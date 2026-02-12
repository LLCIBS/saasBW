# call_analyzer/rostelecom_connector.py
"""
Коннектор для получения записей звонков из облачной АТС Ростелеком.

Документация: https://numbers.cloudpbx.rt.ru/docs/
Интеграционный API. Руководство администратора домена v7.5
"""

import csv
import gzip
import hashlib
import io
import json
import os
import tempfile
import logging
import re
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
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
    timeout: int = 30,
    retries: int = 1,
    retry_delay: int = 30
) -> Tuple[Optional[str], Optional[str]]:
    """
    Запрашивает временную ссылку на запись разговора (get_record).
    Запись может появиться не сразу после завершения звонка — при необходимости
    выполняются повторные попытки.

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

    last_err = None
    for attempt in range(max(1, retries)):
        try:
            resp = requests.post(endpoint, data=body_json.encode('utf-8'), headers=headers, timeout=timeout)
            data = resp.json() if resp.text else {}

            result = str(data.get("result", ""))
            result_message = data.get("resultMessage", "")
            url = data.get("url")

            if result == "0" and url:
                return url, None
            last_err = result_message or f"Ошибка get_record: {resp.status_code}"
            if attempt < retries - 1:
                logger.info(f"get_record: попытка {attempt + 1}/{retries}, ответ: {last_err}, повтор через {retry_delay} с")
                time.sleep(retry_delay)
            else:
                break
        except Exception as e:
            last_err = str(e)
            logger.error(f"Ошибка запроса get_record (попытка {attempt + 1}): {e}", exc_info=True)
            if attempt < retries - 1:
                time.sleep(retry_delay)
    return None, last_err


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


def test_connection(
    api_url: str,
    client_id: str,
    sign_key: str,
    timeout: int = 15
) -> Tuple[bool, str]:
    """
    Проверяет подключение к API Ростелеком.
    Вызывает get_record с тестовым session_id — API вернёт ошибку сессии, но проверка
    подписи и учётных данных пройдёт (200 + result != 0 = аутентификация успешна).
    
    Returns:
        (success, message) — успех и сообщение для пользователя
    """
    body = {"session_id": "00000000-0000-0000-0000-000000000000"}
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
        
        # 200 + result != "0" — аутентификация прошла, сессия не найдена (ожидаемо для теста)
        if resp.status_code == 200 and result != "0":
            if "session" in (result_message or "").lower() or "сесси" in (result_message or "").lower():
                return True, "Подключение успешно (учётные данные верны)"
            return True, "Подключение успешно"
        if resp.status_code == 200 and result == "0":
            return True, "Подключение успешно"
        if resp.status_code == 401:
            return False, "Неверный код идентификации или ключ подписи"
        if resp.status_code == 403:
            return False, "Доступ запрещён. Проверьте права в ЛК Ростелеком"
        if resp.status_code >= 400:
            return False, result_message or f"Ошибка API: {resp.status_code}"
        return True, "Подключение успешно"
    except requests.exceptions.Timeout:
        return False, "Таймаут соединения. Проверьте адрес API и доступность сети"
    except requests.exceptions.ConnectionError:
        return False, "Ошибка соединения. Проверьте адрес API"
    except Exception as e:
        logger.error(f"Ошибка теста подключения Ростелеком: {e}", exc_info=True)
        return False, str(e)


def domain_call_history(
    api_url: str,
    client_id: str,
    sign_key: str,
    date_start: str,
    date_end: str,
    direction: int = 0,
    state: int = 0,
    phone_number: Optional[str] = None,
    timeout: int = 30
) -> Tuple[bool, str, Optional[str]]:
    """
    Запрос на формирование файла с выгрузкой журнала вызовов домена (A.3.8).
    date_start/date_end — по Москве, формат "yyyy-MM-dd HH:mm:ss".
    direction: 0=все, 1=входящие, 2=исходящие, 3=внутренние.
    state: 0=все, 1=принят, 2=не принят.

    Returns:
        (success, message, order_id)
    """
    body = {
        "date_start": date_start,
        "date_end": date_end,
        "direction": direction,
        "state": state,
    }
    if phone_number:
        body["phone_number"] = phone_number
    body_json = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
    sign = compute_sign(client_id, body_json, sign_key)
    endpoint = urljoin(api_url.rstrip('/') + '/', 'domain_call_history')
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Client-ID": client_id,
        "X-Client-Sign": sign,
    }
    try:
        resp = requests.post(endpoint, data=body_json.encode('utf-8'), headers=headers, timeout=timeout)
        data = resp.json() if resp.text else {}
        result = str(data.get("result", ""))
        result_message = (data.get("resultMessage") or "").strip()
        if resp.status_code == 200 and result == "0":
            return True, "Выгрузка заказана", data.get("order_id")
        if result_message and "уже существует" in result_message.lower():
            return False, "Выгрузка с этим периодом уже запрошена. Дождитесь уведомления о готовности файла или попробуйте через 5–10 минут.", None
        return False, result_message or f"Ошибка {resp.status_code}", None
    except Exception as e:
        logger.error(f"Rostelecom domain_call_history: {e}", exc_info=True)
        return False, str(e), None


def download_call_history(
    api_url: str,
    client_id: str,
    sign_key: str,
    order_id: str,
    timeout: int = 60
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    Запрос на скачивание файла журнала вызовов (A.3.9).
    Ответ — .CSV в gzip. Парсим в список словарей по столбцам.

    Returns:
        (success, message, rows) — rows с ключами session_id, is_record, start_call_date, direction, orig_number, dest_number, answering_pin, ...
    """
    body = {"order_id": order_id}
    body_json = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
    sign = compute_sign(client_id, body_json, sign_key)
    endpoint = urljoin(api_url.rstrip('/') + '/', 'download_call_history')
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Client-ID": client_id,
        "X-Client-Sign": sign,
    }
    try:
        resp = requests.post(endpoint, data=body_json.encode('utf-8'), headers=headers, timeout=timeout)
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "application/json" in ct or (resp.text and resp.text.strip().startswith('{')):
            data = resp.json() if resp.text else {}
            result = str(data.get("result", ""))
            msg = data.get("resultMessage", "Файл ещё не готов")
            if result != "0":
                return False, msg, []
            return False, msg or "Неожиданный JSON-ответ", []

        raw = resp.content
        if not raw:
            return False, "Пустой ответ", []

        try:
            decompressed = gzip.decompress(raw)
        except Exception:
            decompressed = raw
        text = decompressed.decode("utf-8", errors="replace")

        # Столбцы CSV по документации Ростелеком (A.3.9, Таблица A.3.14)
        CSV_COLUMNS = [
            "session_id", "call_type", "direction", "state",
            "orig_number", "orig_pin", "dest_number",
            "answering_sipuri", "answering_pin",
            "start_call_date", "duration",
            "is_voicemail", "is_record", "is_fax",
            "status_code", "status_string",
        ]

        lines = text.strip().splitlines()
        if not lines:
            return True, "Загружено записей: 0", []

        # Проверяем, есть ли заголовки (если первая строка содержит session_id)
        first_line = lines[0].lower()
        has_headers = "session_id" in first_line

        # Читаем CSV через файл с newline='' — корректная обработка переводов строк
        tmp_path = None
        rows = []
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".csv", text=True)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            with open(tmp_path, "r", encoding="utf-8", newline="") as f:
                if has_headers:
                    reader = csv.DictReader(f, delimiter=",")
                else:
                    reader = csv.DictReader(f, fieldnames=CSV_COLUMNS, delimiter=",")
                rows = list(reader)
        except csv.Error as ce:
            if "new-line" in str(ce).lower() or "newline" in str(ce).lower():
                # Fallback: некорректные переносы в полях — считаем разделителем \r\n, иначе \n
                logger.warning(f"Rostelecom CSV: fallback из-за вложенных переносов — {ce}")
                sep = "\r\n" if "\r\n" in text else "\n"
                lines = text.split(sep)
                sanitized = "\n".join(ln.replace("\n", " ").replace("\r", " ") for ln in lines)
                try:
                    with io.StringIO(sanitized) as s:
                        rdr = csv.DictReader(s, fieldnames=CSV_COLUMNS, delimiter=",")
                        rows = [r for r in rdr if (r.get("session_id") or "").strip()]
                except csv.Error:
                    rows = []
            else:
                raise
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        logger.info(f"Rostelecom download_call_history: {len(rows)} строк, заголовки={has_headers}")
        return True, f"Загружено записей: {len(rows)}", rows
    except Exception as e:
        logger.error(f"Rostelecom download_call_history: {e}", exc_info=True)
        return False, str(e), []


