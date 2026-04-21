# -*- coding: utf-8 -*-
"""
Разбор REST/JSON для источника «Кастомный API»: HTTP-запрос и извлечение списка записей
с полями record_url, station, original_filename и опционально external_id, timestamp.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

from common.employee_mapping_provider import MAX_BODY_BYTES, _get_field, _navigate_path

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30

DEFAULT_REQUEST_CONFIG: Dict[str, Any] = {
    'url': '',
    'method': 'GET',
    'headers': {},
    'params': {},
    'json_body': None,
    'timeout_sec': 30,
    'verify_ssl': True,
    'auth_type': 'none',
    'auth_token': '',
    'auth_username': '',
    'auth_password': '',
    'auth_header_name': '',
    'auth_header_value': '',
}

DEFAULT_MAPPING_CONFIG: Dict[str, Any] = {
    'items_path': '',
    'record_url_field': 'record_url',
    'station_field': 'station',
    'original_filename_field': 'filename',
    'external_id_field': '',
    'timestamp_field': '',
    # Если в JSON приходит путь (/2026/.../file.mp3), а не полный URL — добавляется к этому префиксу
    'recording_base_url': '',
}


def clean_internal_station_value(raw: Any) -> str:
    """
    Только цифры внутреннего номера; убирает случайные вхождения _sk_ / __sk_ из строки.
    """
    s = str(raw or '').strip()
    if not s:
        return '0'
    s = re.sub(r'(?i)_+sk_+', '', s)
    s = re.sub(r'\D', '', s)
    return s or '0'


def apply_recording_base_url(raw: str, base_url: Optional[str]) -> str:
    """
    Если значение уже http(s) — без изменений.
    Иначе к необязательному префиксу (например http://host/bw-cdr) добавляется путь из поля записи.
    """
    s = (raw or '').strip()
    if not s:
        return s
    low = s.lower()
    if low.startswith(('http://', 'https://')):
        return s
    b = (base_url or '').strip()
    if not b:
        return s
    b = b.rstrip('/')
    if s.startswith('/'):
        return b + s
    return f'{b}/{s}'


def merge_request_config(req: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(DEFAULT_REQUEST_CONFIG)
    if req:
        out.update({k: v for k, v in req.items() if v is not None})
    return out


def merge_mapping_config(m: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(DEFAULT_MAPPING_CONFIG)
    if m:
        out.update({k: v for k, v in m.items() if v is not None})
    return out


def _execute_http(request_config: Dict[str, Any]) -> Tuple[Optional[Any], Optional[str]]:
    req = merge_request_config(request_config)
    url = str(req.get('url') or '').strip()
    if not url:
        return None, 'Не указан URL'

    method = (req.get('method') or 'GET').upper()
    if method not in ('GET', 'POST'):
        method = 'GET'

    timeout = int(req.get('timeout_sec') or DEFAULT_TIMEOUT)
    timeout = max(5, min(timeout, 120))
    verify_ssl = bool(req.get('verify_ssl', True))

    headers = dict(req.get('headers') or {})
    params = dict(req.get('params') or {})
    json_body = req.get('json_body')

    auth_type = (req.get('auth_type') or 'none').lower()
    if auth_type == 'bearer':
        token = (req.get('auth_token') or '').strip()
        if token:
            headers['Authorization'] = f'Bearer {token}'
    elif auth_type == 'header':
        hn = (req.get('auth_header_name') or '').strip()
        hv = (req.get('auth_header_value') or '').strip()
        if hn:
            headers[hn] = hv

    auth = None
    if auth_type == 'basic':
        u = req.get('auth_username') or ''
        p = req.get('auth_password') or ''
        auth = (str(u), str(p))

    try:
        if not verify_ssl:
            requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
        if method == 'GET':
            resp = requests.get(
                url, headers=headers, params=params, timeout=timeout, auth=auth, verify=verify_ssl,
            )
        else:
            resp = requests.post(
                url,
                headers=headers,
                params=params,
                json=json_body if json_body is not None else None,
                timeout=timeout,
                auth=auth,
                verify=verify_ssl,
            )
    except requests.RequestException as exc:
        logger.warning('custom_api HTTP error: %s', exc)
        return None, str(exc)[:500]

    if not resp.ok:
        return None, f'HTTP {resp.status_code}: {(resp.text or "")[:200]}'

    raw_len = len(resp.content or b'')
    if raw_len > MAX_BODY_BYTES:
        return None, 'Ответ слишком большой'

    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        return None, f'Не JSON: {exc}'

    return data, None


def _parse_timestamp(val: Any) -> Optional[datetime]:
    if val is None or val == '':
        return None
    if isinstance(val, (int, float)):
        try:
            ts = int(val)
            if ts > 1_000_000_000_000:
                ts = ts // 1000
            return datetime.utcfromtimestamp(ts)
        except (ValueError, OSError, OverflowError):
            return None
    s = str(val).strip()
    if not s:
        return None
    for fmt in (
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M:%S.%f',
    ):
        try:
            return datetime.strptime(s[:26].replace('Z', ''), fmt.replace('Z', ''))
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def _sanitize_filename_base(name: str) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    base = base.strip() or 'recording'
    return base[:200]


def parse_items_from_json(
    data: Any,
    mapping_config: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    m = merge_mapping_config(mapping_config)
    items_path = (m.get('items_path') or '').strip()
    record_f = (m.get('record_url_field') or 'record_url').strip()
    station_f = (m.get('station_field') or 'station').strip()
    orig_f = (m.get('original_filename_field') or 'filename').strip()
    ext_id_f = (m.get('external_id_field') or '').strip()
    ts_f = (m.get('timestamp_field') or '').strip()

    if not record_f or not station_f or not orig_f:
        return [], 'Укажите record_url_field, station_field и original_filename_field'

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
    for it in items:
        if not isinstance(it, dict):
            continue
        record_url = _get_field(it, record_f)
        station = _get_field(it, station_f)
        original = _get_field(it, orig_f)
        if record_url is None or str(record_url).strip() == '':
            continue
        if station is None or str(station).strip() == '':
            continue
        if original is None or str(original).strip() == '':
            continue

        record_url_s = str(record_url).strip()
        base_u = (m.get('recording_base_url') or '').strip()
        record_url_s = apply_recording_base_url(record_url_s, base_u)

        station_s = clean_internal_station_value(station)
        orig_s = _sanitize_filename_base(str(original).strip().split('/')[-1].split('\\')[-1])

        ext_id = None
        if ext_id_f:
            ext_id = _get_field(it, ext_id_f)
        ext_id_s = str(ext_id).strip() if ext_id is not None else ''

        ts_val = _get_field(it, ts_f) if ts_f else None
        call_dt = _parse_timestamp(ts_val)

        if not ext_id_s:
            h = hashlib.sha256(
                f'{record_url_s}|{orig_s}|{ts_val}'.encode('utf-8', errors='replace')
            ).hexdigest()
            ext_id_s = h

        out.append({
            'external_id': ext_id_s,
            'record_url': record_url_s,
            'station_code': station_s,
            'original_filename': orig_s,
            'call_datetime': call_dt,
            'raw': it,
        })

    if not out:
        return [], 'После разбора не осталось ни одной записи с record_url, station и filename'

    return out, None


def fetch_custom_api_records(
    request_config: Dict[str, Any],
    mapping_config: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    data, err = _execute_http(request_config)
    if err:
        return [], err
    return parse_items_from_json(data, mapping_config)
