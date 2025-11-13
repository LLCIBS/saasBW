import logging
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import threading
import yaml
import re

from call_analyzer import config
from call_analyzer.utils import send_alert
from call_analyzer.retruck.services import TranscriptionService, TheBaiAnalyzer

logger = logging.getLogger(__name__)

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

RECALL_DATA_FILE = "E:/CallRecords/mon/recall_cases.json"
pending_recalls = []

def extract_recall_when(analysis: str) -> str | None:
    """
    Ищет тег вида [ПЕРЕЗВОНИТЬ:ЧТО-ТО] и возвращает "ЧТО-ТО", либо None.
    """
    if not analysis:
        return None
    match = re.search(r"\[ПЕРЕЗВОНИТЬ:([^\]]+)\]", analysis)
    if match:
        return match.group(1).strip()
    return None

def normalize_station_code(station_code):
    """
    Приводит дочерний код станции к родительскому.
    """
    if station_code in config.STATION_NAMES:
        return station_code  # Уже родительский
    for parent, children in config.STATION_MAPPING.items():
        if station_code in children:
            return parent
    return None  # Неизвестный код станции

def get_station_name(station_code: str) -> str:
    """
    Возвращает человекочитаемое название станции с учётом STATION_MAPPING,
    по аналогии с transfer.py.
    """
    # Сначала прямой поиск в config.STATION_NAMES
    if station_code in config.STATION_NAMES:
        return config.STATION_NAMES[station_code]
    # Если нет, пробуем найти parent_code
    for parent_code, child_codes in config.STATION_MAPPING.items():
        if station_code in child_codes:
            return config.STATION_NAMES.get(parent_code, station_code)
    # Иначе возвращаем сам station_code
    return station_code

def get_parent_station_code(st_code: str) -> str:
    # Если st_code уже есть в config.STATION_NAMES, возвращаем его
    if st_code in config.STATION_NAMES:
        return st_code
    # Если st_code является дочерним, ищем родителя
    for parent_code, child_codes in config.STATION_MAPPING.items():
        if st_code in child_codes:
            return parent_code
    return st_code  # если не найдено, возвращаем как есть


