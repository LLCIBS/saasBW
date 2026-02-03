"""
Сервис для автоматической генерации отчетов по расписанию
Использует APScheduler для управления задачами
"""

from datetime import datetime, timedelta, time as dt_time
from typing import Optional
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from flask import current_app

from database import db
from database.models import ReportSchedule, User

logger = logging.getLogger(__name__)

scheduler: Optional[BackgroundScheduler] = None


def _calc_dates(schedule: ReportSchedule):
    """Вычислить start_date и end_date для отчета на основе настроек периода."""
    today = datetime.now().date()
    period_type = schedule.period_type or 'last_week'
    
    if period_type == 'last_day':
        # Последний день (вчера)
        end_date = today - timedelta(days=1)
        start_date = end_date
    
    elif period_type == 'last_week':
        # Последняя неделя (7 дней назад до вчера)
        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=6)
    
    elif period_type == 'last_month':
        # Последний месяц (30 дней назад до вчера)
        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=29)
    
    elif period_type == 'last_n_days':
        # Последний выбранный интервал дней
        n_days = schedule.period_n_days or 7
        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=n_days - 1)
    
    else:
        # По умолчанию - последняя неделя
        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=6)
    
    return start_date, end_date


def _run_report_job(user_id: int, report_type: str):
    """Фоновый запуск генерации отчета для одного пользователя."""
    from web_interface.app import app, build_user_runtime_config, legacy_config_override
    
    logger.info(f"[Scheduler] ====== TRIGGERED: report={report_type}, user={user_id} at {datetime.now()} ======")
    
    with app.app_context():
        try:
            user = User.query.get(user_id)
            if not user:
                logger.warning(f"[Scheduler] User {user_id} not found for report {report_type}")
                return

            schedule = ReportSchedule.query.filter_by(
                user_id=user_id, 
                report_type=report_type, 
                enabled=True
            ).first()
            
            if not schedule:
                logger.info(f"[Scheduler] No enabled schedule for user={user_id}, report={report_type}")
                return
            
            # Логируем информацию о расписании для отладки
            logger.info(
                f"[Scheduler] Schedule info: type={schedule.schedule_type}, "
                f"weekly_day={schedule.weekly_day}, weekly_time={schedule.weekly_time}, "
                f"daily_time={schedule.daily_time}"
            )

            start_date, end_date = _calc_dates(schedule)
            start_str = start_date.isoformat()
            end_str = end_date.isoformat()

            logger.info(
                f"[Scheduler] Auto run report {report_type} for user={user_id} "
                f"period {start_str}..{end_str}"
            )

            # Импортируем функции генерации отчетов
            try:
                if report_type == 'week_full':
                    from reports.week_full import run_week_full
                elif report_type == 'rr_3':
                    from reports.rr_3 import run_rr_3
                elif report_type == 'rr_bad':
                    from reports.rr_bad import run_rr_bad
                else:
                    logger.error(f"[Scheduler] Unknown report type: {report_type}")
                    return
            except ImportError as e:
                logger.error(f"[Scheduler] Failed to import report module {report_type}: {e}", exc_info=True)
                return

            # Получаем конфигурацию пользователя
            runtime_cfg = build_user_runtime_config(user=user)
            
            base_folder = runtime_cfg.get('paths', {}).get('base_records_path')
            if not base_folder:
                logger.error(f"[Scheduler] No base_records_path for user {user_id}")
                return

            # Запускаем генерацию отчета
            try:
                with legacy_config_override(runtime_cfg):
                    if report_type == 'week_full':
                        start_dt = datetime.combine(start_date, dt_time.min) if start_date else None
                        end_dt = datetime.combine(end_date, dt_time.max) if end_date else None
                        try:
                            result_path = run_week_full(start_date=start_dt, end_date=end_dt, base_folder=base_folder)
                        except TypeError:
                            # Если функция не принимает параметры, вызываем без них
                            result_path = run_week_full(base_folder=base_folder)
                        logger.info(f"[Scheduler] week_full completed: {result_path}")
                    elif report_type == 'rr_3':
                        date_from = datetime.combine(start_date, dt_time.min) if start_date else None
                        date_to = datetime.combine(end_date, dt_time.max) if end_date else None
                        try:
                            run_rr_3(date_from=date_from, date_to=date_to)
                        except TypeError:
                            run_rr_3()
                        logger.info(f"[Scheduler] rr_3 completed")
                    elif report_type == 'rr_bad':
                        date_from = datetime.combine(start_date, dt_time.min) if start_date else None
                        date_to = datetime.combine(end_date, dt_time.max) if end_date else None
                        try:
                            run_rr_bad(date_from=date_from, date_to=date_to)
                        except TypeError:
                            run_rr_bad()
                        logger.info(f"[Scheduler] rr_bad completed")
            except Exception as e:
                logger.error(f"[Scheduler] Error generating report {report_type} for user {user_id}: {e}", exc_info=True)
                return

            # Обновляем время последнего запуска
            schedule.last_run_at = datetime.utcnow()
            
            # Вычисляем следующее время запуска
            if scheduler:
                job = scheduler.get_job(f"user_{user_id}_{report_type}")
                if job and job.next_run_time:
                    schedule.next_run_at = job.next_run_time
            
            db.session.commit()
            logger.info(f"[Scheduler] Successfully completed report {report_type} for user {user_id}")
            
        except Exception as e:
            logger.error(f"[Scheduler] Unexpected error in _run_report_job: {e}", exc_info=True)
            db.session.rollback()


