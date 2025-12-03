import logging
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import re

import yaml
import threading

import config

try:
    from call_analyzer.utils import send_alert, normalize_phone_number  # type: ignore
    # services.py больше не используется, так как transcription_service заменен на internal_transcription
except ImportError:
    from utils import send_alert, normalize_phone_number
# Импорты удалены - функционал ReTruck больше не используется

logger = logging.getLogger(__name__)

# Файл, где хранятся данные переводов — используем файл в корне проекта
PROJECT_ROOT = Path(__file__).parents[2]


def _resolve_transfer_store_path() -> str:
    """
    Возвращает путь к JSON с кейсами переводов в пределах пользовательского BASE_RECORDS_PATH.
    Это гарантирует изоляцию данных между арендаторами.
    """
    base_path = Path(str(config.BASE_RECORDS_PATH))
    runtime_dir = base_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return str((runtime_dir / "transfer_cases.json").resolve())

# Маппинг станций (для дополнительной логики, если потребуется)
STATION_MAPPING = {
    '9308': ['4110', '4111'],
    '9304': ['4100', '4101'],
    '9302': ['4155', '4156'],
    '9307': ['4150', '5151'],
    '9327': ['4210', '4211'],
    '9300': ['4222', '4221'],
    '9326': ['4160'],
    '9324': ['4240'],
    '9321': ['4200', '4201'],
    '9322': ['4231', '4230'],
    '9325': ['4217'],
    '9316': ['4170', '4172'],
    '9319': ['4181', '4180'],
    '9301': ['4140', '4141'],
    '9347': ['4254', '4255']
}

# --- Special Time Map for parsing human-friendly time phrases ---
SPECIAL_TIME_MAP = {
    "утро": 9,     # 09:00
    "день": 13,    # 13:00
    "вторая половина дня": 15,  # 15:00
    "вечер": 18,   # 18:00
    "ночь": 22     # 22:00
}

def parse_special_time(phrase, now=None):

    from datetime import datetime, timedelta
    now = now or datetime.now()
    phrase = phrase.lower().strip()
    # 1. "завтра утром", "сегодня вечером" и т.п.
    m = re.match(r'(сегодня|завтра|послезавтра)? ?(утро|день|вечер|ночь|вторая половина дня)?', phrase)
    if m:
        day_word, part = m.groups()
        if day_word == "сегодня":
            base = now
        elif day_word == "завтра":
            base = now + timedelta(days=1)
        elif day_word == "послезавтра":
            base = now + timedelta(days=2)
        else:
            base = now
        hour = SPECIAL_TIME_MAP.get(part, 9)
        dt = base.replace(hour=hour, minute=0, second=0, microsecond=0)
        if dt < now:
            dt += timedelta(days=1)
        return dt
    # 2. "через N часов"
    m = re.match(r'через (\d+) час', phrase)
    if m:
        hours = int(m.group(1))
        return now + timedelta(hours=hours)
    # 3. "во второй половине дня"
    if "вторая половина дня" in phrase:
        dt = now.replace(hour=15, minute=0, second=0, microsecond=0)
        if dt < now:
            dt += timedelta(days=1)
        return dt
    # 4. Попробовать через dateparser как fallback
    try:
        import dateparser
        dt = dateparser.parse(phrase, settings={'RELATIVE_BASE': now})
        if dt:
            return dt
    except ImportError:
        pass
    return None

# --- Example usage: ---
# dt = parse_special_time("завтра утром")
# print(dt)

# SPECIAL_TIME_MAP можно свободно расширять и изменять прямо в этом файле или вынести в отдельный конфиг.

# Глобальный список ожидающих переводов
pending_transfers = []

