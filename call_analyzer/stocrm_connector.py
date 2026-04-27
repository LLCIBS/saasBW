# call_analyzer/stocrm_connector.py
"""
Коннектор для получения записей звонков из CRM StoCRM.

Документация API:
  Список звонков: https://stocrm.ru/wiki/article/WIKI-A-627/
  Получить запись: https://stocrm.ru/wiki/article/WIKI-A-629/
  Параметры фильтра: https://stocrm.ru/wiki/article/WIKI-A-628/

Схема работы:
  1. GET /api/external/v1/calls/get_filtered?SID=...  — получить список звонков (HAS_RECORD=Y)
  2. GET /api/external/v1/call/get_record?SID=...&UUID=...  — получить аудио (StoCRM возвращает
     либо бинарный MP3 напрямую, либо URL/JSON с ссылкой)
  3. Сохранить аудиофайл в папку пользователя
"""

import logging
import re
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_MSK_TZ = ZoneInfo("Europe/Moscow")


def moscow_datetime_from_unix(ts: int) -> datetime:
    """
    Unix epoch из StoCRM (UTC) → наивный datetime с компонентами часового пояса Europe/Moscow.
    Используется для имён файлов и путей, чтобы в отчётах совпадало с московским временем.
    """
    return (
        datetime.fromtimestamp(int(ts), tz=timezone.utc)
        .astimezone(_MSK_TZ)
        .replace(tzinfo=None)
    )


def moscow_now_naive() -> datetime:
    """Текущее время по Москве без tzinfo (для fallback в имени файла)."""
    return datetime.now(_MSK_TZ).replace(tzinfo=None)

STOCRM_BASE_TPL = "https://{domain}.stocrm.ru"

# Направления: StoCRM → внутренние
_DCONTEXT_MAP = {
    "IN": "incoming",
    "OUT": "outbound",
}


def _base_url(domain: str) -> str:
    """Строит базовый URL из поддомена или полного хоста."""
    domain = domain.strip().rstrip("/")
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain
    if "stocrm.ru" in domain:
        return f"https://{domain}"
    return STOCRM_BASE_TPL.format(domain=domain)


def _norm_phone(phone: str) -> str:
    """Оставляет только цифры."""
    if not phone:
        return "unknown"
    digits = re.sub(r"\D", "", str(phone))
    return digits or str(phone)[:20]


def make_stocrm_filename(
    phone: str,
    workstation_id: Any,
    dcontext: str,
    timestamp_unix: int,
    call_uuid: str = "",
) -> str:
    """
    Формирует имя файла в формате:
      stocrm-{direction}-{phone}_{workstation_id}_{YYYYMMDD}-{HHMMSS}.mp3

    Дата/время в имени — по Europe/Moscow (из Unix-времени StoCRM).

    Пример: stocrm-incoming-79161234567_6_20241215-143022.mp3
    """
    direction = _DCONTEXT_MAP.get(str(dcontext).upper(), "incoming")
    phone_clean = _norm_phone(phone)
    ws = re.sub(r"\W", "", str(workstation_id)) or "0"
    try:
        dt = moscow_datetime_from_unix(int(timestamp_unix))
        ts_str = dt.strftime("%Y%m%d-%H%M%S")
    except Exception:
        ts_str = moscow_now_naive().strftime("%Y%m%d-%H%M%S")
    return f"stocrm-{direction}-{phone_clean}_{ws}_{ts_str}.mp3"


def parse_stocrm_filename(filename: str) -> Optional[Tuple[str, str, datetime]]:
    """
    Разбирает имя файла stocrm-*.
    Возвращает (phone_number, workstation_id, call_time) или None.
    """
    m = re.match(
        r"^stocrm-(incoming|outbound|internal)-(\d+)_(\w+)_(\d{8})-(\d{6})(?:-\w+)?\.(mp3|wav|ogg)$",
        filename,
        re.I,
    )
    if not m:
        return None
    try:
        direction = m.group(1)
        phone = m.group(2)
        ws_id = m.group(3)
        yyyymmdd = m.group(4)
        hhmmss = m.group(5)
        call_time = datetime.strptime(f"{yyyymmdd}{hhmmss}", "%Y%m%d%H%M%S")
        return phone, ws_id, call_time
    except Exception:
        return None


