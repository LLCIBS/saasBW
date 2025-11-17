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
                SELECT id, user_id, name, host, port, username, password, 
                       remote_path, protocol, is_active, sync_interval
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
        # На Ubuntu важно использовать resolve() для получения абсолютного пути
        # На Windows это тоже работает корректно
        try:
            base_path = base_path.resolve()
        except (OSError, ValueError) as e:
            # Если не удалось разрешить (например, путь не существует), создаем как есть
            logger.warning(f"Не удалось разрешить базовый путь {user_base_path_str}, используем как есть: {e}")
            base_path = Path(user_base_path_str)
        
        # Создаем структуру папок как для локальных файлов: BASE_RECORDS_PATH/YYYY/MM/DD
        target_folder = base_path / str(today.year) / f"{today.month:02d}" / f"{today.day:02d}"
        target_folder.mkdir(parents=True, exist_ok=True)
        
        # Нормализуем target_folder для единообразия
        try:
            target_folder = target_folder.resolve()
        except (OSError, ValueError):
            # Если не удалось разрешить, используем как есть
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
            remote_files = ftp.list_files()
            logger.info(f"Найдено {len(remote_files)} файлов на FTP сервере {row.host}")
        except Exception as e:
            error_msg = f"Ошибка получения списка файлов: {str(e)}"
            logger.error(f"FTP {row.name}: {error_msg}")
            # Обновляем ошибку в БД в отдельном соединении
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
        
        # Скачиваем новые файлы
        downloaded = 0
        downloaded_files = []  # Список скачанных файлов для ручной обработки
        
        for file_info in remote_files:
            try:
                filename = file_info['name']
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
                    filename_lower.startswith("вход_")
                )
                valid_extensions = ['.mp3', '.wav']
                is_valid_ext = any(filename_lower.endswith(ext) for ext in valid_extensions)
                
                if not is_valid_name or not is_valid_ext:
                    logger.warning(f"Файл {filename} не соответствует формату (должен начинаться с fs_/external-/in-/вход_ и иметь расширение .mp3/.wav). Пропускаем.")
                    continue
                
                # Скачиваем файл
                if ftp.download_file(filename, local_file_path):
                    downloaded += 1
                    downloaded_files.append(local_file_path)
                    logger.info(f"✓ Скачан файл: {filename} -> {local_file_path}")
                
            except Exception as e:
                logger.error(f"Ошибка скачивания файла {file_info.get('name', 'unknown')}: {e}")
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
                        # Нормализуем путь для кроссплатформенности
                        # На Ubuntu важно использовать resolve() для получения абсолютного пути
                        # На Windows это тоже работает корректно
                        try:
                            normalized_path = file_path.resolve()
                        except (OSError, ValueError) as e:
                            logger.warning(f"Не удалось разрешить путь {file_path}, используем как есть: {e}")
                            normalized_path = file_path
                        
                        # Проверяем существование файла
                        if not normalized_path.exists():
                            logger.warning(f"Файл не существует, пропускаем: {normalized_path}")
                            continue
                        
                        # Используем str() для преобразования в строку - это работает корректно на обеих ОС
                        # Path.resolve() уже нормализовал путь для текущей ОС
                        path_str = str(normalized_path)
                        
                        # Создаем mock события для watchdog
                        mock_event = SimpleNamespace(
                            src_path=path_str,
                            is_directory=False
                        )
                        handler.on_created(mock_event)
                        logger.info(f"→ Файл {file_path.name} передан в обработку (путь: {path_str}, ОС: {platform.system()})")
                    except Exception as e:
                        logger.error(f"Ошибка обработки файла {file_path.name}: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Ошибка инициализации CallHandler: {e}", exc_info=True)
        
        # Обновляем статистику в отдельном соединении
        with engine.connect() as update_connection:
            update_sql = text("""
                UPDATE ftp_connections
                SET last_sync = :now, last_error = NULL, 
                    download_count = download_count + :downloaded
                WHERE id = :conn_id
            """)
            with update_connection.begin():
                update_connection.execute(update_sql, {
                    'now': datetime.utcnow(),
                    'downloaded': downloaded,
                    'conn_id': connection_id
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
    
    Args:
        connection_id: ID подключения
        sync_interval: Интервал синхронизации в секундах
    """
    logger.info(f"Запущен поток синхронизации для FTP подключения {connection_id}")
    
    while True:
        try:
            # Проверяем, активно ли подключение (без Flask context)
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
            
            # Выполняем синхронизацию
            sync_ftp_connection(connection_id)
            
            # Ждем до следующей синхронизации
            time.sleep(sync_interval)
            
        except Exception as e:
            logger.error(f"Ошибка в потоке синхронизации FTP {connection_id}: {e}", exc_info=True)
            time.sleep(60)  # Ждем минуту перед повтором при ошибке


def start_ftp_sync(connection_id: int):
    """
    Запускает фоновую синхронизацию для FTP подключения
    
    Args:
        connection_id: ID подключения
    """
    with _sync_lock:
        if connection_id in _sync_threads:
            logger.warning(f"Синхронизация для FTP подключения {connection_id} уже запущена")
            return
        
        # Получаем интервал синхронизации (без Flask context)
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
        
        # Создаем и запускаем поток
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
    """
    Останавливает синхронизацию для FTP подключения
    
    Args:
        connection_id: ID подключения
    """
    with _sync_lock:
        if connection_id not in _sync_threads:
            return
        
        # Поток остановится сам, когда увидит, что подключение неактивно
        # Просто удаляем из словаря
        del _sync_threads[connection_id]
        logger.info(f"Остановлена синхронизация для FTP подключения {connection_id}")


def start_all_active_ftp_syncs():
    """Запускает синхронизацию для FTP подключений, выбранных пользователями в конфигурации"""
    try:
        from config.settings import get_config
        from sqlalchemy import create_engine, text
        from common.user_settings import default_config_template
        import json
        
        # Создаем подключение к БД напрямую, без Flask контекста
        config = get_config()
        engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
        
        started_count = 0
        
        with engine.connect() as connection:
            # Получаем всех пользователей с настройками
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
                
                # Парсим JSON данные
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                
                config_data = data.get('config') or default_config_template()
                paths_cfg = config_data.get('paths') or {}
                source_type = paths_cfg.get('source_type', 'local')
                ftp_connection_id = paths_cfg.get('ftp_connection_id')
                
                # Если пользователь выбрал FTP как источник
                if source_type == 'ftp' and ftp_connection_id:
                    # Проверяем, что подключение существует и активно
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

