# call_analyzer/stocrm_sync_manager.py
"""
Менеджер периодической синхронизации записей звонков из StoCRM.

Схема работы:
  1. GET /api/external/v1/calls/get_filtered — список звонков с записью (HAS_RECORD=Y)
  2. Клиентская фильтрация по дате (TIMESTAMP >= cutoff)
  3. Для каждого нового звонка: GET /api/external/v1/call/get_record — аудио (бинарный MP3 или URL)
  4. Сохранение файла в папку пользователя
  5. Watchdog call_analyzer подхватывает файл для анализа
"""

import logging
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

_sync_threads: dict = {}
_sync_lock = threading.Lock()


def _extract_extension_from_call(call: dict, dcontext: str) -> Optional[str]:
    """
    Пытается извлечь номер рабочей станции (200, 201) из CALL_SRC/CALL_DST.
    Для входящего: CALL_DST может быть внутренним номером оператора.
    Для исходящего: CALL_SRC может быть внутренним номером оператора.
    """
    src = str(call.get("CALL_SRC") or "").strip()
    dst = str(call.get("CALL_DST") or "").strip()
    for candidate in (dst, src) if dcontext == "IN" else (src, dst):
        digits = re.sub(r"\D", "", candidate)
        if 2 <= len(digits) <= 5 and digits.isdigit():
            return candidate
    return None


def _sanitize_error(err: str) -> str:
    """Очищает строку ошибки для сохранения в БД (PostgreSQL не допускает NUL)."""
    s = (str(err) or "")[:500]
    return s.replace("\x00", "").replace("\r", "").replace("\n", " ").strip()


def _process_stocrm_recording(
    engine,
    conn_id: int,
    user_id: int,
    call_uuid: str,
    phone: str,
    workstation_id,
    dcontext: str,
    timestamp_unix: int,
):
    """
    Скачивает одну запись звонка из StoCRM и сохраняет в папку пользователя.
    Если файл уже существует — пропускает.
    """
    from call_analyzer.stocrm_connector import get_record_and_save, make_stocrm_filename
    from config.settings import get_config

    try:
        with engine.connect() as c:
            conn_row = c.execute(
                text("SELECT domain, sid FROM stocrm_connections WHERE id = :cid"),
                {"cid": conn_id},
            ).fetchone()
            r = c.execute(
                text("SELECT base_records_path FROM user_config WHERE user_id = :uid"),
                {"uid": user_id},
            ).fetchone()

        if not conn_row:
            logger.error(f"StoCRM conn {conn_id} не найдено")
            return

        base_path_str = (r.base_records_path or "").strip() if r else ""
        if not base_path_str:
            default_base = getattr(get_config(), "BASE_RECORDS_PATH", "/var/calls")
            base_path_str = str(Path(default_base) / "users" / str(user_id))

        base_path = Path(base_path_str)
        filename = make_stocrm_filename(phone, workstation_id, dcontext, timestamp_unix, call_uuid)

        try:
            dt = datetime.utcfromtimestamp(int(timestamp_unix))
        except Exception:
            dt = datetime.utcnow()

        target_dir = base_path / str(dt.year) / f"{dt.month:02d}" / f"{dt.day:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        save_path = target_dir / filename

        if save_path.exists() and save_path.stat().st_size > 0:
            logger.debug(f"StoCRM: файл уже существует, пропуск: {save_path}")
            return

        logger.info(f"StoCRM: запрашиваем запись UUID={call_uuid[:30]}, путь={save_path}")

        ok, err = get_record_and_save(
            conn_row.domain, conn_row.sid, call_uuid,
            save_path, timeout=60, retries=3, retry_delay=15,
        )
        if not ok:
            err_msg = f"get_record: {err}" if err else "Неизвестная ошибка"
            logger.error(f"StoCRM get_record failed UUID={call_uuid}: {err_msg}")
            with engine.connect() as uc:
                uc.execute(
                    text("UPDATE stocrm_connections SET last_error = :e WHERE id = :cid"),
                    {"e": _sanitize_error(err_msg), "cid": conn_id},
                )
                uc.commit()
            return

        logger.info(f"StoCRM: запись сохранена {save_path} ({save_path.stat().st_size} байт)")
        with engine.connect() as uc:
            uc.execute(
                text("UPDATE stocrm_connections SET last_error = NULL WHERE id = :cid"),
                {"cid": conn_id},
            )
            uc.commit()

    except Exception as e:
        logger.error(f"StoCRM _process_stocrm_recording UUID={call_uuid}: {e}", exc_info=True)
        try:
            with engine.connect() as uc:
                uc.execute(
                    text("UPDATE stocrm_connections SET last_error = :e WHERE id = :cid"),
                    {"e": _sanitize_error(str(e)), "cid": conn_id},
                )
                uc.commit()
        except Exception:
            pass


