# -*- coding: utf-8 -*-
"""
Периодическая синхронизация записей из произвольного REST API (Кастомный API).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

_sync_threads: dict = {}
_sync_lock = threading.Lock()


def _sanitize_error(err: str) -> str:
    s = (str(err) or '')[:500]
    return s.replace('\x00', '').replace('\r', '').replace('\n', ' ').strip()


def _should_skip_existing(engine, connection_id: int, external_key: str, save_path: Path) -> bool:
    with engine.connect() as c:
        r = c.execute(
            text(
                """
                SELECT status, saved_path FROM custom_api_imported_calls
                WHERE connection_id = :cid AND external_key = :ek
                """
            ),
            {'cid': connection_id, 'ek': external_key},
        ).fetchone()
    if not r:
        return False
    if r.status == 'ok' and r.saved_path:
        p = Path(str(r.saved_path))
        try:
            if p.exists() and p.stat().st_size > 0:
                return True
        except OSError:
            pass
    return False


def _record_import_success(
    engine,
    connection_id: int,
    user_id: int,
    external_key: str,
    record_url: str,
    save_path: Path,
    raw_item: Dict[str, Any],
) -> None:
    raw_json = json.dumps(raw_item, ensure_ascii=False, default=str)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO custom_api_imported_calls
                (connection_id, user_id, external_key, record_url, saved_path, raw_payload, status, error_message, downloaded_at)
                VALUES (:cid, :uid, :ek, :url, :path, CAST(:raw AS jsonb), 'ok', NULL, :dt)
                ON CONFLICT (connection_id, external_key) DO UPDATE SET
                    record_url = EXCLUDED.record_url,
                    saved_path = EXCLUDED.saved_path,
                    raw_payload = EXCLUDED.raw_payload,
                    status = 'ok',
                    error_message = NULL,
                    downloaded_at = EXCLUDED.downloaded_at
                """
            ),
            {
                'cid': connection_id,
                'uid': user_id,
                'ek': external_key,
                'url': record_url,
                'path': str(save_path),
                'raw': raw_json,
                'dt': datetime.utcnow(),
            },
        )


