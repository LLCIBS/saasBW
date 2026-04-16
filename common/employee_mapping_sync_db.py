# -*- coding: utf-8 -*-
"""
Применение результата синхронизации к таблице user_employee_extensions и обновление статуса источника.
Использует SQLAlchemy Core (text) — совместимо с воркером без Flask app context.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text


def _manual_extensions(connection, user_id: int) -> set:
    r = connection.execute(
        text(
            "SELECT extension FROM user_employee_extensions "
            "WHERE user_id = :uid AND origin_type = 'manual'"
        ),
        {"uid": user_id},
    )
    return {str(row[0]) for row in r.fetchall() if row[0]}


def apply_employee_mapping_sync_rows(
    connection,
    user_id: int,
    mode: str,
    rows: Sequence[Dict[str, Any]],
) -> int:
    """
    Применяет строки из API. mode: sync_replace | sync_only | sync_merge_manual_priority
    Возвращает число вставленных строк привязки.
    """
    now = datetime.utcnow()
    mode = (mode or '').strip()
    tuples: List[Tuple[str, str]] = []
    for r in rows:
        ext = (r.get('extension') or '').strip()
        emp = (r.get('employee') or '').strip()
        if ext and emp:
            tuples.append((ext, emp))

    if mode in ('sync_replace', 'sync_only'):
        connection.execute(
            text("DELETE FROM user_employee_extensions WHERE user_id = :uid"),
            {"uid": user_id},
        )
        n = 0
        for ext, emp in tuples:
            connection.execute(
                text(
                    """
                    INSERT INTO user_employee_extensions
                    (user_id, extension, employee, origin_type, external_ref, synced_at, created_at, updated_at)
                    VALUES (:uid, :ext, :emp, 'sync', NULL, :ts, :ts, :ts)
                    """
                ),
                {"uid": user_id, "ext": ext, "emp": emp, "ts": now},
            )
            n += 1
        return n

    if mode == 'sync_merge_manual_priority':
        manual_ext = _manual_extensions(connection, user_id)
        connection.execute(
            text(
                "DELETE FROM user_employee_extensions WHERE user_id = :uid AND origin_type = 'sync'"
            ),
            {"uid": user_id},
        )
        n = 0
        for ext, emp in tuples:
            if ext in manual_ext:
                continue
            connection.execute(
                text(
                    """
                    INSERT INTO user_employee_extensions
                    (user_id, extension, employee, origin_type, external_ref, synced_at, created_at, updated_at)
                    VALUES (:uid, :ext, :emp, 'sync', NULL, :ts, :ts, :ts)
                    """
                ),
                {"uid": user_id, "ext": ext, "emp": emp, "ts": now},
            )
            n += 1
        return n

    return 0


def update_mapping_source_status(
    connection,
    user_id: int,
    ok: bool,
    err: Optional[str],
    records_count: Optional[int],
) -> None:
    now = datetime.utcnow()
    err_s = (err or '')[:500] if err else None
    connection.execute(
        text(
            """
            UPDATE user_employee_mapping_sources SET
                last_attempt_at = :now,
                last_sync_ok = :ok,
                last_sync_error = :err,
                last_records_count = :cnt,
                last_success_at = CASE WHEN :ok THEN :now ELSE last_success_at END,
                updated_at = :now
            WHERE user_id = :uid
            """
        ),
        {"uid": user_id, "now": now, "ok": ok, "err": err_s, "cnt": records_count},
    )


def fetch_employee_mapping_dict(connection, user_id: int) -> Dict[str, str]:
    """Словарь extension -> employee для подстановки в config."""
    r = connection.execute(
        text(
            "SELECT extension, employee FROM user_employee_extensions WHERE user_id = :uid"
        ),
        {"uid": user_id},
    )
    return {str(row[0]): str(row[1]) for row in r.fetchall() if row[0] and row[1]}


def load_mapping_source_row(connection, user_id: int) -> Optional[Dict[str, Any]]:
    r = connection.execute(
        text(
            """
            SELECT mode, provider_type, enabled, refresh_ttl_seconds,
                   request_config, mapping_config, normalize_config,
                   last_success_at, last_attempt_at, last_sync_ok, last_sync_error, last_records_count
            FROM user_employee_mapping_sources WHERE user_id = :uid
            """
        ),
        {"uid": user_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        'mode': row[0],
        'provider_type': row[1],
        'enabled': row[2],
        'refresh_ttl_seconds': row[3] or 300,
        'request_config': row[4] or {},
        'mapping_config': row[5] or {},
        'normalize_config': row[6] or {},
        'last_success_at': row[7],
        'last_attempt_at': row[8],
        'last_sync_ok': row[9],
        'last_sync_error': row[10],
        'last_records_count': row[11],
    }