def sync_stocrm_connection(connection_id: int, user_id: Optional[int] = None):
    """
    Синхронизирует записи звонков для одного подключения StoCRM.
    Запрашивает список звонков → фильтрует по дате и направлению →
    для каждого нового звонка скачивает аудио.
    """
    from config.settings import get_config
    from sqlalchemy import create_engine, text

    logger.info(f"StoCRM: начало синхронизации подключения {connection_id}")
    engine = None
    try:
        cfg = get_config()
        engine = create_engine(cfg.SQLALCHEMY_DATABASE_URI)

        with engine.connect() as c:
            row = c.execute(
                text("""
                    SELECT id, user_id, domain, sid, is_active,
                           allowed_directions, start_from, sync_interval_minutes
                    FROM stocrm_connections WHERE id = :cid
                """),
                {"cid": connection_id},
            ).fetchone()

        if not row or not row.is_active:
            return

        uid = user_id or row.user_id

        # Окно синхронизации: от start_from (или 7 дней назад) до сейчас
        now_dt = datetime.utcnow()
        if row.start_from:
            cutoff_dt = row.start_from.replace(tzinfo=None) if hasattr(row.start_from, 'tzinfo') else row.start_from
        else:
            cutoff_dt = now_dt - timedelta(days=7)

        cutoff_ts = int(cutoff_dt.timestamp())

        allowed = list(row.allowed_directions) if row.allowed_directions else None
        logger.info(f"StoCRM sync {connection_id}: окно={cutoff_dt} — {now_dt}, направления={allowed}")

        from call_analyzer.stocrm_connector import fetch_call_list

        success, message, calls = fetch_call_list(
            domain=row.domain,
            sid=row.sid,
            cutoff_timestamp=cutoff_ts,
            allowed_directions=allowed,
            timeout=30,
        )

        logger.info(f"StoCRM sync {connection_id}: success={success}, msg={message}, calls={len(calls) if calls else 0}")

        with engine.connect() as uc:
            uc.execute(
                text("UPDATE stocrm_connections SET last_sync = :now, last_error = :err WHERE id = :cid"),
                {"now": datetime.utcnow(), "err": None if success else message, "cid": connection_id},
            )
            uc.commit()

        if success and calls:
            for call in calls:
                call_uuid = str(call.get("CALL_UUID") or "").strip()
                if not call_uuid:
                    continue
                phone = str(call.get("PHONE_NUMBER") or call.get("CALL_SRC") or "").strip()
                dcontext = str(call.get("CALL_DCONTEXT") or "IN").strip().upper()
                # Номер рабочей станции (200, 201) приоритетнее WORKSTATION_ID (3, 5)
                workstation_id = (
                    call.get("WORKSTATION_NUMBER")
                    or call.get("EXTENSION")
                    or call.get("WORKSTATION_EXTENSION")
                    or call.get("INNER_NUMBER")
                    or call.get("STATION_NUMBER")
                    or _extract_extension_from_call(call, dcontext)
                    or call.get("WORKSTATION_ID")
                    or "0"
                )
                ts_val = call.get("TIMESTAMP") or call.get("TIMESTAMP_FRONTEND_TIMESTAMP") or 0
                try:
                    timestamp_unix = int(ts_val)
                except (TypeError, ValueError):
                    timestamp_unix = int(now_dt.timestamp())

                _process_stocrm_recording(
                    engine, connection_id, uid,
                    call_uuid, phone, workstation_id, dcontext, timestamp_unix,
                )

    except Exception as e:
        logger.error(f"StoCRM sync {connection_id}: {e}", exc_info=True)
        try:
            if engine:
                with engine.connect() as uc:
                    uc.execute(
                        text("UPDATE stocrm_connections SET last_sync = :now, last_error = :err WHERE id = :cid"),
                        {"now": datetime.utcnow(), "err": str(e)[:500], "cid": connection_id},
                    )
                    uc.commit()
        except Exception:
            pass
    finally:
        if engine:
            engine.dispose()


