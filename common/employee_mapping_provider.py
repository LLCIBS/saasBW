# -*- coding: utf-8 -*-
"""
Универсальное получение и разбор списка привязок «добавочный → сотрудник» из REST JSON.
Без доступа к БД — только HTTP и нормализация.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_BODY_BYTES = 10 * 1024 * 1024


def _navigate_path(obj: Any, path: str) -> Any:
    """Путь вида 'data.items' или пустая строка — корень."""
    if path is None or str(path).strip() == '':
        return obj
    cur = obj
    for part in str(path).strip().split('.'):
        if part == '':
            continue
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                idx = int(part)
                cur = cur[idx]
            except (ValueError, IndexError, TypeError):
                return None
        else:
            return None
    return cur


def _get_field(item: Any, field: str) -> Any:
    if not field:
        return None
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)


def normalize_extension(value: Any, cfg: Optional[Dict[str, Any]]) -> str:
    cfg = cfg or {}
    s = '' if value is None else str(value).strip()
    if cfg.get('strip_non_digits'):
        s = re.sub(r'\D', '', s)
    # ограничение как в БД
    max_len = int(cfg.get('max_extension_len') or 20)
    s = s[:max_len]
    return s


def fetch_generic_rest_json(
    request_config: Dict[str, Any],
    mapping_config: Dict[str, Any],
    normalize_config: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Выполняет HTTP-запрос и извлекает список записей {extension, employee, raw?}.

    request_config:
      url (str), method (GET|POST), headers (dict), params (dict), json_body (any),
      timeout_sec (int), auth_type: none|bearer|basic|header,
      auth_token, auth_username, auth_password, auth_header_name, auth_header_value

    mapping_config:
      items_path (str), extension_field (str), employee_field (str)
    """
    normalize_config = normalize_config or {}
    url = (request_config or {}).get('url') or ''
    url = str(url).strip()
    if not url:
        return [], 'Не указан URL источника'

    method = (request_config.get('method') or 'GET').upper()
    if method not in ('GET', 'POST'):
        method = 'GET'

    timeout = int(request_config.get('timeout_sec') or DEFAULT_TIMEOUT)
    timeout = max(5, min(timeout, 120))

    headers = dict(request_config.get('headers') or {})
    params = dict(request_config.get('params') or {})
    json_body = request_config.get('json_body')

    auth_type = (request_config.get('auth_type') or 'none').lower()
    if auth_type == 'bearer':
        token = (request_config.get('auth_token') or '').strip()
        if token:
            headers['Authorization'] = f'Bearer {token}'
    elif auth_type == 'header':
        hn = (request_config.get('auth_header_name') or '').strip()
        hv = (request_config.get('auth_header_value') or '').strip()
        if hn:
            headers[hn] = hv

    auth = None
    if auth_type == 'basic':
        u = request_config.get('auth_username') or ''
        p = request_config.get('auth_password') or ''
        auth = (str(u), str(p))

    try:
        if method == 'GET':
            resp = requests.get(
                url, headers=headers, params=params, timeout=timeout, auth=auth,
            )
        else:
            resp = requests.post(
                url,
                headers=headers,
                params=params,
                json=json_body if json_body is not None else None,
                timeout=timeout,
                auth=auth,
            )
    except requests.RequestException as exc:
        logger.warning('employee_mapping HTTP error: %s', exc)
        return [], str(exc)[:500]

    if not resp.ok:
        return [], f'HTTP {resp.status_code}: {(resp.text or "")[:200]}'

    raw_len = len(resp.content or b'')
    if raw_len > MAX_BODY_BYTES:
        return [], 'Ответ слишком большой'

    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        return [], f'Не JSON: {exc}'

    items_path = (mapping_config or {}).get('items_path') or ''
    ext_field = (mapping_config or {}).get('extension_field') or 'extension'
    emp_field = (mapping_config or {}).get('employee_field') or 'employee'

    target = _navigate_path(data, items_path)
    if target is None:
        return [], 'Путь items_path не найден в ответе'

    if isinstance(target, dict):
        items = [target]
    elif isinstance(target, list):
        items = target
    else:
        return [], 'По items_path ожидался объект или массив'

    out: List[Dict[str, Any]] = []
    seen = set()
    for it in items:
        ext_raw = _get_field(it, ext_field)
        emp_raw = _get_field(it, emp_field)
        ext = normalize_extension(ext_raw, normalize_config)
        emp = '' if emp_raw is None else str(emp_raw).strip()
        if not ext or not emp:
            continue
        if ext in seen:
            continue
        seen.add(ext)
        row = {'extension': ext, 'employee': emp, 'raw': it if isinstance(it, dict) else None}
        out.append(row)

    if not out:
        return [], 'После разбора не осталось ни одной пары добавочный→сотрудник'

    return out, None
