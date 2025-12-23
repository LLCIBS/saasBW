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
# Ключ: (user_id, connection_id) для полной изоляции между пользователями
_sync_threads = {}
_sync_lock = threading.Lock()


def sync_ftp_connection(connection_id: int, user_id: Optional[int] = None):
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
        
        config = get_config()
        engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
        
        try:
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
                # Если user_id не был явно передан (ручной вызов), берем из строки
                if user_id is None:
                    user_id = row.user_id

                start_from = row.start_from
                last_processed_mtime = row.last_processed_mtime
                last_processed_filename = row.last_processed_filename or ''
                
                # Получаем путь для сохранения файлов из нормализованной таблицы user_config
                user_config_sql = text("""
                    SELECT base_records_path, source_type
                    FROM user_config
                    WHERE user_id = :user_id
                """)
                user_result = connection.execute(user_config_sql, {'user_id': row.user_id})
                user_row = user_result.fetchone()
            
            # Закрываем engine после получения данных
            engine.dispose()
            engine = None
        except Exception as e:
            # Если ошибка при получении данных, закрываем engine и пробрасываем дальше
            if engine is not None:
                try:
                    engine.dispose()
                except Exception:
                    pass
            raise
        
        # Получаем base_records_path из настроек пользователя (user_config)
        user_base_path_str = ''
        source_type = 'local'
        if user_row:
            user_base_path_str = (user_row.base_records_path or '').strip()
            source_type = user_row.source_type or 'local'
        # Если источник не FTP — прекращаем
        if source_type != 'ftp':
            logger.info(f"FTP {row.name}: источник не ftp для пользователя {row.user_id}, пропуск")
            return
        
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
            # Создаем новый engine для обновления ошибки
            if engine is None:
                from config.settings import get_config
                from sqlalchemy import create_engine, text
                config = get_config()
                engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
            try:
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
            finally:
                if engine is not None:
                    engine.dispose()
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

        # ВАЖНО: Оставляем только те файлы, которые подходят под наши шаблоны и расширения.
        # Это нужно сделать ДО фильтра возраста, чтобы parse_filename мог извлечь дату из имени.
        from call_analyzer.utils import is_valid_call_filename
        valid_files = [f for f in filtered_files if is_valid_call_filename(f['name'])]
        
        if len(valid_files) < len(filtered_files):
            logger.info(
                f"FTP {row.name}: отфильтрованы файлы неподходящего формата "
                f"(осталось {len(valid_files)} из {len(filtered_files)})"
            )
        filtered_files = valid_files

        # ВАЖНО: Фильтруем файлы, которые были изменены менее 5 минут назад
        # На FTP-сервере работает скрипт конвертации в стерео (~2 минуты)
        # Используем время из ИМЕНИ ФАЙЛА (call_dt), а не mtime, т.к. mtime может быть некорректным
        current_time = datetime.now()
        min_age_minutes = 5
        files_before_age_filter = len(filtered_files)
        
        logger.info(f"FTP {row.name}: применяем фильтр возраста файлов (минимум {min_age_minutes} минут). Текущее время: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Добавляем логирование для отладки
        filtered_files_with_age = []
        skipped_count = 0
        from call_analyzer.utils import parse_filename
        
        for f in filtered_files:
            # Пытаемся извлечь время звонка из имени файла
            _, _, call_dt = parse_filename(f['name'])
            
            if call_dt:
                # Используем время из имени файла
                age_seconds = (current_time - call_dt).total_seconds()
                if age_seconds >= (min_age_minutes * 60):
                    filtered_files_with_age.append(f)
                else:
                    skipped_count += 1
                    logger.info(
                        f"FTP {row.name}: пропуск файла {f['name']} - возраст {age_seconds:.0f} сек "
                        f"(звонок {call_dt.strftime('%Y-%m-%d %H:%M:%S')}, требуется >= {min_age_minutes * 60} сек)"
                    )
            else:
                # Если не удалось извлечь дату из имени, используем mtime с FTP
                age_seconds = (current_time - f['mtime']).total_seconds()
                if age_seconds >= (min_age_minutes * 60):
                    filtered_files_with_age.append(f)
                    logger.info(f"FTP {row.name}: файл {f['name']} прошел (по mtime): возраст {age_seconds:.0f} сек")
                else:
                    skipped_count += 1
                    logger.info(f"FTP {row.name}: пропуск файла {f['name']} по mtime: возраст {age_seconds:.0f} сек (mtime: {f['mtime'].strftime('%Y-%m-%d %H:%M:%S')})")
        
        filtered_files = filtered_files_with_age
        
        if skipped_count > 0:
            logger.info(
                f"FTP {row.name}: отфильтрованы файлы моложе {min_age_minutes} минут "
                f"(пропущено {skipped_count}, осталось {len(filtered_files)})"
            )
        else:
            logger.info(f"FTP {row.name}: все файлы ({files_before_age_filter}) прошли фильтр возраста")

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
        connection_key = (user_id, connection_id)
        
        last_db_check_time = time.time()
        
        logger.info(f"FTP {connection_name}: начинаем скачивание файлов (всего {len(remote_files)} файлов)")

        for file_info in remote_files:
            # 1. Быстрая проверка авто-синхронизации (in-memory)
            current_thread_name = threading.current_thread().name
            if current_thread_name == f"FtpSync-{user_id}-{connection_id}":
                if connection_key not in _sync_threads:
                    logger.info(f"Авто-синхронизация FTP {connection_id} прервана пользователем (local check)")
                    return
            
            # 2. Проверка статуса в БД (для надежной остановки любой синхронизации)
            # Проверяем каждые 2 секунды
            if time.time() - last_db_check_time > 2.0:
                last_db_check_time = time.time()
                try:
                    # Создаем временный engine для проверки статуса
                    from config.settings import get_config
                    from sqlalchemy import create_engine, text
                    config = get_config()
                    status_engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
                    try:
                        with status_engine.connect() as status_conn:
                            status_sql = text("SELECT is_active FROM ftp_connections WHERE id = :id")
                            res = status_conn.execute(status_sql, {"id": connection_id}).fetchone()
                            if not res or not res.is_active:
                                logger.info(f"Синхронизация FTP {connection_id} прервана (отключено в БД)")
                                return
                    finally:
                        status_engine.dispose()
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
                
                # Дополнительная проверка для формата external-* (пропускаем служебные хвосты)
                filename_lower = filename.lower()
                if filename_lower.startswith("external-"):
                    if ".wav-out." in filename_lower or ".wav-in." in filename_lower:
                        logger.debug(f"Пропускаем файл с хвостом .wav-out. или .wav-in.: {filename}")
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
        
        # Обновляем статистику - создаем новый engine
        from config.settings import get_config
        from sqlalchemy import create_engine, text
        config = get_config()
        update_engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
        try:
            with update_engine.connect() as update_connection:
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
        finally:
            update_engine.dispose()
        
        logger.info(f"FTP синхронизация {row.name} завершена. Скачано файлов: {downloaded}")
            
    except Exception as e:
        logger.error(f"Ошибка синхронизации FTP подключения {connection_id}: {e}", exc_info=True)
        error_engine = None
        try:
            from config.settings import get_config
            from sqlalchemy import create_engine, text
            config = get_config()
            error_engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
            with error_engine.connect() as connection:
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
        finally:
            if error_engine is not None:
                error_engine.dispose()


def _sync_worker(user_id: int, connection_id: int, sync_interval: int):
    """
    Рабочий поток для периодической синхронизации FTP подключения
    """
    logger.info(f"_sync_worker: Запущен поток синхронизации для FTP {connection_id} пользователя {user_id} (интервал {sync_interval} сек)")
    
    consecutive_errors = 0
    max_consecutive_errors = 5  # Максимум 5 ошибок подряд перед остановкой
    
    while True:
        # Проверяем, не остановили ли нас
        if (user_id, connection_id) not in _sync_threads:
            logger.info(f"Поток синхронизации FTP {connection_id} пользователя {user_id} остановлен (удален из активных)")
            break

        engine = None
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
            
            # Закрываем engine перед синхронизацией
            engine.dispose()
            engine = None
            
            sync_ftp_connection(connection_id, user_id=user_id)
            
            # Сбрасываем счетчик ошибок при успешной синхронизации
            consecutive_errors = 0
            
            time.sleep(sync_interval)
            
        except KeyboardInterrupt:
            logger.info(f"Поток синхронизации FTP {connection_id} прерван пользователем")
            break
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Ошибка в потоке синхронизации FTP {connection_id} (ошибка #{consecutive_errors}): {e}", exc_info=True)
            
            # Если слишком много ошибок подряд, останавливаем поток
            if consecutive_errors >= max_consecutive_errors:
                logger.error(f"Поток синхронизации FTP {connection_id} остановлен из-за {consecutive_errors} ошибок подряд")
                # Удаляем поток из активных, чтобы он не перезапустился автоматически
                with _sync_lock:
                    if (user_id, connection_id) in _sync_threads:
                        del _sync_threads[(user_id, connection_id)]
                break
            
            # Экспоненциальная задержка при ошибках (60, 120, 240, 480 секунд)
            error_delay = min(60 * (2 ** (consecutive_errors - 1)), 600)  # Максимум 10 минут
            logger.info(f"Повторная попытка через {error_delay} секунд...")
            time.sleep(error_delay)
        finally:
            # Гарантируем закрытие engine даже при ошибке
            if engine is not None:
                try:
                    engine.dispose()
                except Exception:
                    pass


def start_ftp_sync(connection_id: int, user_id: Optional[int] = None):
    logger.info(f"start_ftp_sync: Запрос на запуск ID={connection_id}, user_id={user_id}")
    with _sync_lock:
        # Если user_id не передан, определим его ниже (после запроса в БД)
        key_to_check = None if user_id is None else (user_id, connection_id)
        if key_to_check and key_to_check in _sync_threads:
            logger.warning(f"start_ftp_sync: Синхронизация для FTP {connection_id} пользователя {user_id} уже запущена (в списке активных)")
            return
        
        engine = None
        try:
            from config.settings import get_config
            from sqlalchemy import create_engine, text
            config = get_config()
            engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
            
            with engine.connect() as connection:
                sql = text("""
                    SELECT id, user_id, name, is_active, sync_interval
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
                
                resolved_user_id = user_id or row.user_id
                key_to_check = (resolved_user_id, connection_id)
                if key_to_check in _sync_threads:
                    logger.warning(f"start_ftp_sync: Синхронизация уже активна для FTP {connection_id} пользователя {resolved_user_id}")
                    return
                
                sync_interval = row.sync_interval or 300
            
            # Закрываем engine перед запуском потока
            engine.dispose()
            engine = None
            
            thread = threading.Thread(
                target=_sync_worker,
                args=(resolved_user_id, connection_id, sync_interval),
                daemon=True,
                name=f"FtpSync-{resolved_user_id}-{connection_id}"
            )
            thread.start()
            _sync_threads[(resolved_user_id, connection_id)] = thread
            
            logger.info(f"start_ftp_sync: Поток запущен и добавлен в реестр для FTP {connection_id}")
            
        except Exception as e:
            logger.error(f"start_ftp_sync: Ошибка запуска: {e}", exc_info=True)
        finally:
            # Гарантируем закрытие engine
            if engine is not None:
                try:
                    engine.dispose()
                except Exception:
                    pass


def _monitor_and_restart_threads():
    """
    Мониторинг потоков синхронизации и их автоматический перезапуск при падении
    """
    logger.info("Запущен мониторинг FTP потоков синхронизации")
    
    while True:
        try:
            time.sleep(30)  # Проверяем каждые 30 секунд
            
            # Сначала собираем список мертвых потоков (с блокировкой)
            dead_threads = []
            with _sync_lock:
                for (user_id, conn_id), thread in list(_sync_threads.items()):
                    if not thread.is_alive():
                        logger.warning(f"Обнаружен мертвый поток синхронизации для FTP {conn_id} пользователя {user_id}, планируем перезапуск")
                        dead_threads.append((user_id, conn_id))
                        # Удаляем из словаря перед перезапуском
                        del _sync_threads[(user_id, conn_id)]
            
            # Перезапускаем мертвые потоки (без блокировки, чтобы избежать deadlock)
            for user_id, conn_id in dead_threads:
                # Проверяем, что подключение все еще активно
                engine = None
                try:
                    from config.settings import get_config
                    from sqlalchemy import create_engine, text
                    config = get_config()
                    engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
                    
                    with engine.connect() as connection:
                        sql = text("""
                            SELECT id, user_id, name, is_active, sync_interval
                            FROM ftp_connections
                            WHERE id = :conn_id
                        """)
                        result = connection.execute(sql, {'conn_id': conn_id})
                        row = result.fetchone()
                        
                        if row and row.is_active:
                            logger.info(f"Перезапускаем поток синхронизации для FTP {conn_id} пользователя {row.user_id} ({row.name})")
                            start_ftp_sync(conn_id, user_id=row.user_id)
                        else:
                            logger.info(f"FTP подключение {conn_id} неактивно, не перезапускаем")
                except Exception as e:
                    logger.error(f"Ошибка при перезапуске потока FTP {conn_id}: {e}", exc_info=True)
                finally:
                    if engine is not None:
                        try:
                            engine.dispose()
                        except Exception:
                            pass
                        
        except Exception as e:
            logger.error(f"Ошибка в мониторе потоков FTP: {e}", exc_info=True)
            time.sleep(60)


def stop_ftp_sync(connection_id: int, user_id: Optional[int] = None):
    """
    Останавливает синхронизацию для конкретного подключения.
    Если user_id не указан — останавливает все потоки с таким connection_id.
    """
    with _sync_lock:
        if user_id is None:
            # Удаляем все потоки с данным connection_id (safety fallback)
            keys_to_remove = [(u, cid) for (u, cid) in _sync_threads.keys() if cid == connection_id]
        else:
            keys_to_remove = [(user_id, connection_id)] if (user_id, connection_id) in _sync_threads else []
        
        for key in keys_to_remove:
            _sync_threads.pop(key, None)
            logger.info(f"Остановлена синхронизация для FTP подключения {key[1]} пользователя {key[0]}")


def start_all_active_ftp_syncs(user_id: Optional[int] = None):
    """????????? ????????????? ??? FTP ???????????, ????????? ?????????????? ? ????????????.
    
    Args:
        user_id: ????????????, ??? ???? ????????? FTP. ???? None, ??????????? ?????? ???."""
    engine = None
    try:
        from config.settings import get_config
        from sqlalchemy import create_engine, text
        
        config = get_config()
        engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
        
        started_count = 0
        
        with engine.connect() as connection:
            params = {}
            user_filter = ''
            if user_id is not None:
                params['filter_user_id'] = user_id
                user_filter = ' AND uc.user_id = :filter_user_id'
            sql = text(f"""
                SELECT uc.user_id, uc.ftp_connection_id, fc.id as conn_id, fc.name
                FROM user_config uc
                JOIN users u ON u.id = uc.user_id AND u.is_active = TRUE
                JOIN ftp_connections fc ON fc.id = uc.ftp_connection_id AND fc.user_id = uc.user_id
                WHERE uc.source_type = 'ftp' AND fc.is_active = TRUE{user_filter}
            """)
            result = connection.execute(sql, params)
            
            seen = set()
            for row in result:
                key = (row.user_id, row.conn_id)
                if not row.conn_id or key in seen:
                    continue
                seen.add(key)
                try:
                    start_ftp_sync(row.conn_id, user_id=row.user_id)
                    started_count += 1
                    logger.info(f"Запущена FTP синхронизация для пользователя {row.user_id}: {row.name}")
                except Exception as e:
                    logger.error(f"Ошибка запуска синхронизации для FTP {row.conn_id}: {e}")
        
        scope_msg = f' ??? ???????????? {user_id}' if user_id is not None else ''
        logger.info(f"???????? ????????????? ??? {started_count} FTP ??????????? (????????? ??????????????){scope_msg}")
        
        # Запускаем мониторинг потоков (только один раз)
        if not hasattr(start_all_active_ftp_syncs, '_monitor_started'):
            monitor_thread = threading.Thread(
                target=_monitor_and_restart_threads,
                daemon=True,
                name="FtpSyncMonitor"
            )
            monitor_thread.start()
            start_all_active_ftp_syncs._monitor_started = True
            logger.info("Запущен мониторинг FTP потоков синхронизации")
        
    except Exception as e:
        logger.error(f"Ошибка запуска FTP синхронизаций: {e}", exc_info=True)
    finally:
        # Гарантируем закрытие engine
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass


def stop_all_ftp_syncs():
    """Останавливает все FTP синхронизации"""
    with _sync_lock:
        keys = list(_sync_threads.keys())
        for user_id, conn_id in keys:
            stop_ftp_sync(conn_id, user_id=user_id)
        logger.info("Остановлены все FTP синхронизации")