def _sync_worker(user_id: int, connection_id: int, sync_interval_minutes: int):
    """Фоновый поток: периодически вызывает sync_stocrm_connection."""
    interval_sec = max(60, sync_interval_minutes * 60)
    logger.info(f"StoCRM sync worker: conn={connection_id}, user={user_id}, интервал={sync_interval_minutes} мин")
    consecutive_errors = 0
    max_consecutive_errors = 5

    while True:
        key = (user_id, connection_id)
        with _sync_lock:
            if key not in _sync_threads:
                break
        try:
            from config.settings import get_config
            from sqlalchemy import create_engine, text as sa_text

            cfg = get_config()
            engine = create_engine(cfg.SQLALCHEMY_DATABASE_URI)
            with engine.connect() as c:
                r = c.execute(
                    sa_text("SELECT id, is_active, sync_interval_minutes FROM stocrm_connections WHERE id = :cid"),
                    {"cid": connection_id},
                ).fetchone()
            engine.dispose()

            if not r or not r.is_active or (r.sync_interval_minutes or 0) <= 0:
                logger.info(f"StoCRM {connection_id}: неактивно или интервал 0, остановка")
                break

            sync_stocrm_connection(connection_id, user_id=user_id)
            consecutive_errors = 0
            time.sleep(interval_sec)

        except KeyboardInterrupt:
            break
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"StoCRM sync worker {connection_id} ошибка #{consecutive_errors}: {e}", exc_info=True)
            if consecutive_errors >= max_consecutive_errors:
                logger.error(f"StoCRM sync worker {connection_id}: превышен лимит ошибок, остановка")
                break
            time.sleep(min(60 * (2 ** (consecutive_errors - 1)), 600))

    with _sync_lock:
        _sync_threads.pop((user_id, connection_id), None)


def start_stocrm_sync(connection_id: int, user_id: Optional[int] = None):
    """Запускает фоновый поток синхронизации для указанного подключения (если ещё не запущен)."""
    from config.settings import get_config
    from sqlalchemy import create_engine, text

    with _sync_lock:
        try:
            cfg = get_config()
            engine = create_engine(cfg.SQLALCHEMY_DATABASE_URI)
            with engine.connect() as c:
                r = c.execute(
                    text("SELECT id, user_id, is_active, sync_interval_minutes FROM stocrm_connections WHERE id = :cid"),
                    {"cid": connection_id},
                ).fetchone()
            engine.dispose()

            if not r:
                return
            uid = user_id or r.user_id
            if not r.is_active or (r.sync_interval_minutes or 0) <= 0:
                return

            key = (uid, connection_id)
            if key in _sync_threads and _sync_threads[key].is_alive():
                return

            interval = r.sync_interval_minutes or 60
            t = threading.Thread(
                target=_sync_worker,
                args=(uid, connection_id, interval),
                daemon=True,
                name=f"StocrmSync-{uid}-{connection_id}",
            )
            t.start()
            _sync_threads[key] = t
            logger.info(f"StoCRM: запущен поток синхронизации conn={connection_id} user={uid}")
        except Exception as e:
            logger.error(f"StoCRM start_stocrm_sync {connection_id}: {e}", exc_info=True)


def stop_stocrm_sync(connection_id: int, user_id: Optional[int] = None):
    """Останавливает поток синхронизации (фактически удаляет из словаря, поток завершится сам)."""
    with _sync_lock:
        if user_id is None:
            keys = [k for k in _sync_threads if k[1] == connection_id]
        else:
            keys = [(user_id, connection_id)] if (user_id, connection_id) in _sync_threads else []
        for k in keys:
            _sync_threads.pop(k, None)
            logger.info(f"StoCRM: остановлен sync conn={connection_id}")


def start_all_active_stocrm_syncs(user_id: Optional[int] = None):
    """Запускает синхронизацию для всех активных подключений StoCRM (is_active=True, interval>0)."""
    from config.settings import get_config
    from sqlalchemy import create_engine, text

    engine = None
    try:
        cfg = get_config()
        engine = create_engine(cfg.SQLALCHEMY_DATABASE_URI)
        params: dict = {}
        uf = ""
        if user_id is not None:
            params["uid"] = user_id
            uf = " AND s.user_id = :uid"
        sql = text(f"""
            SELECT s.id AS conn_id, s.user_id
            FROM stocrm_connections s
            JOIN users u ON u.id = s.user_id AND u.is_active = TRUE
            WHERE s.is_active = TRUE
              AND s.sync_interval_minutes > 0{uf}
        """)
        with engine.connect() as c:
            rows = c.execute(sql, params or {}).fetchall()

        seen = set()
        for row in rows:
            if not row.conn_id or (row.user_id, row.conn_id) in seen:
                continue
            seen.add((row.user_id, row.conn_id))
            try:
                start_stocrm_sync(row.conn_id, user_id=row.user_id)
                logger.info(f"StoCRM: автозапуск sync conn={row.conn_id} user={row.user_id}")
            except Exception as e:
                logger.error(f"StoCRM start_all: ошибка conn={row.conn_id}: {e}")
    except Exception as e:
        logger.error(f"StoCRM start_all_active_stocrm_syncs: {e}", exc_info=True)
    finally:
        if engine:
            engine.dispose()
