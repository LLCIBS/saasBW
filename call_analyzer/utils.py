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

    # Поддержка форматов с дефисами из конфигурации:
    # - external-<station>-<phone>-<YYYYMMDD>-<HHMMSS>-...
    # - in-<station>-<phone>-<YYYYMMDD>-<HHMMSS>-...
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

    parts = file_name.split("_")
    if len(parts) < 4:
        return None, None, None  # невалидное имя файла

    # parts[0] = "fs"
    first_id = parts[1]  # может быть либо телефон, либо станция
    second_id = parts[2]  # может быть либо телефон, либо станция
    date_str = parts[3]  # "2025-03-03-16-19-42"

    station_code = None
    phone_number = None

    # Улучшенная логика определения формата
    # Сначала проверяем, является ли first_id известным кодом станции
    
    # Проверяем, является ли first_id известным кодом станции
    if first_id in config.STATION_NAMES or first_id in config.STATION_MAPPING:
        # Формат: fs_[station_code]_[phone_number]_[datetime]_...
        station_code = first_id
        phone_number = second_id
    elif second_id in config.STATION_NAMES or second_id in config.STATION_MAPPING:
        # Формат: fs_[phone_number]_[station_code]_[datetime]_...
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
    # Проверяем новый формат с направлением
    if re.match(config.FILENAME_PATTERNS['direction_pattern'], file_name, re.IGNORECASE):
        return 'direction_format'
    
    parts = file_name.split("_")
    if len(parts) < 4:
        return None

    first_id = parts[1]  # может быть либо телефон, либо станция
    second_id = parts[2]  # может быть либо телефон, либо станция

    # Проверяем, является ли first_id известным кодом станции
    if first_id in config.STATION_NAMES or first_id in config.STATION_MAPPING:
        # Формат: fs_[station_code]_[phone_number]_[datetime]_... (исходящий)
        return 'outgoing'
    elif second_id in config.STATION_NAMES or second_id in config.STATION_MAPPING:
        # Формат: fs_[phone_number]_[station_code]_[datetime]_... (входящий)
        return 'incoming'
    else:
        # Fallback: используем логику по длине
        if len(first_id) == 4 and first_id.isdigit():
            # Формат: fs_[station_code]_[phone_number]_[datetime]_... (исходящий)
            return 'outgoing'
        else:
            # Формат: fs_[phone_number]_[station_code]_[datetime]_... (входящий)
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
        # Формат исходящих: fs_{station_code}_{phone_number}_{timestamp}
        filename = f"fs_{station_code}_{phone_clean}_{timestamp}.txt"
    else:
        # Формат входящих: fs_{phone_number}_{station_code}_{timestamp}
        filename = f"fs_{phone_clean}_{station_code}_{timestamp}.txt"
    
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


def is_legal_entity_call(transcript_text: str) -> bool:
    """
    Определяет, является ли звонок от юридического лица по AI-анализу контекста.
    
    Args:
        transcript_text (str): Текст транскрипции звонка
        
    # Поддержка формата: in-<station>-<phone>-<YYYYMMDD>-<HHMMSS>-...
    # Пример: in-9623217779-+79033227159-20251007-110801-1759824481.3355.wav
    if file_name.lower().startswith("in-"):
        in_parts = file_name.split("-")
        # Ожидаем минимум: [in, station, phone, yyyymmdd, hhmmss, ...]
        if len(in_parts) >= 5:
            try:
                station_code = in_parts[1]
                phone_number = in_parts[2]
                yyyymmdd = in_parts[3]
                hhmmss = in_parts[4]
                dt_str = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}-{hhmmss[:2]}-{hhmmss[2:4]}-{hhmmss[4:6]}"
                call_time = datetime.datetime.strptime(dt_str, "%Y-%m-%d-%H-%M-%S")
                phone_number = normalize_phone_number(phone_number)
                return phone_number, station_code, call_time
            except Exception:
                pass

    Returns:
        bool: True если звонок от юридического лица, False иначе
    """
    if not transcript_text:
        return False
    
    # Сначала быстрая проверка по ключевым словам
    text_lower = transcript_text.lower()
    
    # Проверяем исключающие фразы
    exclusion_phrases = [
        "позвоните компании", "обратитесь в компанию", "рекомендую компанию",
        "там есть компания", "есть компания", "другая компания",
        "много организаций", "есть организации", "другие организации",
        "попробуйте позвонить компании", "звоните компании"
    ]
    
    for phrase in exclusion_phrases:
        if phrase in text_lower:
            logger.info(f"Найдена исключающая фраза '{phrase}' - НЕ звонок от юр. лица")
            return False
    
    # Если есть ключевые слова, делаем AI-анализ
    keywords_found = False
    for keyword in config.LEGAL_ENTITY_KEYWORDS:
        if keyword.lower() in text_lower:
            keywords_found = True
            break
    
    if not keywords_found:
        return False
    
    # AI-анализ контекста
    try:
        legal_entity_prompt = load_legal_entity_prompt()
        if legal_entity_prompt:
            ai_result = thebai_analyze_legal_entity(transcript_text, legal_entity_prompt)
            if "[ТИП_КЛИЕНТА:ЮРИДИЧЕСКОЕ_ЛИЦО]" in ai_result:
                logger.info(f"AI определил звонок как от юридического лица: {ai_result[:100]}...")
                return True
            elif "[ТИП_КЛИЕНТА:ЧАСТНОЕ_ЛИЦО]" in ai_result:
                logger.info(f"AI определил звонок как от частного лица: {ai_result[:100]}...")
                return False
            else:
                logger.warning(f"AI не смог определить тип клиента: {ai_result}")
                # Fallback к простой проверке ключевых слов
                return simple_keyword_check(transcript_text)
        else:
            logger.warning("Не удалось загрузить промпт для AI-анализа")
            return simple_keyword_check(transcript_text)
    except Exception as e:
        logger.error(f"Ошибка AI-анализа: {e}")
        # Fallback к простой проверке ключевых слов
        return simple_keyword_check(transcript_text)


