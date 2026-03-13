# call_analyzer/rostelecom_sync_manager.py
"""
Менеджер периодической синхронизации записей звонков из облачной АТС Ростелеком.
Работает БЕЗ webhook — запросы domain_call_history, download_call_history, get_record
выполняются напрямую из системы. Подходит, когда «Адрес внешней системы» занят CRM.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

_sync_threads = {}
_sync_lock = threading.Lock()


def _process_rostelecom_recording(
    engine,
    conn_id: int,
    user_id: int,
    session_id: str,
    from_number: str,
    request_number: str,
    request_pin: str,
    call_type: str,
    timestamp_str: str,
):
    """Обрабатывает одну запись: get_record -> download -> сохранение."""
    from call_analyzer.rostelecom_connector import get_record, download_recording, make_rostelecom_filename
    from config.settings import get_config
    from sqlalchemy import text

    try:
        with engine.connect() as c:
            conn_row = c.execute(
                text("SELECT api_url, client_id, sign_key FROM rostelecom_ats_connections WHERE id = :cid"),
                {"cid": conn_id},
            ).fetchone()
            r = c.execute(
                text("SELECT base_records_path FROM user_config WHERE user_id = :uid"),
                {"uid": user_id},
            ).fetchone()
        base_path_str = (r.base_records_path or "").strip() if r else ""
        if not conn_row:
            logger.error("Rostelecom conn not found")
            return
        if not base_path_str:
            default_base = getattr(get_config(), "BASE_RECORDS_PATH", "/var/calls")
            base_path_str = str(Path(default_base) / "users" / str(user_id))
        base_path = Path(base_path_str)
        ts = timestamp_str or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")
        ts_clean = ts.replace("-", "").replace(" ", "-").replace(":", "")[:15]
        filename = make_rostelecom_filename(
            session_id, from_number or "", request_number or "", request_pin,
            call_type or "incoming", ts_clean
        )
        try:
            dt = datetime.strptime(ts[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        except Exception:
            dt = datetime.utcnow()
        target_dir = base_path / str(dt.year) / f"{dt.month:02d}" / f"{dt.day:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        save_path = target_dir / filename
        logger.info(f"Rostelecom: получаем запись session_id={session_id[:20]}..., путь={save_path}")
        url, err = get_record(
            conn_row.api_url, conn_row.client_id, conn_row.sign_key, session_id,
            timeout=60, retries=5, retry_delay=30
        )
        if err or not url:
            logger.error(f"Rostelecom get_record failed: {err}")
            with engine.connect() as uc:
                uc.execute(
                    text("UPDATE rostelecom_ats_connections SET last_error = :e, last_sync = :now WHERE id = :cid"),
                    {"e": err, "now": datetime.utcnow(), "cid": conn_id},
                )
                uc.commit()
            return
        if not download_recording(url, save_path, timeout=120):
            err_msg = "Rostelecom: ошибка скачивания записи"
            logger.error(err_msg)
            with engine.connect() as uc:
                uc.execute(
                    text("UPDATE rostelecom_ats_connections SET last_error = :e, last_sync = :now WHERE id = :cid"),
                    {"e": err_msg, "now": datetime.utcnow(), "cid": conn_id},
                )
                uc.commit()
            return
        logger.info(f"Rostelecom запись сохранена: {save_path}")
        with engine.connect() as uc:
            uc.execute(
                text("UPDATE rostelecom_ats_connections SET last_error = NULL, last_sync = :now WHERE id = :cid"),
                {"now": datetime.utcnow(), "cid": conn_id},
            )
            uc.commit()
    except Exception as e:
        logger.error(f"Rostelecom _process_rostelecom_recording: {e}", exc_info=True)
        try:
            with engine.connect() as uc:
                uc.execute(
                    text("UPDATE rostelecom_ats_connections SET last_error = :e, last_sync = :now WHERE id = :cid"),
                    {"e": str(e), "now": datetime.utcnow(), "cid": conn_id},
                )
                uc.commit()
        except Exception:
            pass


def sync_rostelecom_connection(connection_id: int, user_id: Optional[int] = None):
    """Синхронизация истории звонков Ростелеком (domain_call_history + download + get_record)."""
    from config.settings import get_config
    from sqlalchemy import create_engine, text

    logger.info(f"Начало синхронизации Ростелеком подключения {connection_id}")
    engine = None
    try:
        config = get_config()
        engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
        with engine.connect() as c:
            row = c.execute(
                text("""
                    SELECT id, user_id, api_url, client_id, sign_key, is_active,
                           allowed_directions, start_from, sync_interval_minutes
                    FROM rostelecom_ats_connections WHERE id = :cid
                """),
                {"cid": connection_id},
            ).fetchone()
        if not row:
            return
        if not row.is_active:
            return
        uid = user_id or row.user_id
        date_to = datetime.utcnow()
        date_from = row.start_from or (date_to - timedelta(days=7))
        if date_from.tzinfo:
            date_from = date_from.replace(tzinfo=None)
        logger.info(f"Rostelecom sync {connection_id}: выгрузка за {date_from} — {date_to}")
        from call_analyzer.rostelecom_connector import fetch_call_history
        success, message, calls = fetch_call_history(
            row.api_url, row.client_id, row.sign_key, date_from, date_to, timeout=60
        )
        logger.info(f"Rostelecom sync {connection_id}: success={success}, msg={message}, calls={len(calls) if calls else 0}")
        with engine.connect() as uc:
            uc.execute(
                text("UPDATE rostelecom_ats_connections SET last_sync = :now, last_error = :err WHERE id = :cid"),
                {"now": datetime.utcnow(), "err": None if success else message, "cid": connection_id}
            )
            uc.commit()
        if success and calls:
            allowed = row.allowed_directions
            for c in calls:
                sid = c.get("session_id") or c.get("sessionId")
                is_rec = (c.get("is_record") or c.get("isRecord") or "").lower() == "true"
                call_type = c.get("type") or c.get("call_type") or "incoming"
                if allowed and call_type not in allowed:
                    continue
                if sid and is_rec:
                    _process_rostelecom_recording(
                        engine, connection_id, uid, sid,
                        c.get("from_number") or c.get("fromNumber", ""),
                        c.get("request_number") or c.get("requestNumber", ""),
                        c.get("request_pin") or c.get("requestPin", ""),
                        call_type,
                        c.get("timestamp") or c.get("start_time", ""),
                    )
    except Exception as e:
        logger.error(f"Rostelecom sync {connection_id}: {e}", exc_info=True)
        try:
            with engine.connect() as uc:
                uc.execute(
                    text("UPDATE rostelecom_ats_connections SET last_sync = :now, last_error = :err WHERE id = :cid"),
                    {"now": datetime.utcnow(), "err": str(e), "cid": connection_id}
                )
                uc.commit()
        except Exception:
            pass
    finally:
        if engine:
            engine.dispose()


def _sync_worker(user_id: int, connection_id: int, sync_interval_minutes: int):
    interval_sec = max(60, sync_interval_minutes * 60)
    logger.info(f"Rostelecom sync worker: conn={connection_id}, user={user_id}, интервал={sync_interval_minutes} мин")
    consecutive_errors = 0
    max_consecutive_errors = 5

    while True:
        key = (user_id, connection_id)
        with _sync_lock:
            if key not in _sync_threads:
                break
        try:
            from config.settings import get_config
            from sqlalchemy import create_engine, text
            config = get_config()
            engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
            with engine.connect() as c:
                r = c.execute(
                    text("SELECT id, is_active, sync_interval_minutes FROM rostelecom_ats_connections WHERE id = :cid"),
                    {"cid": connection_id},
                ).fetchone()
            engine.dispose()
            if not r or not r.is_active or (r.sync_interval_minutes or 0) <= 0:
                logger.info(f"Rostelecom {connection_id} неактивен или интервал 0, остановка")
                break
            sync_rostelecom_connection(connection_id, user_id=user_id)
            consecutive_errors = 0
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            break
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Rostelecom sync worker {connection_id} ошибка #{consecutive_errors}: {e}", exc_info=True)
            if consecutive_errors >= max_consecutive_errors:
                break
            time.sleep(min(60 * (2 ** (consecutive_errors - 1)), 600))


def start_rostelecom_sync(connection_id: int, user_id: Optional[int] = None):
    from config.settings import get_config
    from sqlalchemy import create_engine

    with _sync_lock:
        key = (user_id, connection_id) if user_id else None
        if key and key in _sync_threads:
            return
        engine = None
        try:
            config = get_config()
            engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
            with engine.connect() as c:
                r = c.execute(
                    text("""
                        SELECT id, user_id, is_active, sync_interval_minutes
                        FROM rostelecom_ats_connections WHERE id = :cid
                    """),
                    {"cid": connection_id},
                ).fetchone()
            if not r:
                return
            uid = user_id or r.user_id
            if not r.is_active or (r.sync_interval_minutes or 0) <= 0:
                return
            key = (uid, connection_id)
            if key in _sync_threads:
                return
            engine.dispose()
            engine = None
            sync_interval = r.sync_interval_minutes or 60
            t = threading.Thread(
                target=_sync_worker,
                args=(uid, connection_id, sync_interval),
                daemon=True,
                name=f"RostelecomSync-{uid}-{connection_id}",
            )
            t.start()
            _sync_threads[key] = t
            logger.info(f"Запущен Rostelecom sync для подключения {connection_id}")
        finally:
            if engine:
                engine.dispose()


def stop_rostelecom_sync(connection_id: int, user_id: Optional[int] = None):
    with _sync_lock:
        if user_id is None:
            keys = [k for k in _sync_threads if k[1] == connection_id]
        else:
            keys = [(user_id, connection_id)] if (user_id, connection_id) in _sync_threads else []
        for k in keys:
            _sync_threads.pop(k, None)
            logger.info(f"Остановлен Rostelecom sync подключения {connection_id}")


def start_all_active_rostelecom_syncs(user_id: Optional[int] = None):
    """Запускает синхронизацию для всех активных подключений с source_type=rostelecom."""
    from config.settings import get_config
    from sqlalchemy import create_engine, text

    engine = None
    try:
        config = get_config()
        engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
        params = {}
        uf = ""
        if user_id is not None:
            params["uid"] = user_id
            uf = " AND uc.user_id = :uid"
        sql = text(f"""
            SELECT uc.user_id, uc.rostelecom_ats_connection_id as conn_id
            FROM user_config uc
            JOIN users u ON u.id = uc.user_id AND u.is_active = TRUE
            JOIN rostelecom_ats_connections r ON r.id = uc.rostelecom_ats_connection_id
                AND r.user_id = uc.user_id AND r.is_active = TRUE
                AND (r.sync_interval_minutes IS NULL OR r.sync_interval_minutes > 0)
            WHERE uc.source_type = 'rostelecom'{uf}
        """)
        with engine.connect() as c:
            rows = c.execute(sql, params or {}).fetchall()
        seen = set()
        for row in rows:
            if not row.conn_id or (row.user_id, row.conn_id) in seen:
                continue
            seen.add((row.user_id, row.conn_id))
            try:
                start_rostelecom_sync(row.conn_id, user_id=row.user_id)
            except Exception as e:
                logger.error(f"Ошибка запуска Rostelecom sync {row.conn_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка запуска Rostelecom sync: {e}", exc_info=True)
    finally:
        if engine:
            engine.dispose()