def load_transfer_cases():
    """
    �-���?�?�?�?����'? �?����?�?�� �?�?����?����?�<�: ����?��?�?�?�?�? ��� JSON-�"�����>��.
    """
    global pending_transfers
    data_file = _resolve_transfer_store_path()
    if not os.path.exists(data_file):
        logger.info("[transfer_tracker] �������> �? �?�?����?���?��?�?�� ����?��?�?�?�?�? �?�� �?�����?��?, �?���ؐ�?����? �? ���?�?�'�?�?�? �?����?���.")
        pending_transfers = []
        return
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for rec in data:
                rec['call_time'] = datetime.fromisoformat(rec['call_time'])
                rec['deadline'] = datetime.fromisoformat(rec['deadline'])
            pending_transfers = data
            logger.info(f"[transfer_tracker] �-���?�?�?�?���?�? {len(pending_transfers)} ����?��?�?�?�?�? ��� {data_file}")
    except Exception as e:
        logger.error(f"[transfer_tracker] �?�?��+��� ���?�� �����?�?�?����� {data_file}: {e}")
        pending_transfers = []

def save_transfer_cases():
    """
    ���?�:�?���?�?��' �?����?�?�� �?�?����?����?�<�: ����?��?�?�?�?�? �? JSON-�"�����>, ���?��?�+�?�����?�? datetime �? ISO-�"�?�?�?���',
    �� �?�'���?���?�>�?��' �?�?��?�?�?�>��?��� �?�? �?�?�?�?��?�� ���? ����?��?�?�?���?.
    """
    data_file = _resolve_transfer_store_path()
    try:
        data = []
        for rec in pending_transfers:
            new_rec = dict(rec)
            new_rec['call_time'] = rec['call_time'].isoformat()
            new_rec['deadline'] = rec['deadline'].isoformat()
            data.append(new_rec)
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[transfer_tracker] ���?�:�?���?��?�? {len(data)} ����?��?�?�?�?�? �? {data_file}")
        notify_transfer_change()
    except Exception as e:
        logger.error(f"[transfer_tracker] �?�?��+��� ���?�� �?�?�:�?���?��?��� {data_file}: {e}")

def notify_transfer_change():
    """
    Отправляет в Telegram уведомление со сводкой по переводам.
    """
    try:
        total = len(pending_transfers)
        waiting = sum(1 for rec in pending_transfers if rec['status'] == 'waiting')
        completed = sum(1 for rec in pending_transfers if rec['status'] == 'completed')
        failed = sum(1 for rec in pending_transfers if rec['status'] == 'failed')
        cycled = sum(1 for rec in pending_transfers if rec['status'] == 'cycled')
        msg = (
            f"Обновлены данные переводов (transfer_cases.json):\n"
            f"Всего: {total}\n"
            f"Ожидающих: {waiting}\n"
            f"Завершенных: {completed}\n"
            f"Не состоявшихся: {failed}\n"
            f"Цикличных: {cycled}"
        )
        send_alert(msg)
    except Exception as e:
        logger.error(f"[transfer_tracker] Ошибка при отправке уведомления: {e}")

def get_station_name(station_code: str) -> str:
    """
    Возвращает название станции по коду.
    Если station_code есть напрямую в config.STATION_NAMES, возвращает его.
    Иначе, ищет в STATION_MAPPING родительский код,
    и если найден, возвращает название для родительского кода из config.STATION_NAMES.
    Если ни то, ни другое не найдено, возвращает сам station_code.
    """
    # Сначала попробуем прямой поиск
    if station_code in config.STATION_NAMES:
        return config.STATION_NAMES[station_code]
    # Ищем родительский код в STATION_MAPPING
    for parent_code, child_codes in STATION_MAPPING.items():
        if station_code in child_codes:
            return config.STATION_NAMES.get(parent_code, station_code)
    return station_code


def notify_transfer_started(transfer_record: dict):
    """
    Отправляет уведомление о том, что клиент позвонил и теперь ждёт перевода.
    """
    channel = config.TG_CHANNEL_NIZH if transfer_record["incoming_station"] in config.NIZH_STATION_CODES else config.TG_CHANNEL_OTHER

    msg = (
        f"[Перевод] Новый кейс: {transfer_record['phone_number']}\n"
        f"Станция: {get_station_name(transfer_record['incoming_station'])}"
    )
    if transfer_record.get("transfer_station"):
        msg += f"\nПеревести на: {transfer_record['transfer_station']}"
    if transfer_record.get("transfer_conditions"):
        msg += f"\nУсловия: {transfer_record['transfer_conditions']}"
    #if transfer_record.get("analysis"):
    #    msg += f"\nАнализ: {transfer_record['analysis']}"

    send_alert(msg, chat_id=channel)

    logger.info(f"Уведомление о начале перевода отправлено для {transfer_record['phone_number']}.")