def _add_schedule_job(sched: BackgroundScheduler, schedule: ReportSchedule):
    """Добавить задачу в планировщик на основе расписания."""
    job_id = f"user_{schedule.user_id}_{schedule.report_type}"

    # Логируем полную информацию о расписании для отладки
    logger.info(
        f"[Scheduler] Processing schedule {job_id}: "
        f"type={schedule.schedule_type}, enabled={schedule.enabled}, "
        f"daily_time={schedule.daily_time}, "
        f"weekly_day={schedule.weekly_day}, weekly_time={schedule.weekly_time}, "
        f"interval_value={schedule.interval_value}, interval_unit={schedule.interval_unit}"
    )

    # Удаляем старую задачу, если была
    try:
        sched.remove_job(job_id)
        logger.info(f"[Scheduler] Removed existing job {job_id}")
    except Exception:
        pass

    if not schedule.enabled:
        logger.info(f"[Scheduler] Schedule {job_id} is disabled, skipping")
        return

    trigger = None
    schedule_type = schedule.schedule_type
    
    try:
        # ВАЖНО: проверяем только поля для текущего типа расписания
        if schedule_type == 'daily':
            daily_time = schedule.daily_time
            if not daily_time or not isinstance(daily_time, str) or ':' not in daily_time:
                logger.warning(f"[Scheduler] Invalid daily_time '{daily_time}' for {job_id}, using default 12:00")
                daily_time = '12:00'
            hour, minute = map(int, daily_time.split(':'))
            trigger = CronTrigger(hour=hour, minute=minute)
            logger.info(f"[Scheduler] Created DAILY trigger for {job_id} at {daily_time}")
            
        elif schedule_type == 'interval':
            interval_value = schedule.interval_value
            interval_unit = schedule.interval_unit
            if not interval_value or not interval_unit:
                logger.warning(f"[Scheduler] Missing interval params for {job_id}")
                return
            if interval_unit == 'days':
                trigger = IntervalTrigger(days=int(interval_value))
            elif interval_unit == 'hours':
                trigger = IntervalTrigger(hours=int(interval_value))
            else:
                logger.warning(f"[Scheduler] Unknown interval unit: {interval_unit}")
                return
            logger.info(f"[Scheduler] Created INTERVAL trigger for {job_id}: every {interval_value} {interval_unit}")
            
        elif schedule_type == 'weekly':
            weekly_time = schedule.weekly_time
            if not weekly_time or not isinstance(weekly_time, str) or ':' not in weekly_time:
                logger.warning(f"[Scheduler] Invalid weekly_time '{weekly_time}' for {job_id}, using default 08:00")
                weekly_time = '08:00'
            hour, minute = map(int, weekly_time.split(':'))
            # 0=понедельник ... 6=воскресенье
            day_of_week = schedule.weekly_day if schedule.weekly_day is not None else 0
            trigger = CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute)
            logger.info(f"[Scheduler] Created WEEKLY trigger for {job_id}: day={day_of_week}, time={weekly_time}")
            
        elif schedule_type == 'custom':
            cron_expr = schedule.cron_expression
            if not cron_expr:
                logger.warning(f"[Scheduler] Missing cron_expression for {job_id}")
                return
            try:
                trigger = CronTrigger.from_crontab(cron_expr)
                logger.info(f"[Scheduler] Created CUSTOM trigger for {job_id}: {cron_expr}")
            except Exception as e:
                logger.error(f"[Scheduler] Invalid cron expression '{cron_expr}': {e}")
                return
        else:
            logger.warning(f"[Scheduler] Unknown schedule_type '{schedule_type}' for {job_id}")
            return

        if trigger:
            sched.add_job(
                _run_report_job,
                trigger=trigger,
                args=[schedule.user_id, schedule.report_type],
                id=job_id,
                replace_existing=True,
                max_instances=1,  # Не запускать параллельно
            )
            
            # Обновляем next_run_at в БД
            job = sched.get_job(job_id)
            if job and job.next_run_time:
                schedule.next_run_at = job.next_run_time
                db.session.commit()
                
    except Exception as e:
        logger.error(f"[Scheduler] Error adding schedule {job_id}: {e}", exc_info=True)