def send_legal_entity_notification(phone_number: str, station_code: str, call_time: datetime, 
                                 transcript_text: str, analysis_text: str, filename: str):
    """
    Отправляет уведомление о звонке от юридического лица в специальный Telegram чат.
    
    Args:
        phone_number (str): Номер телефона клиента
        station_code (str): Код станции
        call_time (datetime): Время звонка
        transcript_text (str): Текст транскрипции
        analysis_text (str): Результат анализа
        filename (str): Имя файла звонка
    """
    try:
        station_name = config.STATION_NAMES.get(station_code, station_code)
        formatted_time = call_time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Формируем сообщение
        message = (
            f"🏢 <b>Звонок от юридического лица</b>\n\n"
            f"📞 <b>Номер:</b> {phone_number}\n"
            f"🏪 <b>Станция:</b> {station_name} ({station_code})\n"
            f"🕐 <b>Время:</b> {formatted_time}\n"
            f"📄 <b>Файл:</b> {filename}\n\n"
            f"<b>Результат анализа:</b>\n{analysis_text}\n\n"
            f"<b>Транскрипция:</b>\n{transcript_text[:500]}{'...' if len(transcript_text) > 500 else ''}"
        )
        
        # Отправляем в специальный чат для юридических лиц
        send_alert(message, chat_id=config.LEGAL_ENTITY_CHAT_ID)
        logger.info(f"Уведомление о звонке от юр. лица отправлено в чат {config.LEGAL_ENTITY_CHAT_ID}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления о звонке от юр. лица: {e}")


def load_legal_entity_prompt() -> str:
    """Загружает промпт для определения типа клиента"""
    try:
        prompt_path = Path(__file__).parent / "legal_entity_prompt.yaml"
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("legal_entity_prompt", "")
        return ""
    except Exception as e:
        logger.error(f"Ошибка загрузки промпта: {e}")
        return ""


def simple_keyword_check(transcript_text: str) -> bool:
    """Простая проверка по ключевым словам (fallback)"""
    text_lower = transcript_text.lower()
    
    for keyword in config.LEGAL_ENTITY_KEYWORDS:
        if keyword.lower() in ["ип"]:
            if re.search(r'\b' + re.escape(keyword.lower()) + r'\b', text_lower):
                return True
        else:
            if keyword.lower() in text_lower:
                return True
    return False


def thebai_analyze_legal_entity(transcript: str, prompt: str) -> str:
    """
    Отправляем запрос к TheB.ai для анализа типа клиента
    """
    if not transcript.strip():
        return "Пустой транскрипт, нет анализа."

    payload = {
        "model": config.THEBAI_MODEL,
        "messages": [{"role": "user", "content": f"{prompt}\n\nВот диалог:\n{transcript}"}],
    }
    headers = {
        "Authorization": f"Bearer {config.THEBAI_API_KEY}",
        "Content-Type": "application/json"
    }

    def _request():
        return requests.post(config.THEBAI_URL, headers=headers, json=payload, timeout=60)

    resp = make_request_with_retries(_request, max_retries=2, delay=5)
    if not resp or resp.status_code != 200:
        logger.error(f"TheB.ai анализ типа клиента ошибка: {resp.status_code if resp else 'No resp'}, {resp.text if resp else ''}")
        return "Ошибка анализа"

    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Ошибка парсинга ответа TheB.ai для типа клиента: {e}")
        return "Ошибка анализа"
