# call_analyzer/utils.py

import time
import logging
import requests
import traceback
import datetime
import re
import os
import yaml
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def ensure_telegram_ready(action_description):
    token = (config.TELEGRAM_BOT_TOKEN or '').strip()
    if not token:
        logger.warning("[%s] Telegram не настроен: %s. Укажите токен бота в кабинете.",
                       config.PROFILE_LABEL, action_description)
        return False
    return True


def wait_for_file(file_path, retries=5, delay=2):
    """
    Ждём, пока файл не будет доступен (на случай, если он ещё пишется).
    """
    for attempt in range(retries):
        try:
            with open(file_path, 'rb'):
                return True
        except (PermissionError, FileNotFoundError):
            logger.info(f"Файл {file_path} недоступен. Попытка {attempt+1}/{retries}, ждем {delay} сек.")
            time.sleep(delay)
    return False


def make_request_with_retries(request_func, max_retries=3, delay=5, *args, **kwargs):
    """
    Универсальная обёртка для повторных попыток HTTP-запроса.
    request_func - функция (requests.post / requests.get / и т.д.)
    """
    for attempt in range(max_retries):
        try:
            response = request_func(*args, **kwargs)
            response.raise_for_status()
            return response
        except Exception as e:
            logger.error(f"Ошибка при запросе: {e}. Попытка {attempt+1}/{max_retries}.")
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                return None


