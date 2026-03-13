# call_analyzer/rostelecom_connector.py
"""
Коннектор для получения записей звонков из облачной АТС Ростелеком.

Документация: https://numbers.cloudpbx.rt.ru/docs/
Интеграционный API. Руководство администратора домена v7.5

Реальное поведение API (расходится с документацией):
- Файл выгрузки отдаётся в формате ZIP (не GZIP), несмотря на расширение .csv.z
- Разделитель в CSV — точка с запятой (;), а не запятая
- После domain_call_history файл генерируется асинхронно: первые опросы
  download_call_history возвращают HTML "File not found" — это норма, нужно ждать
"""

import csv
import gzip
import hashlib
import io
import json
import logging
import re
import time
import zipfile
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

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
        (url, error_message) — url если успешно, иначе (None, error_message)
    """
    body = {"session_id": session_id}
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
    sid_short = (session_id or "")[-12:] if session_id else ""
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
            return False, "Выгрузка с этим периодом уже запрошена. Дождитесь готовности файла или попробуйте через 5–10 минут.", None
        return False, result_message or f"Ошибка {resp.status_code}", None
    except Exception as e:
        logger.error(f"Rostelecom domain_call_history: {e}", exc_info=True)
        return False, str(e), None


def _decompress_response(raw: bytes) -> Optional[str]:
    """
    Распаковывает тело ответа API Ростелеком.
    Реальный формат — ZIP (PK), документация говорит GZIP — неверно.
    Поддерживает: ZIP, GZIP, plain text.
    """
    if not raw:
        return None

    if raw[:2] == b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                target = next((n for n in names if n.lower().endswith('.csv')), names[0] if names else None)
                if not target:
                    return None
                logger.info(f"Rostelecom: ZIP-архив, извлекаем '{target}'")
                return zf.read(target).decode('utf-8', errors='replace')
        except zipfile.BadZipFile:
            logger.warning("Rostelecom: PK-сигнатура, но BadZipFile — пробуем GZIP")

    if raw[:2] == b'\x1f\x8b':
        try:
            return gzip.decompress(raw).decode('utf-8', errors='replace')
        except Exception as e:
            logger.warning(f"Rostelecom: GZIP-ошибка: {e}")

    try:
        return gzip.decompress(raw).decode('utf-8', errors='replace')
    except Exception:
        pass

    return raw.decode('utf-8', errors='replace')


def _is_file_not_ready(msg: str) -> bool:
    """Проверяет, означает ли ответ 'файл ещё не готов' (нужно продолжать опрос)."""
    if not msg:
        return False
    lower = msg.lower()
    return (
        "ещё не готов" in lower
        or "not ready" in lower
        or "not found" in lower
        or "file [" in lower
        or "не найден" in lower
        or "ожидайте" in lower
        or "please wait" in lower
    )


def _get_field(row: dict, *keys: str) -> str:
    """Поиск значения в словаре без учёта регистра и символа подчёркивания."""
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    lower_map = {str(x).lower().replace("_", ""): x for x in row}
    for k in keys:
        k_norm = str(k).lower().replace("_", "")
        if k_norm in lower_map:
            return str(row.get(lower_map[k_norm]) or "").strip()
    return ""


def download_call_history(
    api_url: str,
    client_id: str,
    sign_key: str,
    order_id: str,
    timeout: int = 60
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    Запрос на скачивание файла журнала вызовов (A.3.9).
    Ответ — ZIP-архив с CSV внутри (разделитель ";").

    Returns:
        (success, message, rows) — rows содержат ключи по Таблице A.3.14 документации.
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
            return False, msg if result != "0" else (msg or "Неожиданный JSON-ответ"), []

        raw = resp.content
        if not raw:
            return False, "Пустой ответ", []

        text = _decompress_response(raw)
        if text is None:
            return False, "Не удалось распаковать архив из ответа Ростелеком", []

        text_lower = text.strip().lower()[:300]
        if "<html" in text_lower or "<!doctype" in text_lower or ("<h1>" in text_lower and "not found" in text_lower):
            err_match = re.search(r'File \[([^\]]+)\] not found', text, re.I)
            err_msg = err_match.group(0) if err_match else "Файл выгрузки не найден на стороне Ростелеком"
            logger.warning(f"Rostelecom download_call_history: HTML-ответ вместо CSV — {err_msg}")
            return False, err_msg, []

        # Столбцы по документации A.3.9, Таблица A.3.14
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

        # Реальный разделитель — ";", документация неверно указывает ","
        first_line = lines[0]
        delimiter = ';' if first_line.count(';') > first_line.count(',') else ','
        has_headers = "session_id" in first_line.lower()

        rows = []
        try:
            with io.StringIO(text) as sio:
                reader = csv.DictReader(sio, fieldnames=None if has_headers else CSV_COLUMNS, delimiter=delimiter)
                for row in reader:
                    if row.get("session_id", "").strip():
                        rows.append(row)
        except csv.Error as ce:
            logger.warning(f"Rostelecom CSV parse error: {ce}, fallback построчно")
            rows = []
            for i, line in enumerate(lines):
                if has_headers and i == 0:
                    continue
                parts = line.split(delimiter)
                if len(parts) < 2:
                    continue
                padded = parts + [''] * max(0, len(CSV_COLUMNS) - len(parts))
                row = dict(zip(CSV_COLUMNS, padded))
                if row.get("session_id", "").strip():
                    rows.append(row)

        logger.info(f"Rostelecom download_call_history: {len(rows)} записей, разделитель='{delimiter}'")
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
    poll_interval: int = 30,
    poll_max_wait: int = 600,
    timeout: int = 60
) -> Tuple[bool, str, list]:
    """
    Получение истории звонков по документации Ростелеком (A.3.8 + A.3.9):
    1) domain_call_history — заказ выгрузки → order_id;
    2) опрос download_call_history каждые poll_interval сек (файл генерируется асинхронно);
    3) разбор CSV и приведение к формату {session_id, from_number, request_number,
       request_pin, type, timestamp, is_record}.

    Returns:
        (success, message, list_of_calls)
    """
    date_start = date_from.strftime("%Y-%m-%d %H:%M:%S")
    date_end = date_to.strftime("%Y-%m-%d %H:%M:%S")
    ok, msg, order_id = domain_call_history(
        api_url, client_id, sign_key, date_start, date_end,
        direction=direction, state=state, timeout=timeout
    )
    if not ok or not order_id:
        return False, msg or "Не получен order_id", []

    logger.info(f"Rostelecom fetch: order_id={order_id}, опрос каждые {poll_interval}с, макс {poll_max_wait}с")

    dir_map = {"1": "incoming", "2": "outbound", "3": "internal"}
    waited = 0
    last_msg = ""
    while waited < poll_max_wait:
        sleep_time = min(poll_interval, poll_max_wait - waited)
        time.sleep(sleep_time)
        waited += sleep_time
        ok, msg, rows = download_call_history(api_url, client_id, sign_key, order_id, timeout=timeout)
        last_msg = msg or ""

        if ok and rows is not None:
            calls = []
            for r in rows:
                sid = (r.get("session_id") or "").strip()
                if not sid:
                    continue
                is_rec_val = _get_field(r, "is_record", "isrecord").upper()
                is_rec = is_rec_val in ("TRUE", "1", "YES", "ДА", "T", "+", "Y") or is_rec_val.startswith("TRUE")
                call_type = dir_map.get(str(r.get("direction", "1")).strip(), "incoming")
                calls.append({
                    "session_id": sid,
                    "from_number": (r.get("orig_number") or "").strip(),
                    "request_number": (r.get("dest_number") or "").strip(),
                    "request_pin": (r.get("answering_pin") or r.get("orig_pin") or "").strip(),
                    "type": call_type,
                    "timestamp": (r.get("start_call_date") or "").strip(),
                    "is_record": "true" if is_rec else "false",
                })
            with_rec = sum(1 for c in calls if c["is_record"] == "true")
            logger.info(f"Rostelecom fetch_call_history: {with_rec} из {len(calls)} звонков с записью")
            return True, msg, calls

        if _is_file_not_ready(msg):
            logger.debug(f"Rostelecom fetch: файл не готов ({waited}/{poll_max_wait}с): {msg}")
            continue

        logger.warning(f"Rostelecom fetch: ошибка при скачивании: {msg}")
        return False, msg, []

    return False, f"Файл выгрузки не получен за {poll_max_wait} сек. Последний ответ: {last_msg}. Попробуйте позже.", []


def parse_rostelecom_filename(filename: str) -> Optional[Tuple[str, str, datetime]]:
    """
    Парсит имя файла rostelecom-*.
    Возвращает (phone_number, station_code, call_time) или None.
    """
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