def _record_import_error(
    engine,
    connection_id: int,
    user_id: int,
    external_key: str,
    record_url: str,
    err: str,
    raw_item: Optional[Dict[str, Any]],
) -> None:
    raw_json = json.dumps(raw_item or {}, ensure_ascii=False, default=str)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO custom_api_imported_calls
                (connection_id, user_id, external_key, record_url, saved_path, raw_payload, status, error_message, downloaded_at)
                VALUES (:cid, :uid, :ek, :url, NULL, CAST(:raw AS jsonb), 'error', :err, :dt)
                ON CONFLICT (connection_id, external_key) DO UPDATE SET
                    record_url = EXCLUDED.record_url,
                    status = 'error',
                    error_message = EXCLUDED.error_message,
                    downloaded_at = EXCLUDED.downloaded_at
                """
            ),
            {
                'cid': connection_id,
                'uid': user_id,
                'ek': external_key,
                'url': record_url,
                'raw': raw_json,
                'err': _sanitize_error(err),
                'dt': datetime.utcnow(),
            },
        )


def _process_one_item(
    engine,
    connection_id: int,
    user_id: int,
    item: Dict[str, Any],
    base_path: Path,
    verify_ssl: bool,
) -> None:
    from call_analyzer.custom_api_connector import build_custom_api_filename, download_recording

    external_key = str(item.get('external_id') or '').strip()
    if not external_key:
        return
    record_url = str(item.get('record_url') or '').strip()
    station = str(item.get('station_code') or '').strip()
    orig = str(item.get('original_filename') or '').strip()
    raw = item.get('raw') if isinstance(item.get('raw'), dict) else {}
    call_dt = item.get('call_datetime')

    filename = build_custom_api_filename(orig, station)
    if isinstance(call_dt, datetime):
        dt = call_dt
    else:
        dt = datetime.utcnow()
    target_dir = base_path / str(dt.year) / f'{dt.month:02d}' / f'{dt.day:02d}'
    target_dir.mkdir(parents=True, exist_ok=True)
    save_path = target_dir / filename

    if _should_skip_existing(engine, connection_id, external_key, save_path):
        logger.debug('Custom API: пропуск (уже есть): %s', save_path)
        return

    if save_path.exists() and save_path.stat().st_size > 0:
        _record_import_success(engine, connection_id, user_id, external_key, record_url, save_path, raw)
        return

    ok = download_recording(record_url, save_path, timeout=120, verify_ssl=verify_ssl)
    if not ok:
        _record_import_error(engine, connection_id, user_id, external_key, record_url, 'Ошибка скачивания', raw)
        return

    _record_import_success(engine, connection_id, user_id, external_key, record_url, save_path, raw)
    logger.info('Custom API: сохранено %s', save_path)


def sync_custom_api_connection(connection_id: int, user_id: Optional[int] = None):
    """Один цикл синхронизации для подключения Кастомный API."""
    from config.settings import get_config
    from sqlalchemy import create_engine

    from call_analyzer.custom_api_provider import fetch_custom_api_records, merge_mapping_config, merge_request_config

    logger.info('Custom API: начало синхронизации подключения %s', connection_id)
    engine = None
    try:
        cfg = get_config()
        engine = create_engine(cfg.SQLALCHEMY_DATABASE_URI)

        with engine.connect() as c:
            row = c.execute(
                text(
                    """
                    SELECT id, user_id, is_active, request_config, mapping_config, start_from
                    FROM custom_api_connections WHERE id = :cid
                    """
                ),
                {'cid': connection_id},
            ).fetchone()

        if not row or not row.is_active:
            return

        uid = user_id or row.user_id
        req_cfg = merge_request_config(row.request_config if row.request_config else {})
        map_cfg = merge_mapping_config(row.mapping_config if row.mapping_config else {})
        start_from = row.start_from

        with engine.connect() as c:
            r = c.execute(
                text('SELECT base_records_path FROM user_config WHERE user_id = :uid'),
                {'uid': uid},
            ).fetchone()

        base_path_str = (r.base_records_path or '').strip() if r else ''
        if not base_path_str:
            default_base = getattr(cfg, 'BASE_RECORDS_PATH', '/var/calls')
            base_path_str = str(Path(str(default_base)) / 'users' / str(uid))
        base_path = Path(base_path_str)

        rows, err = fetch_custom_api_records(req_cfg, map_cfg)

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE custom_api_connections
                    SET last_sync = :now, last_error = :err
                    WHERE id = :cid
                    """
                ),
                {
                    'now': datetime.utcnow(),
                    'err': None if not err else _sanitize_error(err),
                    'cid': connection_id,
                },
            )

        if err:
            logger.error('Custom API sync %s: %s', connection_id, err)
            return

        verify_ssl = bool(req_cfg.get('verify_ssl', True))

        for item in rows:
            try:
                call_dt = item.get('call_datetime')
                if start_from and isinstance(call_dt, datetime):
                    sf = start_from.replace(tzinfo=None) if hasattr(start_from, 'tzinfo') and start_from.tzinfo else start_from
                    if call_dt < sf:
                        continue
                _process_one_item(engine, connection_id, uid, item, base_path, verify_ssl)
            except Exception as ex:
                logger.error('Custom API item error: %s', ex, exc_info=True)

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE custom_api_connections SET last_sync = :now, last_error = NULL WHERE id = :cid
                    """
                ),
                {'now': datetime.utcnow(), 'cid': connection_id},
            )

    except Exception as e:
        logger.error('Custom API sync %s: %s', connection_id, e, exc_info=True)
        try:
            if engine:
                with engine.begin() as conn:
                    conn.execute(
                        text('UPDATE custom_api_connections SET last_error = :e, last_sync = :now WHERE id = :cid'),
                        {'e': _sanitize_error(str(e)), 'now': datetime.utcnow(), 'cid': connection_id},
                    )
        except Exception:
            pass
    finally:
        if engine:
            engine.dispose()


def _sync_worker(user_id: int, connection_id: int, sync_interval_minutes: int):
    interval_sec = max(60, sync_interval_minutes * 60)
    logger.info(
        'Custom API sync worker: conn=%s, user=%s, интервал=%s мин',
        connection_id, user_id, sync_interval_minutes,
    )
    consecutive_errors = 0
    max_consecutive_errors = 5

    while True:
        key = (user_id, connection_id)
        with _sync_lock:
            if key not in _sync_threads:
                break
        try:
            from config.settings import get_config
            from sqlalchemy import create_engine

            cfg = get_config()
            eng = create_engine(cfg.SQLALCHEMY_DATABASE_URI)
            with eng.connect() as c:
                r = c.execute(
                    text(
                        """
                        SELECT id, is_active, sync_interval_minutes
                        FROM custom_api_connections WHERE id = :cid
                        """
                    ),
                    {'cid': connection_id},
                ).fetchone()
            eng.dispose()

            if not r or not r.is_active or (r.sync_interval_minutes or 0) <= 0:
                logger.info('Custom API %s неактивен или интервал 0, остановка', connection_id)
                break

            sync_custom_api_connection(connection_id, user_id=user_id)
            consecutive_errors = 0
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            break
        except Exception as e:
            consecutive_errors += 1
            logger.error('Custom API sync worker %s ошибка #%s: %s', connection_id, consecutive_errors, e, exc_info=True)
            if consecutive_errors >= max_consecutive_errors:
                break
            time.sleep(min(60 * (2 ** (consecutive_errors - 1)), 600))

    with _sync_lock:
        _sync_threads.pop((user_id, connection_id), None)


def start_custom_api_sync(connection_id: int, user_id: Optional[int] = None):
    from config.settings import get_config
    from sqlalchemy import create_engine

    with _sync_lock:
        try:
            cfg = get_config()
            engine = create_engine(cfg.SQLALCHEMY_DATABASE_URI)
            with engine.connect() as c:
                r = c.execute(
                    text(
                        """
                        SELECT id, user_id, is_active, sync_interval_minutes
                        FROM custom_api_connections WHERE id = :cid
                        """
                    ),
                    {'cid': connection_id},
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

            sync_interval = r.sync_interval_minutes or 60
            t = threading.Thread(
                target=_sync_worker,
                args=(uid, connection_id, sync_interval),
                daemon=True,
                name=f'CustomApiSync-{uid}-{connection_id}',
            )
            t.start()
            _sync_threads[key] = t
            logger.info('Custom API: запущен поток sync conn=%s user=%s', connection_id, uid)
        except Exception as e:
            logger.error('Custom API start_custom_api_sync %s: %s', connection_id, e, exc_info=True)


def stop_custom_api_sync(connection_id: int, user_id: Optional[int] = None):
    with _sync_lock:
        if user_id is None:
            keys = [k for k in _sync_threads if k[1] == connection_id]
        else:
            keys = [(user_id, connection_id)] if (user_id, connection_id) in _sync_threads else []
        for k in keys:
            _sync_threads.pop(k, None)
            logger.info('Custom API: остановлен sync conn=%s', connection_id)


def start_all_active_custom_api_syncs(user_id: Optional[int] = None):
    from config.settings import get_config
    from sqlalchemy import create_engine

    engine = None
    try:
        cfg = get_config()
        engine = create_engine(cfg.SQLALCHEMY_DATABASE_URI)
        params: dict = {}
        uf = ''
        if user_id is not None:
            params['uid'] = user_id
            uf = ' AND c.user_id = :uid'
        sql = text(
            f"""
            SELECT c.id AS conn_id, c.user_id
            FROM custom_api_connections c
            JOIN users u ON u.id = c.user_id AND u.is_active = TRUE
            WHERE c.is_active = TRUE
              AND c.sync_interval_minutes > 0{uf}
            """
        )
        with engine.connect() as c:
            rows = c.execute(sql, params or {}).fetchall()

        seen = set()
        for row in rows:
            if not row.conn_id or (row.user_id, row.conn_id) in seen:
                continue
            seen.add((row.user_id, row.conn_id))
            try:
                start_custom_api_sync(row.conn_id, user_id=row.user_id)
                logger.info('Custom API: автозапуск sync conn=%s user=%s', row.conn_id, row.user_id)
            except Exception as e:
                logger.error('Custom API start_all: ошибка conn=%s: %s', row.conn_id, e)
    except Exception as e:
        logger.error('Custom API start_all_active_custom_api_syncs: %s', e, exc_info=True)
    finally:
        if engine:
            engine.dispose()