def notify_transfer_completed(transfer_record: dict, complete_station: str):
    """
    Отправляет уведомление о том, что с клиентом успешно связались (перевод завершён).
    В уведомлении указывается исходная станция и станция, с которой поступил закрывающий звонок.
    """
    original_station_name = get_station_name(transfer_record["incoming_station"])
    complete_station_name = get_station_name(complete_station)
    channel = config.TG_CHANNEL_NIZH if complete_station in config.NIZH_STATION_CODES else config.TG_CHANNEL_OTHER
    msg = (
        f"Перевод завершён: с клиентом {transfer_record['phone_number']} успешно связались.\n"
        f"Исходная станция: {original_station_name}.\n"
        f"Клиенту перезвонили со станции: {complete_station_name} (вызов: {transfer_record['call_time'].strftime('%H:%M')})."
    )
    send_alert(msg, chat_id=channel)
    logger.info(f"Уведомление о завершённом переводе отправлено для {transfer_record['phone_number']} в канал {channel}.")

def add_transfer_case(phone_number: str, incoming_station: str, call_time: datetime, station: str = None, conditions: str = None, analysis: str = None, when: str = None):
    """
    Добавляет новую запись перевода со статусом 'waiting' и дедлайном через 2 часа.
    Если задано when (например, "завтра утром") — вычисляет remind_at и добавляет notified=False.
    Сразу отправляет уведомление о начале ожидания перевода.
    """
    record = {
        "phone_number": phone_number,
        "incoming_station": incoming_station,
        "call_time": call_time,
        "deadline": call_time + timedelta(hours=2),
        "status": "waiting",
        "transfer_station": station,
        "transfer_conditions": conditions,
        "analysis": analysis
    }
    if when:
        record["transfer_when"] = when
        remind_at = parse_special_time(when, now=call_time)
        if remind_at:
            record["remind_at"] = remind_at.isoformat()
            record["notified"] = False
    pending_transfers.append(record)
    logger.info(f"[transfer_tracker] Добавлен перевод (deadline=2 часа): {record}")
    save_transfer_cases()
    notify_transfer_started(record)

def load_transfer_prompt(kind="primary") -> str:
    """
    Загружает специальный промпт для анализа перевода из YAML-файла transfer_prompt.yaml,
    который должен находиться в той же директории, что и данный модуль.
    Ожидается наличие ключа 'transfer_prompt' в YAML.
    kind: 'primary' или 'followup'
    """
    prompt_file = Path(__file__).parent / "transfer_prompt.yaml"
    try:
        with prompt_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            prompt = data.get("transfer_prompt", {}).get(kind, "").strip() if data else ""
            if not prompt:
                raise ValueError(f"Пустой transfer_prompt для типа {kind}")
            return prompt
    except Exception as e:
        logger.error(f"Ошибка загрузки специального промпта из {prompt_file}: {e}")
        return ("Специальный анализ перевода: оцените успешность установления контакта с клиентом. "
                "Укажите, была ли реакция, и насколько качественно осуществлен перевод.")

def notify_transfer_started(transfer_record: dict):
    """
    Отправляет уведомление о том, что клиент позвонил и теперь ждёт перевода.
    """
    channel = config.TG_CHANNEL_NIZH if transfer_record["incoming_station"] in config.NIZH_STATION_CODES else config.TG_CHANNEL_OTHER

    msg = (
        f"[Перевод]: {transfer_record['phone_number']}\n"
        f"Станция: {get_station_name(transfer_record['incoming_station'])}"
    )
    if transfer_record.get("transfer_station"):
        msg += f"\nПеревести на: {transfer_record['transfer_station']}"
    if transfer_record.get("transfer_conditions"):
        msg += f"\nУсловия: {transfer_record['transfer_conditions']}"
    #if transfer_record.get("analysis"):
    #    msg += f"\nАнализ: {transfer_record['analysis']}"
    #channel = 302271829
    send_alert(msg, chat_id=channel)

    logger.info(f"Уведомление о начале перевода отправлено для {transfer_record['phone_number']}.")

