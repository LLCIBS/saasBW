# call_analyzer/main.py

import logging
import sys
import time
from datetime import datetime
from pathlib import Path  # added for watcher paths

import config as profile_config
config = profile_config

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 1) �����?�����? ������?
def setup_logging():
    profile_label = getattr(profile_config, 'PROFILE_LABEL', 'global')
    log_file = 'bestway.log' if profile_label == 'global' else f'bestway_{profile_label}.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding='utf-8')
        ]
    )

setup_logging()
logger = logging.getLogger(__name__)
logger.info('[MAIN][%s] Call Analyzer worker starting.', getattr(profile_config, 'PROFILE_LABEL', 'global'))

import threading
import os
from watchdog.observers import Observer

try:
    from call_analyzer import call_handler as handler  # type: ignore
    from call_analyzer.call_handler import CallHandler, get_current_folder, IngressHandler  # type: ignore
    from call_analyzer.utils import send_alert  # type: ignore
    from call_analyzer.reports.week_full import run_week_full  # type: ignore
    from call_analyzer.reports.rr_3 import run_rr_3  # type: ignore
    from call_analyzer.reports.rr_bad import run_rr_bad  # type: ignore
    from call_analyzer.reports.skolko_52 import run_skolko_52  # type: ignore
    from call_analyzer.transfer_recall.transfer import load_transfer_cases, check_transfer_deadlines, check_transfer_notifications  # type: ignore
    from call_analyzer.transfer_recall.recall import load_recall_cases, check_recall_notifications  # type: ignore
except ImportError:
    import call_handler as handler
    from call_handler import CallHandler, get_current_folder, IngressHandler
    from utils import send_alert
    from reports.week_full import run_week_full
    from reports.rr_3 import run_rr_3
    from reports.rr_bad import run_rr_bad
    from reports.skolko_52 import run_skolko_52
    from transfer_recall.transfer import load_transfer_cases, check_transfer_deadlines, check_transfer_notifications
    from transfer_recall.recall import load_recall_cases, check_recall_notifications


load_transfer_cases()
load_recall_cases()
# from call_analyzer.transfer_recall.recall import add_recall_case

