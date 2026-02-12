# call_analyzer/rostelecom_connector.py
"""
Коннектор для получения записей звонков из облачной АТС Ростелеком.

Документация: https://numbers.cloudpbx.rt.ru/docs/
Интеграционный API. Руководство администратора домена v7.5
"""

import hashlib
import json
import logging
import re
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# Продуктивный API Ростелеком
ROSTELECOM_API_URL = 'https://api.cloudpbx.rt.ru'
ROSTELECOM_API_TEST = 'https://api-test.cloudpbx.rt.ru'


def compute_sign(client_id: str, body_json: str, sign_key: str) -> str:
    """
    Вычисляет подпись X-Client-Sign по документации Ростелеком.
    X-Client-Sign = sha256hex(client_id + body_json + sign_key)
    """
    raw = f"{client_id}{body_json}{sign_key}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def verify_sign(client_id: str, body_json: str, sign_key: str, received_sign: str) -> bool:
    """Проверяет подпись входящего запроса от Ростелеком."""
    expected = compute_sign(client_id, body_json, sign_key)
    return expected == received_sign


def get_record(
    api_url: str,
    client_id: str,
    sign_key: str,
    session_id: str,
    ip_address: Optional[str] = None,
    timeout: int = 30
) -> Tuple[Optional[str], Optional[str]]:
    """
    Запрашивает временную ссылку на запись разговора (get_record).
    
    Returns:
        (url, error_message) - url если успешно, иначе (None, error_message)
    """
    body = {
        "session_id": session_id,
    }
    if ip_address:
        body["ip_adress"] = ip_address  # В API опечатка: ip_adress

    body_json = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
    sign = compute_sign(client_id, body_json, sign_key)

    endpoint = urljoin(api_url.rstrip('/') + '/', 'get_record')
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Client-ID": client_id,
        "X-Client-Sign": sign,
    }

    try:
        resp = requests.post(endpoint, data=body_json.encode('utf-8'), headers=headers, timeout=timeout)
        data = resp.json() if resp.text else {}

        result = str(data.get("result", ""))
        result_message = data.get("resultMessage", "")
        url = data.get("url")

        if result == "0" and url:
            return url, None
        return None, result_message or f"Ошибка get_record: {resp.status_code}"
    except Exception as e:
        logger.error(f"Ошибка запроса get_record: {e}", exc_info=True)
        return None, str(e)


def download_recording(url: str, save_path: Path, timeout: int = 120) -> bool:
    """Скачивает запись по временной ссылке и сохраняет в файл."""
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return save_path.exists() and save_path.stat().st_size > 0
    except Exception as e:
        logger.error(f"Ошибка скачивания записи {url}: {e}", exc_info=True)
        return False


def make_rostelecom_filename(
    session_id: str,
    from_number: str,
    request_number: str,
    request_pin: Optional[str],
    call_type: str,
    timestamp_str: str
) -> str:
    """
    Формирует имя файла в формате rostelecom-* для совместимости с parse_filename.
    rostelecom-{type}-{from}_{request_pin_or_request}_{timestamp}-{session_short}.mp3
    """
    # Нормализуем номера: убираем sip:, @, оставляем цифры
    def _norm(s: str) -> str:
        if not s:
            return ""
        s = re.sub(r'^sip:', '', s, flags=re.I)
        s = re.sub(r'@.*$', '', s)
        digits = re.sub(r'\D', '', s)
        return digits or s[:15]

    from_clean = _norm(from_number) or "unknown"
    req_clean = _norm(request_number) or "unknown"
    pin = request_pin or req_clean
    # Берём короткую часть session_id для уникальности
    sid_short = (session_id or "")[-12:] if session_id else ""

    # timestamp в формате YYYYMMDD-HHMMSS
    ts_clean = timestamp_str.replace(" ", "-").replace(":", "").replace(".", "")[:15]

    return f"rostelecom-{call_type}-{from_clean}_{pin}_{ts_clean}-{sid_short}.mp3"


def parse_rostelecom_filename(filename: str) -> Optional[Tuple[str, str, datetime]]:
    """
    Парсит имя файла rostelecom-*.
    Возвращает (phone_number, station_code, call_time) или None.
    """
    # rostelecom-incoming-79536154237_317_20250411-153022-abc123.mp3
    m = re.match(
        r'^rostelecom-(incoming|outbound|internal)-(\d+)_(\w+)_(\d{8})-(\d{6})(?:-\w+)?\.(mp3|wav)$',
        filename,
        re.I
    )
    if not m:
        return None
    try:
        call_type = m.group(1)
        from_phone = m.group(2)
        pin_or_station = m.group(3)
        yyyymmdd = m.group(4)
        hhmmss = m.group(5)
        call_time = datetime.strptime(f"{yyyymmdd}{hhmmss}", "%Y%m%d%H%M%S")
        phone = from_phone if call_type == "incoming" else pin_or_station
        station = pin_or_station if call_type == "incoming" else from_phone
        return phone, station, call_time
    except Exception:
        return None