def notify_transfer_completed(transfer_record: dict, complete_station: str):
    """
    Отправляет уведомление о том, что с клиентом успешно связались (перевод завершён).
    В уведомлении указывается исходная станция и станция, с которой поступил закрывающий звонок.
    """
    original_station_name = get_station_name(transfer_record["incoming_station"])
    complete_station_name = get_station_name(complete_station)
    channel = config.TG_CHANNEL_NIZH if complete_station in config.NIZH_STATION_CODES else config.TG_CHANNEL_OTHER
    msg = (
        f"Перевод завершён: с клиентом {transfer_record['phone_number']} успешно связались.\n"
        f"Исходная станция: {original_station_name}.\n"
        f"Клиенту перезвонили со станции: {complete_station_name} (вызов: {transfer_record['call_time'].strftime('%H:%M')})."
    )
    #channel = 302271829
    send_alert(msg, chat_id=channel)
    logger.info(f"Уведомление о завершённом переводе отправлено для {transfer_record['phone_number']} в канал {channel}.")

def add_transfer_case(phone_number: str, incoming_station: str, call_time: datetime, station: str = None, conditions: str = None, analysis: str = None):
    """
    Добавляет новую запись перевода со статусом 'waiting' и дедлайном через 2 часа.
    (Изменено: deadline теперь через 2 часа, чтобы запись оставалась "waiting" для уведомлений.)
    Сразу отправляет уведомление о начале ожидания перевода.
    """
    record = {
        "phone_number": phone_number,
        "incoming_station": incoming_station,
        "call_time": call_time,
        "deadline": call_time + timedelta(hours=2),
        "status": "waiting",
        "transfer_station": station,
        "transfer_conditions": conditions,
        "analysis": analysis
    }
    pending_transfers.append(record)
    logger.info(f"[transfer_tracker] Добавлен перевод (deadline=2 часа): {record}")
    save_transfer_cases()
    notify_transfer_started(record)

def check_new_call_for_transfer(phone_number: str, new_station: str, new_call_time: datetime, new_call_file: Path = None) -> bool:
    """
    Проверяет, закрывает ли новый входящий звонок ожидающий перевод.
    Если для данного номера найдена запись со статусом "waiting" и новый звонок пришёл позже исходного, то:
      - Если новая станция отличается от исходной, засчитываем звонок независимо от дедлайна.
      - Если новая станция совпадает с исходной, засчитываем звонок, если он поступил до дедлайна.
    При успешном закрытии обновляет запись до "completed", запускает специальный анализ в отдельном потоке,
    и отправляет уведомление о завершённом переводе с указанием станции, с которой поступил звонок.
    """
    phone_number_norm = normalize_phone_number(phone_number)
    norm_phone = phone_number_norm.lstrip('+')
    for rec in pending_transfers:
        rec_phone = normalize_phone_number(rec["phone_number"]).lstrip('+')
        if rec["status"] == "waiting" and rec_phone == norm_phone:
            logger.debug(f"Проверяем перевод для {phone_number}: {rec}")
            if new_call_time > rec["call_time"]:
                if new_station != rec["incoming_station"]:
                    rec["status"] = "completed"
                    logger.info(f"[transfer_tracker] Перевод для {phone_number} успешно завершён (разная станция: {new_station}).")
                    save_transfer_cases()
                    threading.Thread(target=process_transfer_closure, args=(new_call_file, rec), daemon=True).start()
                    notify_transfer_completed(rec, new_station)
                    return True
                elif new_call_time <= rec["deadline"]:
                    rec["status"] = "completed"
                    logger.info(f"[transfer_tracker] Перевод для {phone_number} успешно завершён (та же станция: {new_station}).")
                    save_transfer_cases()
                    threading.Thread(target=process_transfer_closure, args=(new_call_file, rec), daemon=True).start()
                    notify_transfer_completed(rec, new_station)
                    return True
    logger.debug(f"Не найден перевод для {phone_number} с новой станцией {new_station} и временем {new_call_time}")
    return False