def notify_on_error(raise_exception=False):
    """
    Декоратор, который логирует и отправляет alert при ошибках.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_message = f"Ошибка в функции {func.__name__}: {e}\n{traceback.format_exc()}"
                logger.error(error_message)
                send_alert(error_message)
                if raise_exception:
                    raise
        return wrapper
    return decorator


def send_alert(message, filename=None, chat_id=None, reply_to_message_id=None):
    """
    Отправляет критическое сообщение в Telegram.
    Если параметр chat_id не передан, используется config.ALERT_CHAT_ID.
    Поддерживает ответ на сообщение через reply_to_message_id.
    """
    event_time = time.strftime("%Y-%m-%d %H:%M:%S")
    alert_message = f"{message}"
    if filename:
        alert_message += f"\nФайл: {filename}"

    if chat_id is None:
        chat_id = config.ALERT_CHAT_ID

    if not ensure_telegram_ready("отправка сервисного уведомления"):
        return None
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": alert_message
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    try:
        resp = requests.post(url, data=payload)
        if resp.status_code == 200:
            logger.info("Alert отправлен в Телеграм.")

            return resp.json().get("result", {}).get("message_id")  # Возвращаем message_id
        else:
            logger.error(f"Не удалось отправить alert: {resp.status_code}, {resp.text}")
    except Exception as e:
        logger.error(f"Ошибка при отправке alert: {e}")



def send_station_message(chat_id, message, file_path=None):
    """
    Отправляет сообщение (и/или файл) в указанный Telegram-чат.
    """
    if not chat_id:
        logger.warning("Пустой chat_id, сообщение не отправлено.")
        return

    if file_path:
        _send_file_telegram(chat_id, message, file_path)
    else:
        _send_text_telegram(chat_id, message)


def _send_text_telegram(chat_id, text):
    if not ensure_telegram_ready("отправка текста в Telegram"):
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(url, data=payload, timeout=15)
        if resp.status_code == 200:
            logger.info(f"Сообщение отправлено в чат {chat_id}")
        else:
            logger.error(f"Ошибка при отправке текста в чат {chat_id}: {resp.status_code}, {resp.text}")
    except Exception as e:
        logger.error(f"Исключение при отправке сообщения в чат {chat_id}: {e}")


def parse_filename(file_name: str):
    """
    Возвращает кортеж (phone_number, station_code, call_datetime),
    независимо от того, входящий или исходящий звонок.
    Поддерживает форматы из конфигурации FILENAME_FORMATS.
    """
    def _try_custom_patterns():
        """Пробуем пользовательские паттерны, если включены. Ожидается порядок групп: phone, station, datetime."""
        try:
            filename_cfg = getattr(config, "PROFILE_SETTINGS", {}).get('filename') or {}
            if not filename_cfg.get('enabled'):
                return None
            patterns = filename_cfg.get('patterns') or []
            dt_default = config.FILENAME_PATTERNS.get('datetime_format')
            for idx, pattern in enumerate(patterns):
                regex = pattern.get('regex')
                if not regex:
                    continue
                
                # Если в сохраненном regex есть [^\\._-]+, он может обрезать дату на первом дефисе.
                # Исправляем это на лету, если нужно, или просто используем как есть.
                match = re.match(regex, file_name, re.IGNORECASE)
                if not match:
                    continue
                
                # Пробуем получить данные по именам групп (если они есть) или по порядку (1-3)
                group_dict = match.groupdict()
                phone = group_dict.get('phone') or (match.group(1) if match.lastindex and match.lastindex >= 1 else None)
                station = group_dict.get('station') or (match.group(2) if match.lastindex and match.lastindex >= 2 else None)
                dt_str = group_dict.get('datetime') or (match.group(3) if match.lastindex and match.lastindex >= 3 else None)
                
                phone = normalize_phone_number(phone) if phone else phone
                call_time = None
                dt_fmt = pattern.get('datetime_format') or dt_default
                if dt_str and dt_fmt:
                    try:
                        # Удаляем лишние символы из строки даты, если они попали (например, расширение)
                        # Но лучше полагаться на точный regex
                        call_time = datetime.datetime.strptime(dt_str, dt_fmt)
                    except Exception:
                        # Попробуем отрезать всё после последнего разделителя, если формат не совпал
                        # (иногда в группу попадает лишнее из-за жадного regex)
                        logger.debug("Ошибка парсинга даты '%s' форматом '%s'", dt_str, dt_fmt)
                        call_time = None
                
                if phone or station:
                    return phone, station, call_time
        except Exception:
            logger.debug("Не удалось применить пользовательские паттерны для %s", file_name, exc_info=True)
        return None

    filename_cfg = getattr(config, "PROFILE_SETTINGS", {}).get('filename') or {}
    custom_enabled = bool(filename_cfg.get('enabled', False))

    custom_match = _try_custom_patterns()
    if custom_match:
        return custom_match
    
    # Если включены свои правила, но ничего не подошло — ПРЕКРАЩАЕМ поиск.
    # Это предотвращает "подтягивание из общего формата".
    if custom_enabled:
        logger.debug("Файл %s не подошел под кастомные шаблоны, общий поиск пропущен.", file_name)
        return None, None, None

    # Поддержка нового формата с направлением:
    # вход_EkbFocusMal128801_с_79536098664_на_73432260822_от_2025_10_20
    m = re.match(config.FILENAME_PATTERNS['direction_pattern'], file_name, re.IGNORECASE)
    if m:
        try:
            station_name = m.group(1)  # EkbFocusMal
            station_code = m.group(2)  # 128801
            from_phone = m.group(3)    # 79536098664
            to_phone = m.group(4)       # 73432260822
            year = m.group(5)           # 2025
            month = m.group(6)          # 10
            day = m.group(7)            # 20
            
            # Создаем дату (время устанавливаем в 00:00:00)
            call_time = datetime.datetime(int(year), int(month), int(day), 0, 0, 0)
            
            # Если в имени файла нет времени, используем время создания файла
            # Это поможет определить реальное время звонка
            try:
                import os
                file_path = os.path.join(os.getcwd(), file_name)
                if os.path.exists(file_path):
                    file_stat = os.stat(file_path)
                    file_time = datetime.datetime.fromtimestamp(file_stat.st_mtime)
                    # Используем время создания файла, но сохраняем дату из имени файла
                    call_time = datetime.datetime(int(year), int(month), int(day), 
                                                file_time.hour, file_time.minute, file_time.second)
            except Exception:
                # Если не удалось получить время создания файла, оставляем 00:00:00
                pass
            
            # Нормализуем номера телефонов
            from_phone = normalize_phone_number(from_phone)
            to_phone = normalize_phone_number(to_phone)
            
            # Возвращаем номер отправителя как основной номер телефона
            return from_phone, station_code, call_time
        except Exception:
            # Падать не будем — попробуем другие форматы ниже
            pass

    # Поддержка формата с дефисами из конфигурации:
    # - external-<station>-<phone>-<YYYYMMDD>-<HHMMSS>-...
    m = re.match(config.FILENAME_PATTERNS['external_pattern'], file_name, re.IGNORECASE)
    if m:
        try:
            station_code = m.group(1)
            phone_number = m.group(2)
            yyyymmdd = m.group(3)
            hhmmss = m.group(4)
            dt_str = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}-{hhmmss[:2]}-{hhmmss[2:4]}-{hhmmss[4:6]}"
            call_time = datetime.datetime.strptime(dt_str, config.FILENAME_PATTERNS['datetime_format'])
            phone_number = normalize_phone_number(phone_number)
            return phone_number, station_code, call_time
        except Exception:
            # Падать не будем — попробуем общий формат ниже
            pass

    # Поддержка формата out-* (исходящие FTP):
    # out-<phone>-<station>-<YYYYMMDD>-<HHMMSS>-...
    m = re.match(config.FILENAME_PATTERNS['out_pattern'], file_name, re.IGNORECASE)
    if m:
        try:
            phone_number = m.group(1)
            station_code = m.group(2)
            yyyymmdd = m.group(3)
            hhmmss = m.group(4)
            dt_str = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}-{hhmmss[:2]}-{hhmmss[2:4]}-{hhmmss[4:6]}"
            call_time = datetime.datetime.strptime(dt_str, config.FILENAME_PATTERNS['datetime_format'])
            phone_number = normalize_phone_number(phone_number)
            return phone_number, station_code, call_time
        except Exception:
            pass

    parts = file_name.split("_")
    
    # Поддержка старого формата с префиксом fs_ (для обратной совместимости)
    if file_name.startswith("fs_") and len(parts) >= 4:
        # Старый формат: fs_[phone/station]_[station/phone]_[datetime]_...
        first_id = parts[1]  # может быть либо телефон, либо станция
        second_id = parts[2]  # может быть либо телефон, либо станция
        date_str = parts[3]  # "2025-03-03-16-19-42"
    elif len(parts) >= 3:
        # Новый формат без префикса: [phone/station]_[station/phone]_[datetime]_...
        first_id = parts[0]  # может быть либо телефон, либо станция
        second_id = parts[1]  # может быть либо телефон, либо станция
        date_str = parts[2]  # "2025-03-03-16-19-42"
    else:
        return None, None, None  # невалидное имя файла

    station_code = None
    phone_number = None

    # Улучшенная логика определения формата
    # Сначала проверяем, является ли first_id известным кодом станции
    
    # Проверяем, является ли first_id известным кодом станции
    if first_id in config.STATION_NAMES or first_id in config.STATION_MAPPING:
        # Формат: [station_code]_[phone_number]_[datetime]_...
        station_code = first_id
        phone_number = second_id
    elif second_id in config.STATION_NAMES or second_id in config.STATION_MAPPING:
        # Формат: [phone_number]_[station_code]_[datetime]_...
        phone_number = first_id
        station_code = second_id
    else:
        # Fallback: используем старую логику по длине
        if len(first_id) == 4 and first_id.isdigit():
            station_code = first_id
            phone_number = second_id
        else:
            phone_number = first_id
            station_code = second_id

    # Дату парсим используя формат из конфигурации
    try:
        call_time = datetime.datetime.strptime(date_str, config.FILENAME_PATTERNS['datetime_format'])
    except ValueError:
        # Не получилось распарсить?
        call_time = None

    # При желании нормализуем телефон (+7 -> 8)
    phone_number = normalize_phone_number(phone_number)
    return phone_number, station_code, call_time


def is_valid_call_filename(filename: str) -> bool:
    """
    Проверяет, является ли файл валидным файлом звонка.
    Поддерживает форматы: fs_*, [phone/station]_[station/phone]_[date]_..., external-*, вход_*
    """
    name_lower = filename.lower()

    filename_cfg = getattr(config, "PROFILE_SETTINGS", {}).get('filename') or {}
    custom_enabled = bool(filename_cfg.get('enabled', False))
    custom_patterns = filename_cfg.get('patterns') or []

    extensions = filename_cfg.get('extensions') or config.FILENAME_PATTERNS.get('supported_extensions', ['.mp3', '.wav'])
    if extensions:
        if not any(name_lower.endswith(ext.lower()) for ext in extensions):
            return False

    # Если включены пользовательские правила, считаем валидными ТОЛЬКО их
    if custom_enabled:
        if not custom_patterns:
            return False
        for pattern in custom_patterns:
            regex = pattern.get('regex')
            if not regex:
                continue
            if re.match(regex, filename, re.IGNORECASE):
                return True
        # Ни один кастомный паттерн не подошёл
        return False

    # Кастомные правила выключены — используем стандартную логику
    # Проверяем известные префиксы
    if (
        name_lower.startswith("fs_")
        or name_lower.startswith("external-")
        or name_lower.startswith("вход_")
    ):
        return True

    # Проверяем новый формат без префикса: [phone/station]_[station/phone]_[date]_...
    # Используем паттерн из конфигурации
    if re.match(config.FILENAME_PATTERNS['fs_pattern'], filename, re.IGNORECASE):
        return True

    return False


def normalize_phone_number(num: str) -> str:
    num = num.strip()
    if num.startswith('8'):
        return "+7" + num[1:]
    elif num.startswith('7') and len(num) == 11:
        return "+" + num
    elif num.startswith('+7'):
        return num
    else:
        return num


def _send_file_telegram(chat_id, caption, file_path):
    if not ensure_telegram_ready("отправка документа в Telegram"):
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            files = {"document": f}
            data = {"chat_id": chat_id, "caption": caption}
            resp = requests.post(url, files=files, data=data, timeout=30)
        if resp.status_code == 200:
            logger.info(f"Файл {file_path} отправлен в чат {chat_id}")
        else:
            logger.error(f"Ошибка при отправке файла в чат {chat_id}: {resp.status_code}, {resp.text}")
    except Exception as e:
        logger.error(f"Исключение при отправке файла в чат {chat_id}: {e}")


def get_call_format(file_name: str):
    """
    Определяет формат звонка по имени файла.
    Возвращает 'incoming' для входящих звонков, 'outgoing' для исходящих звонков,
    или 'direction_format' для нового формата с направлением.
    """
    # 1. Проверяем пользовательские паттерны (наивысший приоритет)
    filename_cfg = getattr(config, "PROFILE_SETTINGS", {}).get('filename') or {}
    if filename_cfg.get('enabled'):
        patterns = filename_cfg.get('patterns') or []
        for pattern in patterns:
            regex = pattern.get('regex')
            if regex and re.match(regex, file_name, re.IGNORECASE):
                direction = pattern.get('direction', 'auto')
                if direction in ['incoming', 'outgoing']:
                    return direction
                # Если 'auto', продолжаем к стандартной логике ниже

    # 2. Проверяем новый формат с направлением
    if re.match(config.FILENAME_PATTERNS['direction_pattern'], file_name, re.IGNORECASE):
        return 'direction_format'
    
    parts = file_name.split("_")
    if len(parts) < 3:
        # Если не разделилось подчеркиванием, пробуем дефис (для out- форматов)
        parts = file_name.split("-")
        if len(parts) < 3:
            return 'incoming'  # Fallback

    first_id = parts[0]  # может быть либо телефон, либо станция
    second_id = parts[1]  # может быть либо телефон, либо станция
    
    # Спец-обработка для префикса out-
    if file_name.lower().startswith('out-'):
        return 'outgoing'

    # Проверяем, является ли first_id известным кодом станции
    if first_id in config.STATION_NAMES or first_id in config.STATION_MAPPING:
        # Формат: [station_code]_[phone_number]_[datetime]_... (исходящий)
        return 'outgoing'
    elif second_id in config.STATION_NAMES or second_id in config.STATION_MAPPING:
        # Формат: [phone_number]_[station_code]_[datetime]_... (входящий)
        return 'incoming'
    else:
        # Fallback: используем логику по длине
        if len(first_id) == 4 and first_id.isdigit():
            # Формат: [station_code]_[phone_number]_[datetime]_... (исходящий)
            return 'outgoing'
        else:
            # Формат: [phone_number]_[station_code]_[datetime]_... (входящий)
            return 'incoming'


def save_transcript_for_analytics(transcript_text: str, phone_number: str, station_code: str, call_time: datetime, original_filename: str = None) -> Path:
    """
    Сохраняет транскрипцию в новом формате для системы аналитики.
    Сохраняет в том же формате, что и исходный файл звонка.
    """
    today_subdir = call_time.strftime("%Y/%m/%d")
    transcript_dir = config.BASE_RECORDS_PATH / today_subdir / "transcript"
    os.makedirs(transcript_dir, exist_ok=True)
    
    # Определяем формат исходного файла
    if original_filename:
        call_format = get_call_format(original_filename)
    else:
        call_format = 'incoming'  # по умолчанию входящий формат
    
    # Формируем имя файла в том же формате, что и исходный
    phone_clean = phone_number.lstrip('+')
    timestamp = call_time.strftime("%Y-%m-%d-%H-%M-%S")
    
    if call_format == 'outgoing':
        # Формат исходящих: {station_code}_{phone_number}_{timestamp}
        filename = f"{station_code}_{phone_clean}_{timestamp}.txt"
    else:
        # Формат входящих: {phone_number}_{station_code}_{timestamp}
        filename = f"{phone_clean}_{station_code}_{timestamp}.txt"
    
    result_file = transcript_dir / filename

    if result_file.exists():
        logger.info(f"Файл транскрипции для аналитики уже существует: {result_file}")
        return result_file
    
    try:
        with result_file.open("w", encoding="utf-8") as f:
            f.write(transcript_text)
        logger.info(f"Транскрипция для аналитики сохранена: {result_file}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении транскрипции для аналитики {result_file}: {e}")
    return result_file