def load_recall_cases():
    global pending_recalls
    if not os.path.exists(RECALL_DATA_FILE):
        logger.info("[recall_tracker] Файл с ожиданиями перезвона не найден, начинаем с пустого списка.")
        pending_recalls = []
        return
    try:
        with open(RECALL_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for rec in data:
                rec["call_time"] = datetime.fromisoformat(rec["call_time"])
                rec["deadline"] = datetime.fromisoformat(rec["deadline"])
                if 'tg_msg_id' in rec:
                    rec['tg_msg_id'] = rec['tg_msg_id']
                if 'recall_station' in rec:
                    rec['recall_station'] = rec['recall_station']
                if 'recall_when' in rec:
                    rec['recall_when'] = rec['recall_when']
                if 'analysis' in rec:
                    rec['analysis'] = rec['analysis']
                if 'remind_at' in rec:
                    rec['remind_at'] = datetime.fromisoformat(rec['remind_at'])
                if 'notified' in rec:
                    rec['notified'] = rec['notified']
            pending_recalls = data
            logger.info(f"[recall_tracker] Загружено {len(pending_recalls)} записей из {RECALL_DATA_FILE}")
    except Exception as e:
        logger.error(f"[recall_tracker] Ошибка при загрузке {RECALL_DATA_FILE}: {e}")
        pending_recalls = []


def save_recall_cases():
    try:
        data = []
        for rec in pending_recalls:
            new_rec = dict(rec)
            new_rec["call_time"] = rec["call_time"].isoformat() if isinstance(rec["call_time"], datetime) else rec["call_time"]
            if "deadline" in rec and isinstance(rec["deadline"], datetime):
                new_rec["deadline"] = rec["deadline"].isoformat()
            else:
                logger.warning(f"[recall_tracker] Нет deadline у кейса: {rec}")
                new_rec["deadline"] = (rec["call_time"] + timedelta(minutes=30)).isoformat() if isinstance(rec["call_time"], datetime) else rec["call_time"]
            if 'tg_msg_id' in rec:
                new_rec['tg_msg_id'] = rec['tg_msg_id']
            if 'recall_station' in rec:
                new_rec['recall_station'] = rec['recall_station']
            if 'recall_when' in rec:
                new_rec['recall_when'] = rec['recall_when']
            if 'analysis' in rec:
                new_rec['analysis'] = rec['analysis']
            if 'remind_at' in rec:
                new_rec['remind_at'] = rec['remind_at'].isoformat() if isinstance(rec['remind_at'], datetime) else rec['remind_at']
            if 'notified' in rec:
                new_rec['notified'] = rec['notified']
            data.append(new_rec)
        with open(RECALL_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[recall_tracker] Сохранено {len(data)} записей в {RECALL_DATA_FILE}")
        notify_recall_change()
    except Exception as e:
        logger.error(f"[recall_tracker] Ошибка при сохранении {RECALL_DATA_FILE}: {e}")

def notify_recall_change():
    """
    Короткая сводка по всем перезвонам (отправляется в общий чат, например ALERT_CHAT_ID)
    """
    try:
        total = len(pending_recalls)
        waiting = sum(1 for rec in pending_recalls if rec['status'] == 'waiting')
        completed = sum(1 for rec in pending_recalls if rec['status'] == 'completed')
        failed = sum(1 for rec in pending_recalls if rec['status'] == 'failed')
        msg = (
            f"Обновлены данные по перезвонам (recall_cases.json):\n"
            f"Всего: {total}\n"
            f"Ожидающих: {waiting}\n"
            f"Завершенных: {completed}\n"
            f"Не состоявшихся: {failed}"
        )
        send_alert(msg, chat_id=config.ALERT_CHAT_ID)
    except Exception as e:
        logger.error(f"[recall_tracker] Ошибка при отправке сводки: {e}")

def notify_recall_started(recall_record: dict):
    station_code = recall_record["station_code"]
    station_name = get_station_name(station_code)

    # Добавляем эти две строки:
    phone_number = recall_record["phone_number"]
    call_time = recall_record["call_time"]

    if recall_record["station_code"] in config.NIZH_STATION_CODES:
        channel = config.TG_CHANNEL_NIZH
    else:
        channel = config.TG_CHANNEL_OTHER

    # Здесь формируем короткое сообщение
    msg = (
        f"[Перезвонить в течение часа]: {recall_record['phone_number']}\n"
        f"Станция: {get_station_name(recall_record['station_code'])}"
    )
    if recall_record.get("recall_station"):
        msg += f"\nПерезвонить с: {recall_record['recall_station']}"
    if recall_record.get("recall_when"):
        msg += f"\nКогда: {recall_record['recall_when']}"
    #if recall_record.get("analysis"):
    #    msg += f"\nАнализ: {recall_record['analysis']}"
    #channel = 302271829
    message_id = send_alert(msg, chat_id=channel)
    recall_record['tg_msg_id'] = message_id
    save_recall_cases()

    logger.info(f"[recall_tracker] Уведомление о начале перезвона отправлено в канал {channel}.")


def notify_recall_completed(recall_record: dict):
    phone_number = recall_record["phone_number"]
    station_code = recall_record["station_code"]
    station_name = get_station_name(station_code)
    call_time = recall_record["call_time"]

    if station_code in config.NIZH_STATION_CODES:
        channel = config.TG_CHANNEL_NIZH
    else:
        channel = config.TG_CHANNEL_OTHER

    msg = (
        f"🟢 Клиенту перезвонили: {phone_number}, {station_name}"
    )
    #channel = 302271829
    reply_to = recall_record.get('tg_msg_id')
    send_alert(msg, chat_id=channel, reply_to_message_id=reply_to)

    logger.info(f"[recall_tracker] Уведомление о завершённом перезвоне отправлено в канал {channel}.")

def notify_recall_warning(recall_record: dict):
    phone_number = recall_record["phone_number"]
    station_code = recall_record["station_code"]
    station_name = get_station_name(station_code)
    call_time = recall_record["call_time"]

    if station_code in config.NIZH_STATION_CODES:
        channel = config.TG_CHANNEL_NIZH
    else:
        channel = config.TG_CHANNEL_OTHER

    msg = (
        f"🟡⏳ Клиент ждёт звонок уже 30 мин.: {phone_number}, {station_name}"
    )
    #channel = 302271829
    reply_to = recall_record.get('tg_msg_id')
    send_alert(msg, chat_id=channel, reply_to_message_id=reply_to)

    logger.info(f"[recall_tracker] Отправлено тревожное уведомление о перезвоне в канал {channel}.")

def notify_recall_lost(recall_record: dict):
    phone_number = recall_record["phone_number"]
    station_code = recall_record["station_code"]
    station_name = get_station_name(station_code)
    call_time = recall_record["call_time"]

    if station_code in config.NIZH_STATION_CODES:
        channel = config.TG_CHANNEL_NIZH
    else:
        channel = config.TG_CHANNEL_OTHER

    msg = (
        f"🔴 Потеря клиента, ожидание больше часа: {phone_number}, {station_name}, {call_time}"
    )
    #channel = 302271829
    reply_to = recall_record.get('tg_msg_id')
    send_alert(msg, chat_id=channel, reply_to_message_id=reply_to)

    logger.info(f"[recall_tracker] Отправлено уведомление о потере клиента в канал {channel}.")

def add_recall_case(phone_number: str, station_code: str, call_time: datetime, station: str = None, when: str = None, analysis: str = None):
    """
    Добавляет новую запись перезвона. Если указано when (например, "завтра утром"),
    вычисляет время напоминания (remind_at) и сохраняет его вместе с кейсом.
    По умолчанию deadline через 30 минут после call_time.
    """
    record = {
        "phone_number": phone_number,
        "station_code": station_code,
        "call_time": call_time,
        "status": "waiting",
        "analysis": analysis,
        "deadline": call_time + timedelta(minutes=30)
    }
    if when:
        record["recall_when"] = when
        remind_at = parse_special_time(when, now=call_time)
        if remind_at:
            record["remind_at"] = remind_at.isoformat()
            record["notified"] = False
    pending_recalls.append(record)
    logger.info(f"[recall_tracker] Добавлен перезвон: {record}")
    save_recall_cases()
    notify_recall_started(record)

def load_recall_prompt(kind="primary") -> str:
    prompt_file = Path(__file__).parent / "recall_prompt.yaml"
    try:
        with prompt_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            prompt = data.get("recall_prompt", {}).get(kind, "").strip() if data else ""
            if not prompt:
                raise ValueError(f"Пустой recall_prompt для типа {kind}")
            return prompt
    except Exception as e:
        logger.error(f"Ошибка при загрузке recall_prompt.yaml: {e}")
        return "Анализ перезвона: установите, был ли контакт."

def check_new_call_for_recall(phone_number: str, new_station: str, new_call_time: datetime, new_call_file: Path = None) -> bool:
    norm_phone = phone_number.lstrip('+')
    normalized_station = normalize_station_code(new_station)
    
    if not normalized_station:
        logger.warning(f"Не удалось определить родительскую станцию для кода {new_station}")
        return False

    for rec in pending_recalls:
        if rec["status"] == "waiting" and rec["phone_number"].lstrip('+') == norm_phone:
            if rec["station_code"] == normalized_station:
                delta_minutes = (new_call_time - rec["call_time"]).total_seconds() / 60
                if 0 < delta_minutes <= 60:
                    rec["status"] = "completed"
                    logger.info(f"[recall_tracker] Перезвон для {phone_number} завершён (станция {new_station}).")
                    save_recall_cases()
                    threading.Thread(
                        target=process_recall_closure,
                        args=(new_call_file, rec),
                        daemon=True
                    ).start()
                    notify_recall_completed(rec)
                    return True
    return False

# сервисы для транскрипции (если нужно)
transcription_service = TranscriptionService(api_key=config.SPEECHMATICS_API_KEY)
analyzer = TheBaiAnalyzer(api_key=config.THEBAI_API_KEY, model=config.THEBAI_MODEL)

def get_transcript_via_service(file_path: Path) -> str:
    try:
        vocab = config.ADDITIONAL_VOCAB if hasattr(config, "ADDITIONAL_VOCAB") else []
        job_id = transcription_service.start_transcription(file_path, vocab)
        if not job_id:
            return ""
        transcript_json = transcription_service.get_transcription(job_id)
        return format_transcript(transcript_json)
    except Exception as e:
        logger.error(f"Ошибка при транскрипции для {file_path}: {e}")
        return ""

def analyze_with_recall_prompt(transcript: str, recall_prompt: str) -> str:
    try:
        return analyzer.analyze(transcript, recall_prompt)
    except Exception as e:
        logger.error(f"Ошибка при анализе перезвона: {e}")
        return "Ошибка анализа перезвона"

def format_transcript(resp_json: dict) -> str:
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

def process_recall_closure(new_call_file: Path, recall_record: dict):
    try:
        if not new_call_file:
            return
        recall_prompt = load_recall_prompt("followup")
        transcript_text = get_transcript_via_service(new_call_file)
        if not transcript_text:
            return
        analysis_result = analyze_with_recall_prompt(transcript_text, recall_prompt)

        # Сохраняем анализ для истории
        today_folder = datetime.now().strftime("%Y/%m/%d")
        save_dir = Path(f"E:/CallRecords/{today_folder}/transcriptions/recall_analysis")
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = save_dir / f"followup_recall_{recall_record['phone_number'].lstrip('+')}_{recall_record['station_code']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with filename.open("w", encoding="utf-8") as f:
            f.write("Транскрипция второго (перезвонного) звонка:\n\n")
            f.write(transcript_text)
            f.write("\n\nАнализ followup (перезвон):\n\n")
            f.write(analysis_result)

        logger.info(f"[recall_tracker] Анализ перезвона сохранён в {filename}")
        send_alert(f"Специальный анализ перезвона завершён для {recall_record['phone_number']}. Результат: {filename}")

        # --- Цикличность: если снова требуется перезвонить, создаём новый кейс ---
        # Теперь проверяем только на тег [ПЕРЕЗВОНИТЬ:СВЯЗАЛИСЬ] (без учёта регистра)
        if '[ПЕРЕЗВОНИТЬ:СВЯЗАЛИСЬ]' in analysis_result.upper():
            recall_when = None
            m_when = re.search(r"\[ПЕРЕЗВОНИТЬ:КОГДА=([^\]]+)\]", analysis_result)
            if m_when:
                recall_when = m_when.group(1)
            # Закрываем текущий кейс как цикличный
            recall_record["status"] = "cycled"
            recall_record["cycled_at"] = datetime.now().isoformat()
            recall_record["cycle_count"] = recall_record.get("cycle_count", 0) + 1
            save_recall_cases()
            # Создаём новый кейс (связанный с предыдущим)
            add_recall_case(
                recall_record["phone_number"],
                recall_record["station_code"],
                datetime.now(),
                when=recall_when,
                analysis=analysis_result
            )
            logger.info(f"[recall_tracker] Цикл перезвона: создан новый кейс для {recall_record['phone_number']}")
    except Exception as e:
        logger.error(f"Ошибка при специальном анализе перезвона: {e}")

def check_recall_notifications():
    now = datetime.now()
    changed = False
    for rec in pending_recalls:
        if rec["status"] == "waiting":
            waiting_time = (now - rec["call_time"]).total_seconds() / 60.0
            if waiting_time >= 30 and waiting_time < 60 and not rec.get("warning_sent"):
                notify_recall_warning(rec)
                rec["warning_sent"] = True
                changed = True
            if waiting_time >= 60:
                rec["status"] = "failed"
                notify_recall_lost(rec)
                changed = True
    if changed:
        save_recall_cases()

def check_recall_deadlines():
    pass

def check_special_reminders():
    """
    Проверяет кейсы с напоминанием (remind_at) и отправляет уведомление, если наступило время.
    """
    now = datetime.now()
    changed = False
    for rec in pending_recalls:
        if rec.get("remind_at") and not rec.get("notified", False):
            remind_at = datetime.fromisoformat(rec["remind_at"])
            if now >= remind_at:
                msg = f"⏰ Напоминание: клиент {rec['phone_number']} ждёт звонка! (Когда: {rec.get('recall_when','')})"
                send_alert(msg)
                rec["notified"] = True
                changed = True
    if changed:
        save_recall_cases()

if __name__ == "__main__":
    load_recall_cases()
    # add_recall_case("+70001234567", "9327", datetime.now())
    check_recall_notifications()
    check_special_reminders()