try:
    from call_analyzer.internal_transcription import transcribe_audio_with_internal_service
    from call_analyzer.call_handler import thebai_analyze
except ImportError:
    try:
        from internal_transcription import transcribe_audio_with_internal_service
        from call_handler import thebai_analyze
    except ImportError:
        # Fallback if call_handler imports cause issues (circular import)
        pass

def get_transcript_via_service(file_path: Path) -> str:
    """
    Получает транскрипт для файла через сервис транскрипции.
    """
    try:
        # Читаем настройку стерео/моно из профиля пользователя
        stereo_mode = False
        if hasattr(config, 'PROFILE_SETTINGS') and config.PROFILE_SETTINGS:
            transcription_cfg = config.PROFILE_SETTINGS.get('transcription') or {}
            stereo_mode = bool(transcription_cfg.get('tbank_stereo_enabled', False))
        else:
            stereo_mode = getattr(config, 'TBANK_STEREO_ENABLED', False)
        
        # Загружаем дополнительный словарь для транскрипции (если не отключен в профиле)
        additional_vocab = []
        try:
            if getattr(config, "USE_ADDITIONAL_VOCAB", True):
                if hasattr(config, 'ADDITIONAL_VOCAB_FILE') and config.ADDITIONAL_VOCAB_FILE and config.ADDITIONAL_VOCAB_FILE.exists():
                    with config.ADDITIONAL_VOCAB_FILE.open("r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                        additional_vocab = data.get("additional_vocab", []) if data else []
            else:
                logger.info("USE_ADDITIONAL_VOCAB=False: словарь для транскрипции переводов не используется")
        except Exception as e:
            logger.debug(f"Не удалось загрузить словарь для транскрипции: {e}")
        
        return transcribe_audio_with_internal_service(
            file_path, 
            stereo_mode=stereo_mode,
            additional_vocab=additional_vocab if additional_vocab else None
        )
    except Exception as e:
        logger.error(f"Ошибка при получении транскрипта для {file_path}: {e}")
        return ""

def analyze_with_special_prompt(transcript: str, special_prompt: str) -> str:
    """
    Анализирует транскрипт с использованием специального промпта через сервис TheBaiAnalyzer.
    """
    try:
        return thebai_analyze(transcript, special_prompt)
    except Exception as e:
        logger.error(f"Ошибка при специальном анализе: {e}")
        return "Ошибка специального анализа"

def format_transcript(resp_json: dict) -> str:
    """
    Форматирует транскрипт из JSON-ответа.
    """
    if "results" not in resp_json:
        return ""
    results = resp_json["results"]
    lines = []
    current_speaker = None
    buffer_words = []
    for item in results:
        alt = item["alternatives"][0]
        spk = alt.get("speaker", "Unknown")
        word = alt.get("content", "")
        if spk != current_speaker:
            if buffer_words:
                lines.append(f"{current_speaker}: {' '.join(buffer_words)}")
            current_speaker = spk
            buffer_words = [word]
        else:
            buffer_words.append(word)
    if buffer_words:
        lines.append(f"{current_speaker}: {' '.join(buffer_words)}")
    return "\n".join(lines)

def process_transfer_closure(new_call_file: Path, transfer_record: dict):
    """
    При закрытии перевода выполняет специальный анализ звонка.
    Загружает специальный промпт из YAML-файла transfer_prompt.yaml, получает транскрипт через сервис,
    анализирует транскрипт с использованием специального промпта, сохраняет результат в текстовый файл,
    и выполняет дополнительные действия (например, отправляет уведомление).
    Результаты сохраняются в папке сегодняшнего дня в структуре:
      E:/CallRecords/mon/YYYY/MM/DD/transfer_analysis
    В файле сохраняется как транскрипция, так и результат специального анализа.
    """
    try:
        special_prompt = load_transfer_prompt("followup")
        transcript_text = get_transcript_via_service(new_call_file) if new_call_file is not None else ""
        analysis_result = analyze_with_special_prompt(transcript_text, special_prompt)
        today_folder = datetime.now().strftime("%Y/%m/%d")
        save_dir = (config.BASE_RECORDS_PATH / today_folder / "transcriptions" / "transfer_analysis")
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = save_dir / f"followup_transfer_{transfer_record['phone_number'].lstrip('+')}_{transfer_record['incoming_station']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with filename.open("w", encoding="utf-8") as f:
            f.write("Транскрипция звонка:\n\n")
            f.write(transcript_text)
            f.write("\n\nАнализ followup (перевод):\n\n")
            f.write(analysis_result)
        logger.info(f"Специальный анализ перевода сохранён в {filename}")
        
        # Сохраняем транскрипцию для новой системы аналитики
        try:
            from call_analyzer.utils import save_transcript_for_analytics  # type: ignore
        except ImportError:
            from utils import save_transcript_for_analytics
        original_filename = new_call_file.name if new_call_file else None
        save_transcript_for_analytics(transcript_text, transfer_record['phone_number'], transfer_record['incoming_station'], datetime.now(), original_filename)
        
        # --- Парсим результат анализа ---

        transfer_station = None
        transfer_conditions = None
        new_transfer_cycle = False
        m_station = re.search(r"\\[ПЕРЕВОД:СТАНЦИЯ=([^\\]]+)\\]", analysis_result)
        if m_station:
            transfer_station = m_station.group(1)
        m_conditions = re.search(r"\\[ПЕРЕВОД:УСЛОВИЯ=([^\\]]+)\\]", analysis_result)
        if m_conditions:
            transfer_conditions = m_conditions.group(1)
        # Проверяем, требуется ли новый перевод
        if '[ПЕРЕВОД:ПЕРЕВОД]' in analysis_result.upper():
            new_transfer_cycle = True
        # --- Обновляем статус и уведомляем ---
        transfer_record["status"] = "cycled" if new_transfer_cycle else "completed"
        transfer_record["cycled_at"] = datetime.now().isoformat() if new_transfer_cycle else None
        transfer_record["cycle_count"] = transfer_record.get("cycle_count", 0) + 1 if new_transfer_cycle else transfer_record.get("cycle_count", 0)
        save_transfer_cases()
        # Формируем уведомление
        msg = f"[Перевод] Завершён followup для {transfer_record['phone_number']}\n"
        if transfer_station and transfer_station != 'НЕИЗВЕСТНО':
            msg += f"Перевести на: {transfer_station}\n"
        else:
            msg += "Ожидается звонок с другой станции\n"
        if transfer_conditions and transfer_conditions != 'ЧАС':
            msg += f"Условия: {transfer_conditions}\n"
        if '[ПЕРЕВОД:ПЕРЕВОД]' in analysis_result.upper():
            msg += "Требуется новый перевод — создан новый кейс.\n"
        msg += f"\nАнализ: {analysis_result}"
        send_alert(msg)
        # --- Новый цикл перевода, если требуется ---
        if new_transfer_cycle:
            add_transfer_case(
                transfer_record["phone_number"],
                transfer_record["incoming_station"],
                datetime.now(),
                station=transfer_station,
                conditions=transfer_conditions,
                analysis=analysis_result
            )
            logger.info(f"[transfer_tracker] Цикл перевода: создан новый кейс для {transfer_record['phone_number']}")
    except Exception as e:
        logger.error(f"Ошибка при специальном анализе перевода: {e}")

def check_transfer_deadlines():
    """
    Проверяет все ожидающие переводы и, если текущая дата и время превышают дедлайн,
    изменяет статус перевода на 'failed' и сохраняет изменения.
    """
    now = datetime.now()
    changed = False
    for rec in pending_transfers:
        # Поскольку deadline теперь через 2 часа, здесь меняем статус только после 2 часов
        if rec["status"] == "waiting" and now >= rec["deadline"]:
            rec["status"] = "failed"
            logger.info(f"[transfer_tracker] Перевод {rec} не состоялся (deadline={rec['deadline']}).")
            changed = True
    if changed:
        save_transfer_cases()

def check_transfer_notifications():
    """
    Проверяет все записи переводов и отправляет уведомления в Telegram,
    если для записи прошло 30 минут ожидания (но менее 2 часов) или 2 часа (просрочка).
    Для станций Нижегородских уведомление отправляется в один канал, для остальных – в другой.
    При 30 мин: отправляется напоминание, при 2 часах: отправляется уведомление о просрочке.
    В данном варианте уведомления отправляются для записей со статусом "waiting".
    """
    now = datetime.now()
    for rec in pending_transfers:
        # Обрабатываем только записи со статусом "waiting"
        if rec["status"] == "waiting":
            waiting_time = (now - rec["call_time"]).total_seconds() / 60.0  # в минутах
            # Напоминание через 30 минут (но менее 120 минут), если уведомление ещё не отправлено
            if waiting_time >= 30 and waiting_time < 120 and not rec.get("reminder_sent"):
                channel = config.TG_CHANNEL_NIZH if rec["incoming_station"] in config.NIZH_STATION_CODES else config.TG_CHANNEL_OTHER
                station_name = get_station_name(rec["incoming_station"])
                msg = (f"Напоминание: клиент {rec['phone_number']} обратился в {rec['call_time'].strftime('%H:%M')} "
                       f"на станцию {station_name}.")
                if rec.get("transfer_station"):
                    msg += f"\nПланируется перевод на: {rec['transfer_station']}"
                if rec.get("transfer_conditions"):
                    msg += f"\nУсловия: {rec['transfer_conditions']}"
                #if rec.get("analysis"):
                #    msg += f"\nАнализ: {rec['analysis']}"
                msg += "\nЕму обещали перезвонить с другой станции, но до сих пор не перезвонили."
                #channel = 302271829
                send_alert(msg, chat_id=channel)
                rec["reminder_sent"] = True
                logger.info(f"Отправлено напоминание для {rec['phone_number']} в канал {channel}.")
            # Уведомление о просрочке через 120 минут, если уведомление ещё не отправлено
            elif waiting_time >= 120 and not rec.get("overdue_notified"):
                channel = config.TG_CHANNEL_NIZH if rec["incoming_station"] in config.NIZH_STATION_CODES else config.TG_CHANNEL_OTHER
                station_name = get_station_name(rec["incoming_station"])
                msg = (f"Просрочка: клиент {rec['phone_number']} обратился в {rec['call_time'].strftime('%H:%M')} "
                       f"на станцию {station_name}.")
                if rec.get("transfer_station"):
                    msg += f"\nПланировался перевод на: {rec['transfer_station']}"
                if rec.get("transfer_conditions"):
                    msg += f"\nУсловия: {rec['transfer_conditions']}"
                #if rec.get("analysis"):
                #    msg += f"\nАнализ: {rec['analysis']}"
                msg += "\nОбещали перезвонить с другой станции, но прошло более 2 часов без обратной связи."
                #channel = 302271829
                send_alert(msg, chat_id=channel)
                rec["overdue_notified"] = True
                logger.info(f"Отправлена просрочная нотификация для {rec['phone_number']} в канал {channel}.")

def check_special_reminders():
    """
    Проверяет кейсы с напоминанием (remind_at) и отправляет уведомление, если наступило время.
    """
    now = datetime.now()
    changed = False
    for rec in pending_transfers:
        if rec.get("remind_at") and not rec.get("notified", False):
            remind_at = datetime.fromisoformat(rec["remind_at"])
            if now >= remind_at:
                msg = f"⏰ Напоминание: клиент {rec['phone_number']} ждёт звонка! (Когда: {rec.get('transfer_when','')})"
                send_alert(msg)
                rec["notified"] = True
                changed = True
    if changed:
        save_transfer_cases()

if __name__ == "__main__":
    load_transfer_cases()
    check_special_reminders()
