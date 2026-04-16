# -*- coding: utf-8 -*-
"""
Обновление привязки номеров перед разбором звонка (воркер call_analyzer):
- по TTL — запрос к внешнему API и запись в БД;
- всегда — перечитать словарь из БД в config.EMPLOYEE_BY_EXTENSION.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import create_engine

logger = logging.getLogger(__name__)

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from config.settings import get_config

        _engine = create_engine(
            get_config().SQLALCHEMY_DATABASE_URI,
            pool_pre_ping=True,
        )
    return _engine


def _should_fetch_http(src: Dict[str, Any], now: datetime) -> bool:
    if not src.get('enabled'):
        return False
    mode = (src.get('mode') or '').strip()
    if mode == 'manual' or mode not in (
        'sync_replace',
        'sync_merge_manual_priority',
        'sync_only',
    ):
        return False
    if (src.get('provider_type') or 'generic_rest_json') != 'generic_rest_json':
        return False
    ttl = int(src.get('refresh_ttl_seconds') or 300)
    ttl = max(60, min(ttl, 86400))
    last_ok = src.get('last_success_at')
    if last_ok is None:
        return True
    if isinstance(last_ok, datetime):
        return (now - last_ok) >= timedelta(seconds=ttl)
    return True


def refresh_employee_mapping_if_needed() -> None:
    """
    Вызывается из пайплайна разбора звонка. Использует CALL_ANALYZER_USER_ID.
    """
    uid = os.getenv('CALL_ANALYZER_USER_ID')
    if not uid:
        return
    try:
        user_id = int(uid)
    except (TypeError, ValueError):
        return

    try:
        from common.employee_mapping_provider import fetch_generic_rest_json
        from common.employee_mapping_sync_db import (
            apply_employee_mapping_sync_rows,
            fetch_employee_mapping_dict,
            load_mapping_source_row,
            update_mapping_source_status,
        )
    except ImportError as exc:
        logger.debug('employee_mapping imports: %s', exc)
        return

    import config as runtime_config

    engine = _get_engine()
    now = datetime.utcnow()

    try:
        with engine.begin() as conn:
            src = load_mapping_source_row(conn, user_id)

            if src and _should_fetch_http(src, now):
                req = dict(src.get('request_config') or {})
                mapp = dict(src.get('mapping_config') or {})
                norm = dict(src.get('normalize_config') or {})
                mode = (src.get('mode') or 'manual').strip()

                rows, err = fetch_generic_rest_json(req, mapp, norm)
                if err:
                    update_mapping_source_status(conn, user_id, False, err, None)
                    logger.warning(
                        'Привязка номеров: синхронизация user=%s не удалась: %s',
                        user_id,
                        err,
                    )
                else:
                    n = apply_employee_mapping_sync_rows(conn, user_id, mode, rows)
                    update_mapping_source_status(conn, user_id, True, None, n)
                    logger.info(
                        'Привязка номеров: синхронизировано %s записей (user=%s)',
                        n,
                        user_id,
                    )

            mapping = fetch_employee_mapping_dict(conn, user_id)
    except Exception as exc:
        logger.warning('Привязка номеров: ошибка обновления: %s', exc)
        try:
            with engine.connect() as conn:
                mapping = fetch_employee_mapping_dict(conn, user_id)
        except Exception:
            return

    try:
        runtime_config.EMPLOYEE_BY_EXTENSION = mapping
        if hasattr(runtime_config, 'PROFILE_SETTINGS') and isinstance(
            runtime_config.PROFILE_SETTINGS, dict
        ):
            runtime_config.PROFILE_SETTINGS['employee_by_extension'] = mapping
    except Exception as exc:
        logger.debug('Не удалось записать EMPLOYEE_BY_EXTENSION: %s', exc)