def load_all_schedules(app=None):
    """Перезагрузить все расписания из БД в планировщик."""
    if scheduler is None:
        logger.warning("[Scheduler] Scheduler not initialized")
        return
    
    try:
        app_to_use = app or current_app._get_current_object() if hasattr(current_app, '_get_current_object') else None
        if app_to_use:
            with app_to_use.app_context():
                schedules = ReportSchedule.query.filter_by(enabled=True).all()
                logger.info(f"[Scheduler] Loading {len(schedules)} schedules from database")
                for s in schedules:
                    _add_schedule_job(scheduler, s)
                logger.info(f"[Scheduler] Successfully loaded all schedules")
        else:
            # Fallback: используем текущий контекст если доступен
            try:
                schedules = ReportSchedule.query.filter_by(enabled=True).all()
                logger.info(f"[Scheduler] Loading {len(schedules)} schedules from database")
                for s in schedules:
                    _add_schedule_job(scheduler, s)
                logger.info(f"[Scheduler] Successfully loaded all schedules")
            except Exception:
                logger.warning("[Scheduler] Could not load schedules - no app context")
    except Exception as e:
        logger.error(f"[Scheduler] Error loading schedules: {e}", exc_info=True)


def refresh_schedule(schedule_id: int, app=None):
    """Обновить одну запись в планировщике после изменения настроек."""
    if scheduler is None:
        return
    
    try:
        app_to_use = app or current_app._get_current_object() if hasattr(current_app, '_get_current_object') else None
        if app_to_use:
            with app_to_use.app_context():
                schedule = ReportSchedule.query.get(schedule_id)
                if not schedule:
                    logger.warning(f"[Scheduler] Schedule {schedule_id} not found")
                    return
                _add_schedule_job(scheduler, schedule)
                logger.info(f"[Scheduler] Refreshed schedule {schedule_id}")
        else:
            # Fallback
            try:
                schedule = ReportSchedule.query.get(schedule_id)
                if not schedule:
                    logger.warning(f"[Scheduler] Schedule {schedule_id} not found")
                    return
                _add_schedule_job(scheduler, schedule)
                logger.info(f"[Scheduler] Refreshed schedule {schedule_id}")
            except Exception:
                logger.warning(f"[Scheduler] Could not refresh schedule {schedule_id} - no app context")
    except Exception as e:
        logger.error(f"[Scheduler] Error refreshing schedule {schedule_id}: {e}", exc_info=True)


def init_scheduler(app):
    """Инициализировать APScheduler. Вызывать один раз при старте Flask."""
    global scheduler
    if scheduler is not None:
        logger.warning("[Scheduler] Scheduler already initialized")
        return scheduler

    try:
        scheduler = BackgroundScheduler(timezone="Europe/Moscow")
        scheduler.start()
        app.logger.info("[Scheduler] Started BackgroundScheduler")
        
        with app.app_context():
            load_all_schedules(app)
            
        return scheduler
    except Exception as e:
        app.logger.error(f"[Scheduler] Failed to initialize scheduler: {e}", exc_info=True)
        return None