def fetch_call_list(
    domain: str,
    sid: str,
    cutoff_timestamp: int,
    allowed_directions: Optional[List[str]] = None,
    page_limit: int = 200,
    max_pages: int = 20,
    timeout: int = 30,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    Получает список звонков из StoCRM API с пагинацией.

    Args:
        domain: Поддомен StoCRM (например "mycompany")
        sid: API-ключ (SID)
        cutoff_timestamp: Unix timestamp — не возвращать звонки старше этого значения
        allowed_directions: Фильтр направлений ["IN", "OUT"] или None (все)
        page_limit: Кол-во записей на страницу
        max_pages: Максимум страниц
        timeout: Таймаут запроса

    Returns:
        (success, message, list_of_calls)
    """
    base = _base_url(domain)
    endpoint = f"{base}/api/external/v1/calls/get_filtered"

    all_calls: List[Dict[str, Any]] = []
    page = 1

    while page <= max_pages:
        params = {
            "SID": sid,
            "SORT[DATE_CREATE]": "DESC",
            "PAGE": page,
            "LIMIT": page_limit,
        }
        try:
            resp = requests.get(endpoint, params=params, timeout=timeout)
        except requests.exceptions.Timeout:
            return False, "Таймаут запроса к StoCRM API", all_calls
        except requests.exceptions.ConnectionError as e:
            return False, f"Ошибка соединения со StoCRM: {e}", all_calls
        except Exception as e:
            logger.error(f"StoCRM fetch_call_list: {e}", exc_info=True)
            return False, str(e), all_calls

        if resp.status_code == 401:
            return False, "Неверный SID ключ", all_calls
        if resp.status_code == 403:
            return False, "Доступ запрещён. Проверьте SID ключ", all_calls
        if resp.status_code != 200:
            return False, f"Ошибка API StoCRM: {resp.status_code} {resp.text[:200]}", all_calls

        try:
            data = resp.json()
        except Exception:
            return False, f"Не удалось разобрать ответ StoCRM: {resp.text[:300]}", all_calls

        # Ответ может быть как {"RESPONSE": {"DATA": [...]}} так и списком напрямую
        rows = []
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            response_obj = data.get("RESPONSE") or data
            if isinstance(response_obj, dict):
                rows = response_obj.get("DATA") or []
            elif isinstance(response_obj, list):
                rows = response_obj

        if not rows:
            break

        reached_cutoff = False
        for row in rows:
            ts = row.get("TIMESTAMP") or row.get("TIMESTAMP_FRONTEND_TIMESTAMP") or 0
            try:
                ts = int(ts)
            except (TypeError, ValueError):
                ts = 0

            if ts > 0 and ts < cutoff_timestamp:
                reached_cutoff = True
                break

            has_record = str(row.get("HAS_RECORD", "N")).strip().upper()
            if has_record != "Y":
                continue

            dcontext = str(row.get("CALL_DCONTEXT", "")).strip().upper()
            if allowed_directions and dcontext and dcontext not in [d.upper() for d in allowed_directions]:
                continue

            all_calls.append(row)

        if reached_cutoff or len(rows) < page_limit:
            break

        page += 1

    logger.info(f"StoCRM fetch_call_list: домен={domain}, страниц={page}, найдено с записью={len(all_calls)}")
    return True, f"Найдено звонков с записью: {len(all_calls)}", all_calls


def get_record_url(
    domain: str,
    sid: str,
    call_uuid: str,
    timeout: int = 30,
    retries: int = 3,
    retry_delay: int = 15,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Запрашивает ссылку на аудиозапись звонка.

    Эндпоинт: GET /api/external/v1/call/get_record?SID=...&UUID=...

    Returns:
        (url, error_message) — url если успешно, иначе (None, error_message)
    """
    base = _base_url(domain)
    endpoint = f"{base}/api/external/v1/call/get_record"
    params = {"SID": sid, "UUID": call_uuid}

    last_err = None
    for attempt in range(max(1, retries)):
        try:
            resp = requests.get(endpoint, params=params, timeout=timeout)
            ct = (resp.headers.get("Content-Type") or "").lower()

            if resp.status_code == 200:
                if "application/json" in ct:
                    try:
                        jdata = resp.json()
                        url = (
                            jdata.get("url")
                            or jdata.get("URL")
                            or jdata.get("link")
                            or jdata.get("LINK")
                            or jdata.get("record_url")
                        )
                        if url:
                            return str(url).strip(), None
                        last_err = f"JSON-ответ без URL: {str(jdata)[:200]}"
                    except Exception:
                        pass

                # Ответ — просто URL строкой
                body = resp.text.strip()
                if body and (body.startswith("http://") or body.startswith("https://")):
                    return body, None

                if body:
                    last_err = f"Неожиданный ответ get_record: {body[:200]}"
                else:
                    last_err = "Пустой ответ от StoCRM get_record"

            elif resp.status_code == 404:
                last_err = f"Запись звонка {call_uuid} не найдена (404)"
                break
            elif resp.status_code == 401:
                last_err = "Неверный SID ключ (401)"
                break
            else:
                last_err = f"Ошибка StoCRM get_record: {resp.status_code} {resp.text[:200]}"

        except requests.exceptions.Timeout:
            last_err = f"Таймаут запроса get_record (попытка {attempt + 1})"
        except Exception as e:
            last_err = str(e)
            logger.error(f"StoCRM get_record ошибка (попытка {attempt + 1}): {e}", exc_info=True)

        if attempt < retries - 1:
            logger.info(f"StoCRM get_record: повтор через {retry_delay}с ({last_err})")
            time.sleep(retry_delay)

    return None, last_err


def _is_mp3_content(content: bytes) -> bool:
    """Проверяет, похоже ли содержимое на MP3 (ID3 или MPEG frame sync)."""
    if len(content) < 4:
        return False
    return (
        content[:3] == b"ID3"
        or (content[0] == 0xFF and (content[1] & 0xE0) == 0xE0)
    )


def get_record_and_save(
    domain: str,
    sid: str,
    call_uuid: str,
    save_path: Path,
    timeout: int = 60,
    retries: int = 3,
    retry_delay: int = 15,
) -> Tuple[bool, Optional[str]]:
    """
    Получает запись звонка и сохраняет в файл.

    StoCRM API get_record может вернуть:
      - бинарный MP3 (audio/mpeg, application/octet-stream) — сохраняем resp.content напрямую;
      - JSON с полем url/URL/link — скачиваем по ссылке;
      - текст-URL (http/https) — скачиваем по ссылке.

    Returns:
        (success, error_message)
    """
    base = _base_url(domain)
    endpoint = f"{base}/api/external/v1/call/get_record"
    params = {"SID": sid, "UUID": call_uuid}

    last_err = None
    for attempt in range(max(1, retries)):
        try:
            resp = requests.get(endpoint, params=params, timeout=timeout)
            ct = (resp.headers.get("Content-Type") or "").lower()
            content = resp.content

            if resp.status_code == 200:
                # Бинарный аудио: StoCRM возвращает MP3 напрямую
                if (
                    "audio/" in ct
                    or "application/octet-stream" in ct
                    or _is_mp3_content(content)
                ):
                    if len(content) > 100:
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(save_path, "wb") as f:
                            f.write(content)
                        if save_path.exists() and save_path.stat().st_size > 0:
                            logger.info(f"StoCRM get_record: сохранён бинарный MP3 ({len(content)} байт)")
                            return True, None
                    last_err = "Пустой или слишком маленький аудиофайл от StoCRM"
                    continue

                # JSON с URL
                if "application/json" in ct:
                    try:
                        jdata = resp.json()
                        url = (
                            jdata.get("url")
                            or jdata.get("URL")
                            or jdata.get("link")
                            or jdata.get("LINK")
                            or jdata.get("record_url")
                        )
                        if url:
                            if download_recording(str(url).strip(), save_path, timeout=timeout):
                                return True, None
                            last_err = "Ошибка скачивания по URL из JSON"
                            continue
                        last_err = f"JSON без URL: {str(jdata)[:150]}"
                    except Exception as e:
                        last_err = f"Ошибка разбора JSON: {e}"
                    continue

                # Текст-URL
                try:
                    body = content.decode("utf-8", errors="replace").strip()
                    if body and (body.startswith("http://") or body.startswith("https://")):
                        if download_recording(body, save_path, timeout=timeout):
                            return True, None
                        last_err = "Ошибка скачивания по URL"
                        continue
                except Exception:
                    pass

                last_err = "Неожиданный формат ответа get_record (не аудио, не JSON, не URL)"

            elif resp.status_code == 404:
                last_err = f"Запись звонка {call_uuid} не найдена (404)"
                break
            elif resp.status_code == 401:
                last_err = "Неверный SID ключ (401)"
                break
            else:
                try:
                    err_text = content.decode("utf-8", errors="replace")[:200]
                except Exception:
                    err_text = f"код {resp.status_code}"
                last_err = f"Ошибка StoCRM get_record: {resp.status_code} {err_text}"

        except requests.exceptions.Timeout:
            last_err = f"Таймаут запроса get_record (попытка {attempt + 1})"
        except Exception as e:
            last_err = str(e)
            logger.error(f"StoCRM get_record ошибка (попытка {attempt + 1}): {e}", exc_info=True)

        if attempt < retries - 1:
            logger.info(f"StoCRM get_record: повтор через {retry_delay}с ({last_err})")
            time.sleep(retry_delay)

    return False, last_err


def download_recording(url: str, save_path: Path, timeout: int = 120) -> bool:
    """Скачивает аудиозапись по URL и сохраняет в файл."""
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return save_path.exists() and save_path.stat().st_size > 0
    except Exception as e:
        logger.error(f"StoCRM download_recording {url}: {e}", exc_info=True)
        return False


def test_connection(domain: str, sid: str, timeout: int = 15) -> Tuple[bool, str]:
    """
    Проверяет подключение к StoCRM API.
    Делает запрос списка звонков с LIMIT=1 — достаточно для проверки SID.

    Returns:
        (success, message)
    """
    base = _base_url(domain)
    endpoint = f"{base}/api/external/v1/calls/get_filtered"
    params = {"SID": sid, "LIMIT": 1, "PAGE": 1}
    try:
        resp = requests.get(endpoint, params=params, timeout=timeout)
        if resp.status_code == 200:
            return True, "Подключение успешно"
        if resp.status_code == 401:
            return False, "Неверный SID ключ (401)"
        if resp.status_code == 403:
            return False, "Доступ запрещён (403). Проверьте SID и домен"
        if resp.status_code == 404:
            return False, f"Домен {domain}.stocrm.ru не найден (404). Проверьте поддомен"
        return False, f"Ошибка API: {resp.status_code} {resp.text[:200]}"
    except requests.exceptions.Timeout:
        return False, "Таймаут соединения. Проверьте домен и сеть"
    except requests.exceptions.ConnectionError as e:
        return False, f"Ошибка соединения: {e}"
    except Exception as e:
        logger.error(f"StoCRM test_connection: {e}", exc_info=True)
        return False, str(e)