def fetch_call_history(
    api_url: str,
    client_id: str,
    sign_key: str,
    date_from: datetime,
    date_to: datetime,
    direction: int = 0,
    state: int = 0,
    poll_interval: int = 20,
    poll_max_wait: int = 300,
    timeout: int = 60
) -> Tuple[bool, str, list]:
    """
    Получение истории звонков по документации Ростелеком:
    1) domain_call_history — заказ выгрузки → order_id;
    2) опрос download_call_history до появления файла (или таймаут);
    3) разбор CSV и приведение к формату {session_id, from_number, request_number, request_pin, type, timestamp, is_record}.

    Returns:
        (success, message, list_of_calls) — список готов для передачи в get_record по session_id.
    """
    date_start = date_from.strftime("%Y-%m-%d 00:00:00")
    date_end = date_to.strftime("%Y-%m-%d 23:59:59")
    ok, msg, order_id = domain_call_history(
        api_url, client_id, sign_key, date_start, date_end,
        direction=direction, state=state, timeout=timeout
    )
    if not ok or not order_id:
        return False, msg or "Не получен order_id", []

    waited = 0
    while waited < poll_max_wait:
        time.sleep(min(poll_interval, poll_max_wait - waited))
        waited += poll_interval
        ok, msg, rows = download_call_history(api_url, client_id, sign_key, order_id, timeout=timeout)
        if ok and rows is not None:
            # Приводим строки CSV к формату, ожидаемому sync: from_number, request_number, request_pin, type, timestamp, is_record
            # CSV: session_id, direction (1=вх, 2=исх, 3=внутр), orig_number, orig_pin, dest_number, answering_pin, start_call_date, is_record
            dir_map = {"1": "incoming", "2": "outbound", "3": "internal"}
            calls = []
            for r in rows:
                sid = (r.get("session_id") or "").strip()
                if not sid:
                    continue
                is_rec = (r.get("is_record") or "").strip().upper() in ("TRUE", "1", "YES")
                direction_val = r.get("direction", "1")
                call_type = dir_map.get(str(direction_val).strip(), "incoming")
                start_date = (r.get("start_call_date") or "").strip()
                orig = (r.get("orig_number") or "").strip()
                dest = (r.get("dest_number") or "").strip()
                ans_pin = (r.get("answering_pin") or "").strip()
                orig_pin = (r.get("orig_pin") or "").strip()
                calls.append({
                    "session_id": sid,
                    "from_number": orig,
                    "request_number": dest,
                    "request_pin": ans_pin or orig_pin,
                    "type": call_type,
                    "timestamp": start_date,
                    "is_record": "true" if is_rec else "false",
                })
            return True, msg, calls
        if "ещё не готов" in (msg or "").lower() or "not ready" in (msg or "").lower():
            continue
        if msg and "загружено" not in msg.lower():
            return False, msg, []

    return False, "Файл выгрузки не получен за отведённое время. Попробуйте позже или проверьте уведомления.", []


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
