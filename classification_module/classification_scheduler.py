#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Планировщик задач для автоматического запуска классификации
"""

import time
import threading
import json
import logging
from datetime import datetime
try:
    from .classification_rules import ClassificationRulesManager
    from .classification_engine import CallClassificationEngine
    from .max_notify import send_excel_report_to_max
except ImportError:
    from classification_rules import ClassificationRulesManager
    from classification_engine import CallClassificationEngine
    from max_notify import send_excel_report_to_max
import os
from pathlib import Path

import requests

# Настройка логирования для планировщика
logger = logging.getLogger(__name__)

class ClassificationScheduler:
    def __init__(self, rules_manager, classification_engine, upload_folder="uploads", flask_app=None):
        self.rules_manager = rules_manager
        self.classification_engine = classification_engine
        self.upload_folder = upload_folder
        self.flask_app = flask_app
        self.running = False
        self.scheduler_thread = None
        self.check_interval = 60  # Проверяем каждую минуту
        self.running_tasks = set()  # Отслеживаем выполняющиеся задачи
        self.task_progress = {}  # Прогресс выполнения задач: {schedule_id: {...}}
        self.lock = threading.Lock()  # Блокировка для потокобезопасности
        
    def start(self):
        """Запустить планировщик"""
        if self.running:
            return
            
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        print("Планировщик задач запущен")
    
    def stop(self):
        """Остановить планировщик"""
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join()
        print("Планировщик задач остановлен")
    
    def _scheduler_loop(self):
        """Основной цикл планировщика"""
        while self.running:
            try:
                if self.flask_app is not None:
                    with self.flask_app.app_context():
                        self._check_and_run_schedules()
                else:
                    self._check_and_run_schedules()
                time.sleep(self.check_interval)
            except Exception as e:
                print(f"Ошибка в планировщике: {e}")
                time.sleep(self.check_interval)
    
    def _check_and_run_schedules(self):
        """Проверить и запустить расписания"""
        try:
            due_schedules = self.rules_manager.get_due_schedules()
            
            if due_schedules:
                logger.info(f"Найдено {len(due_schedules)} расписаний для выполнения")
                print(f"📅 Найдено {len(due_schedules)} расписаний для выполнения")
            
            for schedule in due_schedules:
                try:
                    print(f"🚀 Запуск расписания: {schedule['name']} (ID: {schedule['id']})")
                    logger.info(f"Запуск расписания: {schedule['name']} (ID: {schedule['id']})")
                    self._run_scheduled_classification(schedule)
                except Exception as e:
                    error_msg = f"Ошибка при выполнении расписания {schedule['name']}: {e}"
                    print(f"❌ {error_msg}")
                    logger.error(error_msg, exc_info=True)
                    # Обновляем статистику ошибок
                    self.rules_manager.update_schedule_run_stats(schedule['id'], success=False)
        except Exception as e:
            logger.error(f"Критическая ошибка в _check_and_run_schedules: {e}", exc_info=True)
            print(f"❌ Критическая ошибка при проверке расписаний: {e}")
    
    def _run_scheduled_classification(self, schedule):
        """Выполнить запланированную классификацию"""
        schedule_id = schedule['id']
        
        # Проверяем, не выполняется ли уже это расписание
        with self.lock:
            if schedule_id in self.running_tasks:
                print(f"⚠️ Расписание {schedule_id} уже выполняется, пропускаем дублирующий запуск")
                return
            self.running_tasks.add(schedule_id)
            # Инициализируем прогресс
            self.task_progress[schedule_id] = {
                'status': 'running',
                'progress': 0,
                'processed_files': 0,
                'total_files': 0,
                'current_file': '',
                'message': 'Подготовка...',
                'start_time': time.time(),
                'output_file': None
            }
        
        try:
            input_folder = schedule['input_folder']
            context_days = schedule['context_days']
            
            # СРАЗУ обновляем время следующего запуска, чтобы избежать повторного выполнения
            self.rules_manager.update_next_run(schedule_id)
            
            # Генерируем имя выходного файла
            now = datetime.now()
            date_str = now.strftime("%d%m%Y_%H%M")
            output_file = f"call_classification_results_scheduled_{schedule_id}_{date_str}.xlsx"
            output_path = os.path.join(self.upload_folder, output_file)
            
            # Если папка задана динамически, вычисляем её из настроек и текущей даты
            if input_folder == '__DYNAMIC__':
                try:
                    # Читаем конфигурацию расписания, чтобы понять режим дня
                    rules = self.rules_manager
                    # Получаем полное расписание для доступа к schedule_config
                    full_schedule = rules.get_schedule(schedule_id)
                    config_json = full_schedule.get('schedule_config') if full_schedule else None
                    dynamic_mode = 'today'
                    offset_days = 0
                    if config_json:
                        import json as _json
                        try:
                            cfg = _json.loads(config_json)
                            dynamic = cfg.get('dynamic_day', {})
                            dynamic_mode = dynamic.get('mode', 'today')
                            offset_days = int(dynamic.get('offset_days', 0))
                        except Exception:
                            pass

                    from datetime import timedelta
                    base_path = rules.get_setting('transcript_base_path', 'D:\\CallRecords')
                    run_date = datetime.now()
                    if dynamic_mode == 'offset':
                        run_date = run_date - timedelta(days=offset_days)
                    # Формируем путь E:\\CallRecords\\YYYY\\MM\\DD\\transcript
                    year = run_date.strftime('%Y')
                    month = run_date.strftime('%m')
                    day = run_date.strftime('%d')
                    input_folder = os.path.join(base_path, year, month, day, 'transcript')
                except Exception as e:
                    print(f"Ошибка вычисления динамической папки для расписания {schedule['name']}: {e}")
                    return
            
            # Проверяем существование папки
            if not os.path.exists(input_folder):
                error_msg = f"Папка {input_folder} не найдена для расписания {schedule['name']}"
                print(f"⚠️ {error_msg}")
                logger.warning(error_msg)
                # Не обновляем статистику как ошибку, так как папка может появиться позже
                # Просто пропускаем выполнение
                return
            
            # Запускаем классификацию
            logger.info(f"📂 Обработка папки: {input_folder}")
            logger.info(f"📄 Выходной файл: {output_path}")
            logger.info(f"📅 Контекст (дней): {context_days}")
            print(f"📂 Обработка папки: {input_folder}")
            print(f"📄 Выходной файл: {output_path}")
            print(f"📅 Контекст (дней): {context_days}")
            
            # Функция обратного вызова для обновления прогресса
            def progress_callback(processed, total, current_file):
                with self.lock:
                    if schedule_id in self.task_progress:
                        progress = int((processed / total) * 100) if total > 0 else 0
                        self.task_progress[schedule_id].update({
                            'progress': progress,
                            'processed_files': processed,
                            'total_files': total,
                            'current_file': current_file or '',
                            'message': f'Обработка {processed}/{total} файлов...'
                        })
            
            # Обновляем прогресс - начало обработки
            with self.lock:
                if schedule_id in self.task_progress:
                    self.task_progress[schedule_id]['message'] = 'Загрузка файлов...'
            
            try:
                result = self.classification_engine.process_folder(
                    input_folder=input_folder,
                    output_file=output_path,
                    context_days=context_days,
                    progress_callback=progress_callback
                )
                
                # Обрабатываем разные варианты возврата
                if isinstance(result, tuple):
                    if len(result) >= 3:
                        results, _, total_calls = result[0], result[1], result[2]
                    elif len(result) == 2:
                        results, total_calls = result[0], result[1]
                    else:
                        results = result[0] if result else []
                        total_calls = len(results) if results else 0
                else:
                    results = result if result else []
                    total_calls = len(results) if results else 0
                
                logger.info(f"✅ Расписание {schedule['name']} выполнено успешно. Обработано {total_calls} звонков")
                print(f"✅ Расписание {schedule['name']} выполнено успешно. Обработано {total_calls} звонков")
                
                # Обновляем прогресс - завершение
                with self.lock:
                    if schedule_id in self.task_progress:
                        duration = time.time() - self.task_progress[schedule_id]['start_time']
                        self.task_progress[schedule_id].update({
                            'status': 'completed',
                            'progress': 100,
                            'message': f'Завершено. Обработано {total_calls} звонков',
                            'duration': f'{int(duration//60)}м {int(duration%60)}с',
                            'output_file': output_file,
                            'total_calls': total_calls
                        })
            except Exception as proc_error:
                logger.error(f"❌ Ошибка при обработке папки {input_folder}: {proc_error}")
                print(f"❌ Ошибка при обработке папки {input_folder}: {proc_error}")
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"Детали ошибки:\n{error_trace}")
                
                # Обновляем прогресс - ошибка
                with self.lock:
                    if schedule_id in self.task_progress:
                        self.task_progress[schedule_id].update({
                            'status': 'error',
                            'message': f'Ошибка: {str(proc_error)}',
                            'error': str(proc_error)
                        })
                
                traceback.print_exc()
                raise
            
            # Обновляем статистику успешного выполнения
            try:
                self.rules_manager.update_schedule_run_stats(schedule_id, success=True)
                logger.info(f"Статистика расписания {schedule_id} обновлена")
            except Exception as stats_error:
                logger.warning(f"Не удалось обновить статистику: {stats_error}")

            # Попытка отправить файл в Telegram, если включено
            try:
                telegram_enabled = self.rules_manager.get_setting('telegram_enabled', '0') == '1'
                bot_token = self.rules_manager.get_setting('telegram_bot_token', '')
                chat_id = self.rules_manager.get_setting('telegram_chat_id', '')
                if telegram_enabled and bot_token and chat_id and os.path.exists(output_path):
                    url = f'https://api.telegram.org/bot{bot_token}/sendDocument'
                    with open(output_path, 'rb') as f:
                        files = {'document': (os.path.basename(output_path), f, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
                        data = {'chat_id': chat_id, 'caption': f'Запланированный отчет: {os.path.basename(output_path)} ({total_calls} звонков)'}
                        requests.post(url, data=data, files=files, timeout=30)
            except Exception as te:
                print(f"Ошибка отправки отчета в Telegram: {te}")

            # Отправка в MAX (Bot API), если включено — тот же сценарий, что и Excel в Telegram
            try:
                max_enabled = self.rules_manager.get_setting('max_enabled', '0') == '1'
                max_token = (self.rules_manager.get_setting('max_access_token', '') or '').strip()
                max_chat = (self.rules_manager.get_setting('max_chat_id', '') or '').strip()
                max_caption = (
                    f'Запланированный отчет: {os.path.basename(output_path)} ({total_calls} звонков)'
                )
                if max_enabled and max_token and max_chat and os.path.exists(output_path):
                    send_excel_report_to_max(max_token, max_chat, output_path, max_caption)
            except Exception as me:
                logger.warning("Ошибка отправки отчета в MAX: %s", me)
                print(f"Ошибка отправки отчета в MAX: {me}")
                
        except Exception as e:
            print(f"Ошибка при выполнении классификации для расписания {schedule['name']}: {e}")
            self.rules_manager.update_schedule_run_stats(schedule_id, success=False)
        finally:
            # Убираем задачу из списка выполняемых через 60 секунд после завершения
            # (чтобы можно было получить статус)
            def cleanup_progress():
                time.sleep(60)  # Храним прогресс 60 секунд после завершения
                with self.lock:
                    self.running_tasks.discard(schedule_id)
                    if schedule_id in self.task_progress:
                        # Удаляем прогресс только если статус не active
                        if self.task_progress[schedule_id].get('status') in ('completed', 'error'):
                            del self.task_progress[schedule_id]
            
            cleanup_thread = threading.Thread(target=cleanup_progress, daemon=True)
            cleanup_thread.start()
    
    def get_task_progress(self, schedule_id):
        """Получить прогресс выполнения расписания"""
        with self.lock:
            return self.task_progress.get(schedule_id, None)
    
    def run_schedule_now(self, schedule_id):
        """Запустить расписание немедленно"""
        try:
            schedule = self.rules_manager.get_schedule(schedule_id)
            if not schedule:
                raise ValueError(f"Расписание с ID {schedule_id} не найдено")
            
            if not schedule.get('is_active', False):
                raise ValueError(f"Расписание {schedule['name']} неактивно")
            
            logger.info(f"🚀 Запуск расписания вручную: {schedule['name']} (ID: {schedule_id})")
            print(f"🚀 Запуск расписания вручную: {schedule['name']} (ID: {schedule_id})")
            
            # Проверяем структуру расписания
            logger.info(f"Структура расписания: input_folder={schedule.get('input_folder')}, context_days={schedule.get('context_days')}")
            
            # Создаем временную структуру для запуска
            temp_schedule = {
                'id': schedule_id,
                'name': schedule['name'],
                'input_folder': schedule.get('input_folder', '__DYNAMIC__'),
                'context_days': schedule.get('context_days', 2)
            }
            
            logger.info(f"Запуск с параметрами: {temp_schedule}")
            self._run_scheduled_classification(temp_schedule)
            logger.info(f"✅ Расписание {schedule['name']} успешно завершено")
            print(f"✅ Расписание {schedule['name']} успешно завершено")
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"❌ Ошибка при запуске расписания {schedule_id}: {e}\n{error_details}")
            print(f"❌ Ошибка при запуске расписания {schedule_id}: {e}")
            traceback.print_exc()
            raise
    
    def get_scheduler_status(self):
        """Получить статус планировщика"""
        return {
            'running': self.running,
            'check_interval': self.check_interval,
            'active_schedules': len(self.rules_manager.get_schedules(active_only=True))
        }

# Глобальный экземпляр планировщика
scheduler_instance = None

def get_scheduler():
    """Получить глобальный экземпляр планировщика (нужны CLASSIFICATION_USER_ID и импорт Flask app)."""
    global scheduler_instance
    if scheduler_instance is None:
        try:
            from web_interface.app import app as flask_app
        except Exception as exc:
            raise RuntimeError(
                "standalone-планировщик: не удалось импортировать web_interface.app; "
                "для БД используйте планировщик, встроенный в веб-приложение."
            ) from exc
        uid = int(os.environ.get("CLASSIFICATION_USER_ID", "0") or 0)
        if uid <= 0:
            raise RuntimeError("Задайте CLASSIFICATION_USER_ID в окружении для standalone планировщика.")
        root = Path(os.environ.get("CLASSIFICATION_ROOT", "classification")).resolve()
        with flask_app.app_context():
            rules_manager = ClassificationRulesManager(
                user_id=uid, classification_root=root
            )
            classification_engine = CallClassificationEngine(
                user_id=uid, classification_root=root
            )
        scheduler_instance = ClassificationScheduler(
            rules_manager,
            classification_engine,
            upload_folder=str(root / "uploads"),
            flask_app=flask_app,
        )
    return scheduler_instance

def start_scheduler():
    """Запустить глобальный планировщик"""
    scheduler = get_scheduler()
    scheduler.start()

def stop_scheduler():
    """Остановить глобальный планировщик"""
    global scheduler_instance
    if scheduler_instance:
        scheduler_instance.stop()
        scheduler_instance = None

if __name__ == "__main__":
    # Тестирование планировщика
    print("Тестирование планировщика задач...")
    
    scheduler = get_scheduler()
    scheduler.start()
    
    try:
        # Работаем 60 секунд для тестирования
        time.sleep(60)
    except KeyboardInterrupt:
        print("Остановка по Ctrl+C")
    finally:
        scheduler.stop()
        print("Тестирование завершено")
