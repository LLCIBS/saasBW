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
                elif report_type == 'skolko_52':
                    from reports.skolko_52 import run_skolko_52
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
                    elif report_type == 'skolko_52':
                        date_from = datetime.combine(start_date, dt_time.min) if start_date else None
                        date_to = datetime.combine(end_date, dt_time.max) if end_date else None
                        try:
                            run_skolko_52(date_from=date_from, date_to=date_to)
                        except TypeError:
                            run_skolko_52()
                        logger.info(f"[Scheduler] skolko_52 completed")
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

    # Удаляем старую задачу, если была
    try:
        sched.remove_job(job_id)
    except Exception:
        pass

    if not schedule.enabled:
        logger.info(f"[Scheduler] Schedule {job_id} is disabled, skipping")
        return

    trigger = None
    
    try:
        if schedule.schedule_type == 'daily' and schedule.daily_time:
            hour, minute = map(int, schedule.daily_time.split(':'))
            trigger = CronTrigger(hour=hour, minute=minute)
            logger.info(f"[Scheduler] Added daily schedule {job_id} at {schedule.daily_time}")
            
        elif schedule.schedule_type == 'interval' and schedule.interval_value and schedule.interval_unit:
            if schedule.interval_unit == 'days':
                trigger = IntervalTrigger(days=schedule.interval_value)
            elif schedule.interval_unit == 'hours':
                trigger = IntervalTrigger(hours=schedule.interval_value)
            else:
                logger.warning(f"[Scheduler] Unknown interval unit: {schedule.interval_unit}")
                return
            logger.info(f"[Scheduler] Added interval schedule {job_id}: every {schedule.interval_value} {schedule.interval_unit}")
            
        elif schedule.schedule_type == 'weekly' and schedule.weekly_time is not None:
            hour, minute = map(int, schedule.weekly_time.split(':'))
            # 0=понедельник ... 6=воскресенье
            day_of_week = schedule.weekly_day if schedule.weekly_day is not None else 0
            trigger = CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute)
            logger.info(f"[Scheduler] Added weekly schedule {job_id}: day={day_of_week}, time={schedule.weekly_time}")
            
        elif schedule.schedule_type == 'custom' and schedule.cron_expression:
            try:
                trigger = CronTrigger.from_crontab(schedule.cron_expression)
                logger.info(f"[Scheduler] Added custom schedule {job_id}: {schedule.cron_expression}")
            except Exception as e:
                logger.error(f"[Scheduler] Invalid cron expression '{schedule.cron_expression}': {e}")
                return
        else:
            logger.warning(f"[Scheduler] Invalid schedule config: {schedule}")
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
