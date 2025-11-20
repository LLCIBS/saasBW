# call_analyzer/ftp_sync_manager.py
"""
Менеджер для синхронизации файлов с FTP/SFTP серверов
"""

import logging
import threading
import time
from datetime import datetime
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
            remote_files = ftp.list_files(recursive=True)
            logger.info(f"Найдено {len(remote_files)} файлов на FTP сервере {row.host}")
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

        for file_info in remote_files:
            try:
                filename = file_info['name']
                relative_path = file_info.get('relative_path') or filename
                
                # Исправление дублирования путей: сохраняем файл прямо в целевую папку дня
                # Игнорируем структуру папок с FTP, так как мы уже в папке нужного дня
                local_file_path = target_folder / filename
                
                # Пропускаем, если файл уже существует
                if local_file_path.exists():
                    logger.debug(f"Файл уже существует, пропускаем: {filename}")
                    continue
                
                # Проверяем формат имени файла
                filename_lower = filename.lower()
                is_valid_name = (
                    filename_lower.startswith("fs_") or 
                    filename_lower.startswith("external-") or 
                    filename_lower.startswith("in-") or
                    filename_lower.startswith("вход_") or
                    filename_lower.startswith("out-")
                )
                valid_extensions = ['.mp3', '.wav']
                is_valid_ext = any(filename_lower.endswith(ext) for ext in valid_extensions)
                
                if not is_valid_name or not is_valid_ext:
                    # Для out- файлов может быть много ложных срабатываний в мониторинге,
                    # но мы добавили out- в разрешенные, поэтому warning будет только на совсем левые файлы
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
    logger.info(f"Запущен поток синхронизации для FTP подключения {connection_id}")
    
    while True:
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
    with _sync_lock:
        if connection_id in _sync_threads:
            logger.warning(f"Синхронизация для FTP подключения {connection_id} уже запущена")
            return
        
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
                logger.error(f"FTP подключение {connection_id} не найдено")
                return
            
            if not row.is_active:
                logger.info(f"FTP подключение {row.name} неактивно, не запускаем синхронизацию")
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
        
        logger.info(f"Запущена синхронизация для FTP подключения {connection_id}")


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