def scan_current_day_folder(event_handler, current_folder_path):
    """
    Сканирует папку текущего дня и обрабатывает необработанные файлы.
    
    Args:
        event_handler: Экземпляр CallHandler для обработки файлов
        current_folder_path: Путь к папке текущего дня
    """
    logger = logging.getLogger(__name__)
    
    try:
        from types import SimpleNamespace
        from call_analyzer.call_handler import get_result_file_path
        from call_analyzer.utils import is_valid_call_filename
        
        if not os.path.exists(current_folder_path):
            return 0
        
        # Ищем все аудиофайлы в папке дня
        existing_files = list(Path(current_folder_path).glob("*.mp3")) + list(Path(current_folder_path).glob("*.wav"))
        
        processed_count = 0
        skipped_count = 0
        
        for file_path in existing_files:
            name_lower = file_path.name.lower()
            
            # Проверяем валидность имени файла
            if not is_valid_call_filename(file_path.name):
                continue
            
            # Пропускаем файлы с хвостами .wav-out. и .wav-in. для external-*
            if name_lower.startswith("external-"):
                if ".wav-out." in name_lower or ".wav-in." in name_lower:
                    continue
            
            # Проверяем расширение
            if file_path.suffix.lower() not in ['.mp3', '.wav']:
                continue
            
            # Проверяем, не был ли файл уже обработан
            result_file = get_result_file_path(file_path)
            if result_file.exists():
                skipped_count += 1
                continue
            
            # Файл не обработан - обрабатываем
            try:
                logger.info(f"[SCAN] Найден необработанный файл: {file_path.name}")
                
                mock_event = SimpleNamespace(
                    src_path=str(file_path.resolve()),
                    is_directory=False
                )
                event_handler.on_created(mock_event)
                processed_count += 1
                
                # Небольшая задержка, чтобы не перегружать систему
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"[SCAN] Ошибка обработки файла {file_path.name}: {e}", exc_info=True)
        
        if processed_count > 0:
            logger.info(
                f"[SCAN] Переобход папки завершен. "
                f"Найдено файлов: {len(existing_files)}, "
                f"пропущено (уже обработано): {skipped_count}, "
                f"отправлено на обработку: {processed_count}"
            )
        
        return processed_count
        
    except Exception as e:
        logger.error(f"[SCAN] Ошибка при сканировании папки {current_folder_path}: {e}", exc_info=True)
        return 0

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("[MAIN] Call Analyzer event loop starting")

    # 1. Проверяем и создаем папку для сегодняшних звонков
    path = get_current_folder()
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
            logger.info(f"[MAIN] Создана папка для сегодняшних звонков: {path}")
        except Exception as e:
            msg = f"[MAIN] Ошибка при создании папки {path}: {e}"
            logger.error(msg)
            send_alert(msg)
            return

    # 2. Запуск Watchdog
    event_handler = CallHandler()
    ingress_handler = IngressHandler(event_handler)
    observer = Observer()
    root_watch_path = str(Path(str(profile_config.BASE_RECORDS_PATH)))
    Path(root_watch_path).mkdir(parents=True, exist_ok=True)

    def schedule_watchers(target_folder: str):
        logger.info("[MAIN] Начат мониторинг корня: %s", root_watch_path)
        logger.info("[MAIN] Начат мониторинг папки дня: %s", target_folder)
        observer.schedule(ingress_handler, root_watch_path, recursive=False)
        observer.schedule(event_handler, target_folder, recursive=False)
    try:
        schedule_watchers(path)
        observer.start()
        logger.info(f"[MAIN] Начат мониторинг папки: {path}")
        
        # Обработка существующих файлов при запуске
        logger.info(f"[MAIN] Сканирование существующих файлов в папке: {path}")
        try:
            from types import SimpleNamespace
            from call_analyzer.call_handler import get_result_file_path
            existing_files = list(Path(path).glob("*.mp3")) + list(Path(path).glob("*.wav"))
            processed_count = 0
            skipped_count = 0
            for file_path in existing_files:
                name_lower = file_path.name.lower()
                # Проверяем те же условия, что и в CallHandler
                # Файлы формата out-* пропускаются
                from call_analyzer.utils import is_valid_call_filename
                if not is_valid_call_filename(file_path.name):
                    continue
                
                # Пропускаем файлы с хвостами .wav-out. и .wav-in. для external-*
                if name_lower.startswith("external-"):
                    if ".wav-out." in name_lower or ".wav-in." in name_lower:
                        continue
                
                # Проверяем расширение
                if file_path.suffix.lower() not in ['.mp3', '.wav']:
                    continue
                
                # Проверяем, не был ли файл уже обработан
                result_file = get_result_file_path(file_path)
                if result_file.exists():
                    skipped_count += 1
                    logger.debug(f"[MAIN] Файл {file_path.name} уже обработан, пропускаем")
                    continue
                
                # Обрабатываем файл
                try:
                    mock_event = SimpleNamespace(
                        src_path=str(file_path.resolve()),
                        is_directory=False
                    )
                    event_handler.on_created(mock_event)
                    processed_count += 1
                    logger.info(f"[MAIN] Обработан существующий файл: {file_path.name}")
                except Exception as e:
                    logger.error(f"[MAIN] Ошибка обработки файла {file_path.name}: {e}", exc_info=True)
            
            logger.info(f"[MAIN] Обработано существующих файлов: {processed_count} из {len(existing_files)}, пропущено уже обработанных: {skipped_count}")
        except Exception as e:
            logger.error(f"[MAIN] Ошибка при сканировании существующих файлов: {e}", exc_info=True)

        # Запуск FTP синхронизации (всегда, независимо от режима)
        # start_all_active_ftp_syncs() сама проверит активные подключения пользователей из БД
        # и запустит только те, которые выбраны пользователями в их конфигурации
        # start_ftp_sync() защищен от дубликатов - если поток уже запущен, просто вернется
        try:
            from call_analyzer.ftp_sync_manager import start_all_active_ftp_syncs
            logger.info("[MAIN] ?????? FTP ?????????????...")
            profile_user_id = getattr(profile_config, "PROFILE_USER_ID", None)
            try:
                ftp_user_id = int(profile_user_id) if profile_user_id else None
            except (TypeError, ValueError):
                ftp_user_id = None
            start_all_active_ftp_syncs(user_id=ftp_user_id)
        except Exception as e:
            logger.error(f"[MAIN] ?????? ??????? FTP ?????????????: {e}")


        # 3. Основной цикл
        last_scan_minute = None  # Для отслеживания последней минуты переобхода
        while True:
            now = datetime.now()
            time_str = now.strftime("%H:%M")
            day_of_week = now.weekday()  # 0=понедельник, 6=воскресенье

            # Пример: запуск run_skolko() в 20:00
            if time_str == "20:00":
                run_skolko_52()

            # Запуск run_week_full() по понедельникам в 05:00
            if day_of_week == 6 and time_str == "20:10":
                run_week_full()

            # По понедельникам в 11:00 -> run_rr_3
            if day_of_week == 6 and time_str == "20:02":
                run_rr_3()

            if day_of_week == 6 and time_str == "20:05":
               run_rr_bad()          

            check_transfer_notifications()
            check_transfer_deadlines()
            
            check_recall_notifications()
            
            # Проверка смены папки, idle-time и т.д.
            current_path = get_current_folder()
            if os.path.exists(current_path) and path != current_path:
                try:
                    logger.info(f"[MAIN] Переключение наблюдения на {current_path}")
                    observer.unschedule_all()
                    schedule_watchers(current_path)
                    path = current_path
                except Exception as e:
                    msg = f"[MAIN] Ошибка при переключении директории: {e}"
                    logger.error(msg)
                    send_alert(msg)
            elif not os.path.exists(current_path):
                # Создаем папку для нового дня, если её нет
                try:
                    os.makedirs(current_path, exist_ok=True)
                    logger.info(f"[MAIN] Создана папка для нового дня: {current_path}")
                    # Переключаемся на новую папку
                    observer.unschedule_all()
                    schedule_watchers(current_path)
                    path = current_path
                except Exception as e:
                    msg = f"[MAIN] Ошибка при создании папки дня {current_path}: {e}"
                    logger.error(msg)
                    send_alert(msg)

            current_hour = now.hour

            
            # Проверка, прошло ли более 20 минут с момента последней обработки файла
            if handler.last_processed_time is not None:
                time_since_last_processed = (now - handler.last_processed_time).total_seconds() / 60  # Время в минутах
                if 8 <= current_hour < 20:
                    if time_since_last_processed > 20 and (
                            handler.last_alert_time is None or (
                            now - handler.last_alert_time).total_seconds() / 60 > 20):
                        alert_message = f"Программа не обрабатывала новые файлы более 20 минут.\nПоследняя обработка была в {handler.last_processed_time.strftime('%Y-%m-%d %H:%M:%S')}"
                        logging.warning(alert_message)
                        send_alert(alert_message)
                        handler.last_alert_time = now  # Обновляем глобальную переменную в модуле
                        logging.info(
                            f"Тревожное сообщение отправлено. Время последней отправки обновлено: {handler.last_alert_time}")
                else:
                    logging.info("Вне рабочего времени, тревожные сообщения не отправляются.")
            else:
                logging.info("Файлы ещё не обрабатывались. Устанавливаем время последней обработки на текущее.")
                handler.last_processed_time = now

            # Периодический переобход папки текущего дня (каждые 30 минут)
            # Проверяем каждые 30 минут (минута == 0 или минута == 30)
            # Защита от повторных вызовов в одну и ту же минуту
            if now.minute in [0, 30] and last_scan_minute != now.minute:
                try:
                    current_day_path = get_current_folder()
                    if os.path.exists(current_day_path):
                        scan_current_day_folder(event_handler, current_day_path)
                        last_scan_minute = now.minute  # Запоминаем минуту переобхода
                except Exception as e:
                    logger.error(f"[MAIN] Ошибка при периодическом переобходе папки: {e}", exc_info=True)
            elif now.minute not in [0, 30]:
                # Сбрасываем флаг, когда минута изменилась на не-0/30
                last_scan_minute = None

            time.sleep(60)

    except KeyboardInterrupt:
        logger.info("[MAIN] Остановка наблюдателя (KeyboardInterrupt).")
        observer.stop()
    except Exception as e:
        msg = f"[MAIN] Неизвестная ошибка: {e}"
        logger.error(msg)
        send_alert(msg)
    finally:
        try:
            if observer.is_alive():
                observer.stop()
                observer.join()
        except:
            pass
        logger.info("[MAIN] main.py завершён.")

if __name__ == "__main__":
    main()
