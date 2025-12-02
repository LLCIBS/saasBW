# call_analyzer/ftp_sync_manager.py
"""
Менеджер для синхронизации файлов с FTP/SFTP серверов
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Глобальный словарь для хранения потоков синхронизации
_sync_threads = {}
_sync_lock = threading.Lock()


def sync_ftp_connection(connection_id: int):
    """
    Синхронизирует файлы с FTP подключением
    
    Args:
        connection_id: ID подключения из базы данных
    """
    logger.info(f"Начало синхронизации FTP подключения {connection_id} (ручная или автоматическая)")
    try:
        # Используем прямое подключение к БД без Flask context
        from config.settings import get_config
        from sqlalchemy import create_engine, text
        from call_analyzer.ftp_sync import FtpSync
        from common.user_settings import default_config_template
        import json
        
        config = get_config()
        engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
        
        # Получаем данные подключения
        with engine.connect() as connection:
            sql = text("""
                SELECT id,
                       user_id,
                       name,
                       host,
                       port,
                       username,
                       password,
                       remote_path,
                       protocol,
                       is_active,
                       sync_interval,
                       start_from,
                       last_processed_mtime,
                       last_processed_filename
                FROM ftp_connections
                WHERE id = :conn_id
            """)
            result = connection.execute(sql, {'conn_id': connection_id})
            row = result.fetchone()
            
            if not row:
                logger.error(f"FTP подключение {connection_id} не найдено")
                return
            
            if not row.is_active:
                logger.info(f"FTP подключение {row.name} неактивно, пропускаем синхронизацию")
                return

            start_from = row.start_from
            last_processed_mtime = row.last_processed_mtime
            last_processed_filename = row.last_processed_filename or ''
            
            # Получаем путь для сохранения файлов из настроек пользователя
            user_settings_sql = text("""
                SELECT data
                FROM user_settings
                WHERE user_id = :user_id
            """)
            user_result = connection.execute(user_settings_sql, {'user_id': row.user_id})
            user_row = user_result.fetchone()
        
        # Закрываем первое соединение перед дальнейшей работой
        
        if user_row and user_row.data:
            if isinstance(user_row.data, str):
                try:
                    user_data = json.loads(user_row.data)
                except json.JSONDecodeError:
                    user_data = {}
            else:
                user_data = user_row.data
            config_data = user_data.get('config') or default_config_template()
        else:
            config_data = default_config_template()
        
        # Получаем base_records_path из настроек пользователя
        paths_cfg = config_data.get('paths') or {}
        user_base_path_str = paths_cfg.get('base_records_path', '').strip()
        
        # Если путь не указан в настройках, используем дефолтный
        if not user_base_path_str:
            default_base = getattr(config, 'BASE_RECORDS_PATH', '/var/calls')
            user_base_path_str = str(Path(str(default_base)) / 'users' / str(row.user_id))
        
        # Определяем папку для сохранения: должна быть папка дня YYYY/MM/DD
        # чтобы watchdog подхватил файлы
        from datetime import datetime
        import platform
        today = datetime.now()
        
        # Нормализуем базовый путь для кроссплатформенности
        base_path = Path(user_base_path_str)
        try:
            base_path = base_path.resolve()
        except (OSError, ValueError) as e:
            logger.warning(f"Не удалось разрешить базовый путь {user_base_path_str}, используем как есть: {e}")
            base_path = Path(user_base_path_str)
        
        # Создаем структуру папок как для локальных файлов: BASE_RECORDS_PATH/YYYY/MM/DD
        target_folder = base_path / str(today.year) / f"{today.month:02d}" / f"{today.day:02d}"
        target_folder.mkdir(parents=True, exist_ok=True)
        
        # Нормализуем target_folder
        try:
            target_folder = target_folder.resolve()
        except (OSError, ValueError):
            pass
        
        logger.info(f"FTP {row.name}: файлы будут сохраняться в {target_folder} (ОС: {platform.system()})")
        
        # Создаем FTP синхронизатор
        ftp = FtpSync(
            host=row.host,
            port=row.port,
            username=row.username,
            password=row.password,
            remote_path=row.remote_path,
            protocol=row.protocol
        )
        
        # Получаем список файлов на удаленном сервере
        try:
            scan_min_date = None
            if last_processed_mtime:
                # Если уже синхронизировали, берем с запасом 2 дня
                scan_min_date = last_processed_mtime - timedelta(days=2)
            elif start_from:
                # Если есть начальная дата
                scan_min_date = start_from
            
            if scan_min_date:
                logger.info(f"FTP {row.name}: сканирование файлов с сервера {row.host} (фильтр даты >= {scan_min_date.strftime('%Y-%m-%d')})")
            else:
                logger.info(f"FTP {row.name}: полное сканирование файлов с сервера {row.host}")

            remote_files = ftp.list_files(recursive=True, min_mtime=scan_min_date)
            logger.info(f"FTP {row.name}: найдено {len(remote_files)} файлов")
        except Exception as e:
            error_msg = f"Ошибка получения списка файлов: {str(e)}"
            logger.error(f"FTP {row.name}: {error_msg}")
            with engine.connect() as update_connection:
                update_sql = text("""
                    UPDATE ftp_connections
                    SET last_error = :error, last_sync = :now
                    WHERE id = :conn_id
                """)
                with update_connection.begin():
                    update_connection.execute(update_sql, {
                        'error': error_msg,
                        'now': datetime.utcnow(),
                        'conn_id': connection_id
                    })
            return
        
        # Нормализуем список файлов и применяем фильтры
        normalized_files = []
        for file_info in remote_files:
            info = dict(file_info)
            file_mtime = info.get('mtime')
            if not isinstance(file_mtime, datetime):
                file_mtime = datetime.utcnow()
            info['mtime'] = file_mtime
            name = info.get('name', '')
            relative_path = info.get('relative_path') or name
            info['name'] = name
            info['relative_path'] = relative_path
            normalized_files.append(info)

        total_detected = len(normalized_files)
        normalized_files.sort(key=lambda f: (f['mtime'], f['relative_path']))

        filtered_files = normalized_files
        if start_from:
            filtered_files = [
                f for f in filtered_files
                if f['mtime'] >= start_from
            ]
            logger.info(
                f"FTP {row.name}: отфильтрованы файлы старше {start_from.isoformat()} "
                f"(осталось {len(filtered_files)} из {total_detected})"
            )

        processed_name_marker = last_processed_filename or ''
        if last_processed_mtime:
            filtered_files = [
                f for f in filtered_files
                if (f['mtime'] > last_processed_mtime) or
                   (f['mtime'] == last_processed_mtime and f['relative_path'] > processed_name_marker)
            ]
            logger.info(
                f"FTP {row.name}: отфильтрованы уже обработанные файлы "
                f"(осталось {len(filtered_files)} из {total_detected})"
            )

        remote_files = filtered_files
        logger.info(
            f"FTP {row.name}: к обработке готово {len(remote_files)} файлов из {total_detected}"
        )

        # Скачиваем новые файлы
        downloaded = 0
        downloaded_files = []
        latest_processed_mtime = last_processed_mtime
        latest_processed_name = last_processed_filename or ''
        
        # Сохраняем нужные поля из row в переменные, чтобы использовать их в цикле
        # даже если объект row станет недоступен
        connection_name = row.name
        connection_local_path = user_base_path_str
        
        last_db_check_time = time.time()
        
        logger.info(f"FTP {connection_name}: начинаем скачивание файлов (всего {len(remote_files)} файлов)")

        for file_info in remote_files:
            # 1. Быстрая проверка авто-синхронизации (in-memory)
            current_thread_name = threading.current_thread().name
            if current_thread_name == f"FtpSync-{connection_id}":
                if connection_id not in _sync_threads:
                    logger.info(f"Авто-синхронизация FTP {connection_id} прервана пользователем (local check)")
                    return
            
            # 2. Проверка статуса в БД (для надежной остановки любой синхронизации)
            # Проверяем каждые 2 секунды
            if time.time() - last_db_check_time > 2.0:
                last_db_check_time = time.time()
                try:
                    with engine.connect() as status_conn:
                        status_sql = text("SELECT is_active FROM ftp_connections WHERE id = :id")
                        res = status_conn.execute(status_sql, {"id": connection_id}).fetchone()
                        if not res or not res.is_active:
                            logger.info(f"Синхронизация FTP {connection_id} прервана (отключено в БД)")
                            return
                except Exception as e:
                    logger.warning(f"Не удалось проверить статус активности FTP: {e}")

            try:
                filename = file_info['name']
                relative_path = file_info.get('relative_path') or filename
                file_size = file_info.get('size', 0)

                # Пропускаем слишком маленькие файлы (до 1 КБ включительно) —
                # это почти всегда обрывки / заглушки.
                if file_size is not None and file_size <= 1024:
                    logger.info(
                        f"FTP: файл {filename} имеет размер {file_size} байт (<= 1 КБ), "
                        f"считается служебным/обрезанным и пропускается."
                    )
                    continue
                
                # Исправление дублирования путей: сохраняем файл в папку, соответствующую дате звонка
                # Извлекаем дату из имени файла, если возможно
                from call_analyzer.utils import parse_filename
                _, _, call_dt = parse_filename(filename)
                
                if call_dt:
                    # Если дата есть, формируем путь YYYY/MM/DD
                    date_folder = call_dt.strftime("%Y/%m/%d")
                    # target_folder - это базовая папка (local_path из настроек)
                    # Нам нужно найти корень base_records_path. 
                    # target_folder уже содержит сегодняшнюю дату в текущей реализации (см. выше)?
                    # Проверим, как target_folder вычисляется. 
                    # В main loop: target_folder = Path(local_path) / datetime.now().strftime("%Y/%m/%d")
                    # Это неправильно для старых файлов.
                    
                    # Нам нужно получить local_path (корень)
                    # local_path доступен из row.local_path (но row может быть устаревшим внутри цикла?)
                    # Лучше взять из target_folder, поднявшись на 3 уровня вверх (DD -> MM -> YYYY -> ROOT)
                    
                    # Вариант надежнее: target_folder вычисляется как Path(row.local_path) / ...
                    # Используем сохраненный local_path
                    local_root = Path(connection_local_path)
                    file_target_folder = local_root / date_folder
                    
                    # Создаем папку, если нет
                    file_target_folder.mkdir(parents=True, exist_ok=True)
                    local_file_path = file_target_folder / filename
                else:
                    # Если дату не удалось извлечь, кладем в текущую папку (как было)
                    local_file_path = target_folder / filename
                
                # Пропускаем, если файл уже существует
                if local_file_path.exists():
                    logger.debug(f"Файл уже существует, пропускаем: {filename}")
                    continue
                
                # Проверяем формат имени файла
                filename_lower = filename.lower()
                # Файлы формата out-* пропускаются
                is_valid_name = (
                    filename_lower.startswith("fs_") or 
                    filename_lower.startswith("external-") or 
                    filename_lower.startswith("вход_")
                )
                
                # Для формата external-* пропускаем файлы с хвостами .wav-out. и .wav-in.
                if filename_lower.startswith("external-"):
                    if ".wav-out." in filename_lower or ".wav-in." in filename_lower:
                        logger.debug(f"Пропускаем файл с хвостом .wav-out. или .wav-in.: {filename}")
                        continue
                
                valid_extensions = ['.mp3', '.wav']
                is_valid_ext = any(filename_lower.endswith(ext) for ext in valid_extensions)

                if not is_valid_name or not is_valid_ext:
                    logger.warning(f"Файл {filename} не соответствует формату. Пропускаем.")
                    continue
                
                # Скачиваем файл
                # Используем relative_path, но FTP client должен понимать, что это может быть полный путь
                # В нашей реализации FtpSync мы передаем relative_path, 
                # но если мы нашли файл рекурсивно, в relative_path уже может быть путь
                # Однако FtpSync.download_file ожидает путь ОТНОСИТЕЛЬНО remote_path
                # Если мы передаем туда file_info['relative_path'], все должно работать
                
                if ftp.download_file(relative_path, local_file_path):
                    downloaded += 1
                    downloaded_files.append(local_file_path)
                    logger.info(f"✓ Скачан файл: {relative_path} -> {local_file_path}")

                    file_mtime = file_info.get('mtime') or datetime.utcnow()
                    if (latest_processed_mtime is None or
                            file_mtime > latest_processed_mtime or
                            (file_mtime == latest_processed_mtime and relative_path > latest_processed_name)):
                        latest_processed_mtime = file_mtime
                        latest_processed_name = relative_path
                
            except Exception as e:
                logger.error(f"Ошибка скачивания файла {file_info.get('relative_path') or file_info.get('name', 'unknown')}: {e}")
                continue
        
        # Вручную обрабатываем скачанные файлы через CallHandler
        if downloaded_files:
            logger.info(f"Запускаем обработку {len(downloaded_files)} скачанных файлов...")
            try:
                from call_analyzer.call_handler import CallHandler
                from types import SimpleNamespace
                import platform
                
                handler = CallHandler()
                for file_path in downloaded_files:
                    try:
                        try:
                            normalized_path = file_path.resolve()
                        except (OSError, ValueError) as e:
                            logger.warning(f"Не удалось разрешить путь {file_path}, используем как есть: {e}")
                            normalized_path = file_path
                        
                        if not normalized_path.exists():
                            logger.warning(f"Файл не существует, пропускаем: {normalized_path}")
                            continue
                        
                        path_str = str(normalized_path)
                        
                        mock_event = SimpleNamespace(
                            src_path=path_str,
                            is_directory=False
                        )
                        handler.on_created(mock_event)
                        logger.info(f"→ Файл {file_path.name} передан в обработку")
                    except Exception as e:
                        logger.error(f"Ошибка обработи файла {file_path.name}: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Ошибка инициализации CallHandler: {e}", exc_info=True)
        
        # Обновляем статистику
        with engine.connect() as update_connection:
            update_sql = text("""
                UPDATE ftp_connections
                SET last_sync = :now,
                    last_error = NULL,
                    download_count = download_count + :downloaded,
                    last_processed_mtime = :last_processed_mtime,
                    last_processed_filename = :last_processed_filename
                WHERE id = :conn_id
            """)
            with update_connection.begin():
                update_connection.execute(update_sql, {
                    'now': datetime.utcnow(),
                    'downloaded': downloaded,
                    'conn_id': connection_id,
                    'last_processed_mtime': latest_processed_mtime,
                    'last_processed_filename': latest_processed_name if latest_processed_mtime else None
                })
        
        logger.info(f"FTP синхронизация {row.name} завершена. Скачано файлов: {downloaded}")
            
    except Exception as e:
        logger.error(f"Ошибка синхронизации FTP подключения {connection_id}: {e}", exc_info=True)
        try:
            from config.settings import get_config
            from sqlalchemy import create_engine, text
            config = get_config()
            engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
            with engine.connect() as connection:
                update_sql = text("""
                    UPDATE ftp_connections
                    SET last_error = :error, last_sync = :now
                    WHERE id = :conn_id
                """)
                with connection.begin():
                    connection.execute(update_sql, {
                        'error': str(e),
                        'now': datetime.utcnow(),
                        'conn_id': connection_id
                    })
        except Exception as inner_e:
            logger.error(f"Ошибка обновления статуса ошибки: {inner_e}")


def _sync_worker(connection_id: int, sync_interval: int):
    """
    Рабочий поток для периодической синхронизации FTP подключения
    """
    logger.info(f"_sync_worker: Запущен поток синхронизации для FTP {connection_id} (интервал {sync_interval} сек)")
    
    while True:
        # Проверяем, не остановили ли нас
        if connection_id not in _sync_threads:
            logger.info(f"Поток синхронизации FTP {connection_id} остановлен (удален из активных)")
            break

        try:
            from config.settings import get_config
            from sqlalchemy import create_engine, text
            config = get_config()
            engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
            
            with engine.connect() as connection:
                sql = text("""
                    SELECT id, is_active
                    FROM ftp_connections
                    WHERE id = :conn_id
                """)
                result = connection.execute(sql, {'conn_id': connection_id})
                row = result.fetchone()
                
                if not row or not row.is_active:
                    logger.info(f"FTP подключение {connection_id} неактивно, останавливаем синхронизацию")
                    break
            
            sync_ftp_connection(connection_id)
            
            time.sleep(sync_interval)
            
        except Exception as e:
            logger.error(f"Ошибка в потоке синхронизации FTP {connection_id}: {e}", exc_info=True)
            time.sleep(60)


def start_ftp_sync(connection_id: int):
    logger.info(f"start_ftp_sync: Запрос на запуск ID={connection_id}")
    with _sync_lock:
        if connection_id in _sync_threads:
            logger.warning(f"start_ftp_sync: Синхронизация для FTP {connection_id} уже запущена (в списке активных)")
            return
        
        try:
            from config.settings import get_config
            from sqlalchemy import create_engine, text
            config = get_config()
            engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
            
            with engine.connect() as connection:
                sql = text("""
                    SELECT id, name, is_active, sync_interval
                    FROM ftp_connections
                    WHERE id = :conn_id
                """)
                result = connection.execute(sql, {'conn_id': connection_id})
                row = result.fetchone()
                
                if not row:
                    logger.error(f"start_ftp_sync: FTP подключение {connection_id} не найдено в БД")
                    return
                
                if not row.is_active:
                    logger.info(f"start_ftp_sync: FTP подключение {row.name} неактивно в БД, отмена запуска")
                    return
                
                sync_interval = row.sync_interval or 300
            
            thread = threading.Thread(
                target=_sync_worker,
                args=(connection_id, sync_interval),
                daemon=True,
                name=f"FtpSync-{connection_id}"
            )
            thread.start()
            _sync_threads[connection_id] = thread
            
            logger.info(f"start_ftp_sync: Поток запущен и добавлен в реестр для FTP {connection_id}")
            
        except Exception as e:
            logger.error(f"start_ftp_sync: Ошибка запуска: {e}", exc_info=True)


def stop_ftp_sync(connection_id: int):
    with _sync_lock:
        if connection_id not in _sync_threads:
            return
        del _sync_threads[connection_id]
        logger.info(f"Остановлена синхронизация для FTP подключения {connection_id}")


def start_all_active_ftp_syncs():
    """Запускает синхронизацию для FTP подключений, выбранных пользователями в конфигурации"""
    try:
        from config.settings import get_config
        from sqlalchemy import create_engine, text
        from common.user_settings import default_config_template
        import json
        
        config = get_config()
        engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
        
        started_count = 0
        
        with engine.connect() as connection:
            sql = text("""
                SELECT us.user_id, us.data
                FROM user_settings us
                WHERE us.data IS NOT NULL
            """)
            result = connection.execute(sql)
            
            for row in result:
                user_id = row.user_id
                data = row.data
                
                if not data:
                    continue
                
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                
                config_data = data.get('config') or default_config_template()
                paths_cfg = config_data.get('paths') or {}
                source_type = paths_cfg.get('source_type', 'local')
                ftp_connection_id = paths_cfg.get('ftp_connection_id')
                
                if source_type == 'ftp' and ftp_connection_id:
                    conn_sql = text("""
                        SELECT id, name, user_id, is_active
                        FROM ftp_connections
                        WHERE id = :conn_id AND user_id = :user_id AND is_active = TRUE
                    """)
                    conn_result = connection.execute(conn_sql, {
                        'conn_id': ftp_connection_id,
                        'user_id': user_id
                    })
                    conn_row = conn_result.fetchone()
                    
                    if conn_row:
                        try:
                            start_ftp_sync(conn_row.id)
                            started_count += 1
                            logger.info(f"Запущена FTP синхронизация для пользователя {user_id}: {conn_row.name}")
                        except Exception as e:
                            logger.error(f"Ошибка запуска синхронизации для FTP {conn_row.id}: {e}")
        
        logger.info(f"Запущена синхронизация для {started_count} FTP подключений (выбранных пользователями)")
        
    except Exception as e:
        logger.error(f"Ошибка запуска FTP синхронизаций: {e}", exc_info=True)


def stop_all_ftp_syncs():
    """Останавливает все FTP синхронизации"""
    with _sync_lock:
        connection_ids = list(_sync_threads.keys())
        for conn_id in connection_ids:
            stop_ftp_sync(conn_id)
        logger.info("Остановлены все FTP синхронизации")
