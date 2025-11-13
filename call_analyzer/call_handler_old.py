# call_analyzer/call_handler.py

import logging
import re
import time
import os
import json
import requests
import yaml
from datetime import datetime
from pathlib import Path
from watchdog.events import FileSystemEventHandler
import random
from call_analyzer import config
from call_analyzer.retruck.outsourcing import outsourcing_queue
from call_analyzer.utils import (
    wait_for_file,
    send_alert,
    notify_on_error,
    make_request_with_retries, parse_filename
)

from call_analyzer.transfer_recall.transfer import check_new_call_for_transfer, add_transfer_case, pending_transfers, save_transfer_cases, get_station_name
from call_analyzer.transfer_recall.recall import add_recall_case, check_new_call_for_recall, pending_recalls, save_recall_cases

from call_analyzer.exental_alert import run_exental_alert

@notify_on_error()
def transcribe_and_analyze(file_path: Path, station_code: str):
    filename = file_path.name
    logger.info(f"Начало обработки файла {filename} (станция {station_code}).")

    # 1. Сразу парсим phone_number, station_code_parsed, call_time
    phone_number, station_code_parsed, call_time = parse_filename(filename)

    # 2. Отправляем файл на транскрипцию (Speechmatics)
    sm_config = {
        "type": "transcription",
        "transcription_config": {
            "language": config.SPEECHMATICS_LANGUAGE,
            "diarization": "speaker",
        }
    }
    if additional_vocab:
        sm_config["transcription_config"]["additional_vocab"] = [
            {"content": w} for w in additional_vocab
        ]

    job_id = speechmatics_send_file(file_path, sm_config)
    if not job_id:
        return

    transcript_text = speechmatics_wait_transcript(job_id)
    if not transcript_text:
        logger.error(f"Транскрипт не получен (job_id={job_id}).")
        return

    # 3. Анализ через TheB.ai
    station_prompt = station_prompts.get(station_code, station_prompts.get("default", "Определи результат разговора."))
    analysis_text = thebai_analyze(transcript_text, station_prompt)
    analysis_upper = analysis_text.upper()

    # 4. Сохраняем результат
    result_filename = save_transcript_analysis(file_path, transcript_text, analysis_text)

    # 5. Проверяем: целевой без результата -> вызываем exental_alert
    if is_no_result_call(analysis_text):
        logger.info("Звонок целевой без результата -> вызываем exental_alert для расширенного уведомления.")
        if phone_number and call_time:
            run_exental_alert(
                txt_path=str(result_filename),
                station_code=station_code,
                phone_number=phone_number,
                date_str=call_time.strftime("%Y-%m-%d-%H-%M-%S")
            )
        else:
            logger.warning("Слишком мало данных (phone_number/call_time), не можем вызвать exental_alert.")

    # 6. Если видим результат ПЕРЕВОД
    if "[ТИПЗВОНКА:ЦЕЛЕВОЙ]" in analysis_upper and "[РЕЗУЛЬТАТ:ПЕРЕВОД]" in analysis_upper:
        logger.info("Обнаружен звонок с результатом: ПЕРЕВОД. Запускаем расширенный анализ кейса.")
        transfer_prompt_path = Path(__file__).parent / "transfer_recall" / "transfer_prompt.yaml"
        with open(transfer_prompt_path, "r", encoding="utf-8") as f:
            transfer_prompt_data = yaml.safe_load(f)
            transfer_prompt_value = transfer_prompt_data.get("transfer_prompt", "")
            if isinstance(transfer_prompt_value, dict):
                transfer_prompt_primary = transfer_prompt_value.get("primary", "")
            else:
                transfer_prompt_primary = transfer_prompt_value
        # Провести расширенный анализ
        transfer_analysis = thebai_analyze(transcript_text, transfer_prompt_primary)
        # --- Сохраняем анализ и транскрипт (primary) ---
        today_folder = call_time.strftime("%Y/%m/%d")
        save_dir = Path(f"E:/CallRecords/{today_folder}/transcriptions/transfer_analysis")
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = save_dir / f"primary_transfer_{phone_number.lstrip('+')}_{station_code}_{call_time.strftime('%Y%m%d_%H%M%S')}.txt"
        with filename.open("w", encoding="utf-8") as f:
            f.write("Транскрипция звонка:\n\n")
            f.write(transcript_text)
            f.write("\n\nАнализ primary (перевод):\n\n")
            f.write(transfer_analysis)
        # Парсим расширенные теги

        transfer_station = None
        transfer_conditions = None
        m_station = re.search(r"\[ПЕРЕВОД:СТАНЦИЯ=([^\]]+)\]", transfer_analysis)
        if m_station:
            transfer_station = m_station.group(1)
        m_conditions = re.search(r"\[ПЕРЕВОД:УСЛОВИЯ=([^\]]+)\]", transfer_analysis)
        if m_conditions:
            transfer_conditions = m_conditions.group(1)
        # --- Новая логика: отсчёт только если условия == ЧАС ---
        if transfer_conditions == "ЧАС":
            if phone_number and call_time:
                add_transfer_case(phone_number, station_code, call_time, station=transfer_station, conditions=transfer_conditions, analysis=transfer_analysis)
            else:
                logger.warning("Слишком мало данных (phone_number/call_time) для ПЕРЕВОДА.")
        else:
            # Отправить спец. уведомление, сохранить в json как special, не запускать отсчёт
            record = {
                "phone_number": phone_number,
                "incoming_station": station_code,
                "call_time": call_time,
                "status": "special",
                "transfer_station": transfer_station,
                "transfer_conditions": transfer_conditions,
                "analysis": transfer_analysis
            }
            pending_transfers.append(record)
            save_transfer_cases()
            msg = (
                f"[Перевод] Новый кейс: {phone_number}\n"
                f"Станция: {get_station_name(station_code)}"
            )
            if transfer_station:
                msg += f"\nПеревести на: {transfer_station}"
            if transfer_conditions:
                msg += f"\nУсловия: {transfer_conditions}"
            if transfer_analysis:
                msg += f"\nАнализ: {transfer_analysis}"
            send_alert(msg)

    # 7. Если видим результат ПЕРЕЗВОНИТЬ
    if "[ТИПЗВОНКА:ЦЕЛЕВОЙ]" in analysis_upper and "[РЕЗУЛЬТАТ:ПЕРЕЗВОНИТЬ]" in analysis_upper:
        logger.info("Обнаружен звонок с результатом: ПЕРЕЗВОНИТЬ. Запускаем расширенный анализ кейса.")
        recall_prompt_path = Path(__file__).parent / "transfer_recall" / "recall_prompt.yaml"
        with open(recall_prompt_path, "r", encoding="utf-8") as f:
            recall_prompt_data = yaml.safe_load(f)
            recall_prompt_value = recall_prompt_data.get("recall_prompt", "")
            if isinstance(recall_prompt_value, dict):
                recall_prompt_primary = recall_prompt_value.get("primary", "")
            else:
                recall_prompt_primary = recall_prompt_value
        recall_analysis = thebai_analyze(transcript_text, recall_prompt_primary)
        # --- Сохраняем анализ и транскрипт (primary) ---
        today_folder = call_time.strftime("%Y/%m/%d")
        save_dir = Path(f"E:/CallRecords/{today_folder}/transcriptions/recall_analysis")
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = save_dir / f"primary_recall_{phone_number.lstrip('+')}_{station_code}_{call_time.strftime('%Y%m%d_%H%M%S')}.txt"
        with filename.open("w", encoding="utf-8") as f:
            f.write("Транскрипция звонка:\n\n")
            f.write(transcript_text)
            f.write("\n\nАнализ primary (перезвон):\n\n")
            f.write(recall_analysis)
        recall_when = None
        # Проверяем теги: [ПЕРЕЗВОНИТЬ:КОГДА=...] или [ПЕРЕЗВОНИТЬ:ЧАС]
        m_when = re.search(r"\[ПЕРЕЗВОНИТЬ:КОГДА=([^\]]+)\]", recall_analysis)
        recall_hour = False
        if m_when:
            recall_when = m_when.group(1)
        elif "[ПЕРЕЗВОНИТЬ:ЧАС]" in recall_analysis.upper():
            recall_hour = True

        if phone_number and call_time:
            if recall_hour:
                # Классический отсчёт часа до перезвона
                add_recall_case(phone_number, station_code, call_time, when=None, analysis=recall_analysis)
            elif recall_when and recall_when.strip().lower() == "час":
                # Классический отсчёт часа до перезвона
                add_recall_case(phone_number, station_code, call_time, when=None, analysis=recall_analysis)
            elif recall_when:
                # Просто уведомление, кейс со статусом 'special', без отсчёта
                record = {
                    "phone_number": phone_number,
                    "station_code": station_code,
                    "call_time": call_time,
                    "status": "special",
                    "recall_when": recall_when,
                    "analysis": recall_analysis
                }
                pending_recalls.append(record)
                save_recall_cases()
                msg = (
                    f"[Перезвон] Новый кейс: {phone_number}\n"
                    f"Станция: {get_station_name(station_code)}\n"
                    f"Когда: {recall_when}\n"
                    f"Анализ: {recall_analysis}"
                )
                send_alert(msg)
            else:
                # Нет явного условия — fallback
                add_recall_case(phone_number, station_code, call_time, when=None, analysis=recall_analysis)
        else:
            logger.warning("Слишком мало данных для перезвона (phone_number/call_time).")

    logger.info(f"Обработка файла {filename} завершена.")


# Импортируем расширенный анализ/уведомление:

logger = logging.getLogger(__name__)

# Глобальные переменные для idle-check (main.py)
last_processed_time = None
last_alert_time = None

def get_current_folder():
    """
    Возвращает E:/CallRecords/YYYY/mm/dd (текущий день).
    """
    return datetime.now().strftime("E:/CallRecords/%Y/%m/%d")

# Загружаем промпты (Bestway) из config.PROMPTS_FILE
def load_prompts():
    if not config.PROMPTS_FILE.exists():
        logger.warning(f"Файл промптов {config.PROMPTS_FILE} не найден, используем дефолтный.")
        return {}
    try:
        with config.PROMPTS_FILE.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("stations", {})
    except Exception as e:
        msg = f"Ошибка загрузки промтов: {e}"
        logger.error(msg)
        send_alert(msg)
        return {}

station_prompts = load_prompts()

# Загружаем дополнительный словарь для Speechmatics
def load_additional_vocab():
    if not config.ADDITIONAL_VOCAB_FILE or not config.ADDITIONAL_VOCAB_FILE.exists():
        return []
    try:
        with config.ADDITIONAL_VOCAB_FILE.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("additional_vocab", [])
    except Exception as e:
        logger.error(f"Ошибка при загрузке словаря: {e}")
        return []

additional_vocab = load_additional_vocab()

class CallHandler(FileSystemEventHandler):
    """
    Watchdog: при появлении нового .mp3 – если аутсорс (Ретрак) -> в очередь,
    иначе локальная (Bestway) транскрипция/анализ.
    """

    def on_created(self, event):
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if file_path.suffix.lower() != ".mp3":
            return
        if not file_path.name.startswith("fs_"):
            return

        # Пауза, чтобы файл точно записался
        time.sleep(3)
        if not wait_for_file(file_path):
            logger.error(f"Файл {file_path} недоступен (после нескольких попыток).")
            return

        phone_number, station_code, call_dt = parse_filename(file_path.name)
        logger.info(f"Новый файл: {file_path} (номер={phone_number}, станция={station_code})")

        # Первым делом проверяем, не закрывает ли этот звонок ожидающий перевод
        # Здесь можно изменить check_new_call_for_transfer так, чтобы он принимал еще и путь к файлу
        if check_new_call_for_transfer(phone_number, station_code, call_dt, file_path):
            # Если звонок засчитан как закрывающий перевод, то специальная обработка уже запущена,
            # а стандартная логика обработки входящих звонков не должна выполняться.
            return

        # 2. Проверяем, не закрывает ли этот звонок ожидание «перезвона»
        if check_new_call_for_recall(phone_number, station_code, call_dt, file_path):
            return  # если «закрыло» перезвон, тоже выходим

        # Если звонок не является закрывающим перевод, продолжаем стандартную обработку
        global last_processed_time
        last_processed_time = datetime.now()

        if station_code in config.OUTSOURCED_STATION_CODES:
            logger.info(f"Станция {station_code} – аутсорс (Retruck). Кладем в очередь outsourcing.")
            outsourcing_queue.put(str(file_path))
        elif station_code in config.STATION_NAMES:
            logger.info(f"Станция {station_code} – локальная (Bestway). Запуск транскрипции + анализа.")
            transcribe_and_analyze(file_path, station_code)
        else:
            logger.warning(f"Неизвестный код станции: {station_code} (файл {file_path.name})")


@notify_on_error()
def transcribe_and_analyze(file_path: Path, station_code: str):
    filename = file_path.name
    logger.info(f"Начало обработки файла {filename} (станция {station_code}).")

    # 1. Сразу парсим phone_number, station_code_parsed, call_time
    phone_number, station_code_parsed, call_time = parse_filename(filename)

    # 2. Отправляем файл на транскрипцию (Speechmatics)
    sm_config = {
        "type": "transcription",
        "transcription_config": {
            "language": config.SPEECHMATICS_LANGUAGE,
            "diarization": "speaker",
        }
    }
    if additional_vocab:
        sm_config["transcription_config"]["additional_vocab"] = [
            {"content": w} for w in additional_vocab
        ]

    job_id = speechmatics_send_file(file_path, sm_config)
    if not job_id:
        return

    transcript_text = speechmatics_wait_transcript(job_id)
    if not transcript_text:
        logger.error(f"Транскрипт не получен (job_id={job_id}).")
        return

    # 3. Анализ через TheB.ai
    station_prompt = station_prompts.get(station_code, station_prompts.get("default", "Определи результат разговора."))
    analysis_text = thebai_analyze(transcript_text, station_prompt)
    analysis_upper = analysis_text.upper()

    # 4. Сохраняем результат
    result_filename = save_transcript_analysis(file_path, transcript_text, analysis_text)

    # 5. Проверяем: целевой без результата -> вызываем exental_alert
    if is_no_result_call(analysis_text):
        logger.info("Звонок целевой без результата -> вызываем exental_alert для расширенного уведомления.")
        if phone_number and call_time:
            run_exental_alert(
                txt_path=str(result_filename),
                station_code=station_code,
                phone_number=phone_number,
                date_str=call_time.strftime("%Y-%m-%d-%H-%M-%S")
            )
        else:
            logger.warning("Слишком мало данных (phone_number/call_time), не можем вызвать exental_alert.")

    # 6. Если видим результат ПЕРЕВОД
    if "[ТИПЗВОНКА:ЦЕЛЕВОЙ]" in analysis_upper and "[РЕЗУЛЬТАТ:ПЕРЕВОД]" in analysis_upper:
        logger.info("Обнаружен звонок с результатом: ПЕРЕВОД. Запускаем расширенный анализ кейса.")
        transfer_prompt_path = Path(__file__).parent / "transfer_recall" / "transfer_prompt.yaml"
        with open(transfer_prompt_path, "r", encoding="utf-8") as f:
            transfer_prompt_data = yaml.safe_load(f)
            transfer_prompt_value = transfer_prompt_data.get("transfer_prompt", "")
            if isinstance(transfer_prompt_value, dict):
                transfer_prompt_primary = transfer_prompt_value.get("primary", "")
            else:
                transfer_prompt_primary = transfer_prompt_value
        # Провести расширенный анализ
        transfer_analysis = thebai_analyze(transcript_text, transfer_prompt_primary)
        # --- Сохраняем анализ и транскрипт (primary) ---
        today_folder = call_time.strftime("%Y/%m/%d")
        save_dir = Path(f"E:/CallRecords/{today_folder}/transcriptions/transfer_analysis")
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = save_dir / f"primary_transfer_{phone_number.lstrip('+')}_{station_code}_{call_time.strftime('%Y%m%d_%H%M%S')}.txt"
        with filename.open("w", encoding="utf-8") as f:
            f.write("Транскрипция звонка:\n\n")
            f.write(transcript_text)
            f.write("\n\nАнализ primary (перевод):\n\n")
            f.write(transfer_analysis)
        # Парсим расширенные теги

        transfer_station = None
        transfer_conditions = None
        m_station = re.search(r"\[ПЕРЕВОД:СТАНЦИЯ=([^\]]+)\]", transfer_analysis)
        if m_station:
            transfer_station = m_station.group(1)
        m_conditions = re.search(r"\[ПЕРЕВОД:УСЛОВИЯ=([^\]]+)\]", transfer_analysis)
        if m_conditions:
            transfer_conditions = m_conditions.group(1)
        # --- Новая логика: отсчёт только если условия == ЧАС ---
        if transfer_conditions == "ЧАС":
            if phone_number and call_time:
                add_transfer_case(phone_number, station_code, call_time, station=transfer_station, conditions=transfer_conditions, analysis=transfer_analysis)
            else:
                logger.warning("Слишком мало данных (phone_number/call_time) для ПЕРЕВОДА.")
        else:
            # Отправить спец. уведомление, сохранить в json как special, не запускать отсчёт
            record = {
                "phone_number": phone_number,
                "incoming_station": station_code,
                "call_time": call_time,
                "status": "special",
                "transfer_station": transfer_station,
                "transfer_conditions": transfer_conditions,
                "analysis": transfer_analysis
            }
            pending_transfers.append(record)
            save_transfer_cases()
            msg = (
                f"[Перевод] Новый кейс: {phone_number}\n"
                f"Станция: {get_station_name(station_code)}"
            )
            if transfer_station:
                msg += f"\nПеревести на: {transfer_station}"
            if transfer_conditions:
                msg += f"\nУсловия: {transfer_conditions}"
            if transfer_analysis:
                msg += f"\nАнализ: {transfer_analysis}"
            send_alert(msg)

    # 7. Если видим результат ПЕРЕЗВОНИТЬ
    if "[ТИПЗВОНКА:ЦЕЛЕВОЙ]" in analysis_upper and "[РЕЗУЛЬТАТ:ПЕРЕЗВОНИТЬ]" in analysis_upper:
        logger.info("Обнаружен звонок с результатом: ПЕРЕЗВОНИТЬ. Запускаем расширенный анализ кейса.")
        recall_prompt_path = Path(__file__).parent / "transfer_recall" / "recall_prompt.yaml"
        with open(recall_prompt_path, "r", encoding="utf-8") as f:
            recall_prompt_data = yaml.safe_load(f)
            recall_prompt_value = recall_prompt_data.get("recall_prompt", "")
            if isinstance(recall_prompt_value, dict):
                recall_prompt_primary = recall_prompt_value.get("primary", "")
            else:
                recall_prompt_primary = recall_prompt_value
        recall_analysis = thebai_analyze(transcript_text, recall_prompt_primary)
        # --- Сохраняем анализ и транскрипт (primary) ---
        today_folder = call_time.strftime("%Y/%m/%d")
        save_dir = Path(f"E:/CallRecords/{today_folder}/transcriptions/recall_analysis")
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = save_dir / f"primary_recall_{phone_number.lstrip('+')}_{station_code}_{call_time.strftime('%Y%m%d_%H%M%S')}.txt"
        with filename.open("w", encoding="utf-8") as f:
            f.write("Транскрипция звонка:\n\n")
            f.write(transcript_text)
            f.write("\n\nАнализ primary (перезвон):\n\n")
            f.write(recall_analysis)
        recall_when = None
        # Проверяем теги: [ПЕРЕЗВОНИТЬ:КОГДА=...] или [ПЕРЕЗВОНИТЬ:ЧАС]
        m_when = re.search(r"\[ПЕРЕЗВОНИТЬ:КОГДА=([^\]]+)\]", recall_analysis)
        recall_hour = False
        if m_when:
            recall_when = m_when.group(1)
        elif "[ПЕРЕЗВОНИТЬ:ЧАС]" in recall_analysis.upper():
            recall_hour = True

        if phone_number and call_time:
            if recall_hour:
                # Классический отсчёт часа до перезвона
                add_recall_case(phone_number, station_code, call_time, when=None, analysis=recall_analysis)
            elif recall_when and recall_when.strip().lower() == "час":
                # Классический отсчёт часа до перезвона
                add_recall_case(phone_number, station_code, call_time, when=None, analysis=recall_analysis)
            elif recall_when:
                # Просто уведомление, кейс со статусом 'special', без отсчёта
                record = {
                    "phone_number": phone_number,
                    "station_code": station_code,
                    "call_time": call_time,
                    "status": "special",
                    "recall_when": recall_when,
                    "analysis": recall_analysis
                }
                pending_recalls.append(record)
                save_recall_cases()
                msg = (
                    f"[Перезвон] Новый кейс: {phone_number}\n"
                    f"Станция: {get_station_name(station_code)}\n"
                    f"Когда: {recall_when}\n"
                    f"Анализ: {recall_analysis}"
                )
                send_alert(msg)
            else:
                # Нет явного условия — fallback
                add_recall_case(phone_number, station_code, call_time, when=None, analysis=recall_analysis)
        else:
            logger.warning("Слишком мало данных для перезвона (phone_number/call_time).")

    logger.info(f"Обработка файла {filename} завершена.")


def parse_datetime_from_string(date_str: str) -> datetime:
    # "2025-12-31-16-00-00" -> datetime(2025,12,31,16,0,0)
    return datetime.strptime(date_str, "%Y-%m-%d-%H-%M-%S")


def speechmatics_send_file(file_path: Path, config_data: dict) -> str:
    """
    Отправка файла в Speechmatics -> job_id
    """
    url = "https://asr.api.speechmatics.com/v2/jobs"
    headers = {"Authorization": f"Bearer {config.SPEECHMATICS_API_KEY}"}
    data_json = {"config": json.dumps(config_data)}

    def generate_custom_filename() -> str:
        now = datetime.now()
        ordinal = random.randint(1, 660)  # порядковый номер дня
        time_str = now.strftime("%H%M%S")   # время в часах, минутах, секундах
        return f"day_{ordinal}_{time_str}.mp3"

    def _request():
        with file_path.open("rb") as f:
            custom_filename = generate_custom_filename()
            files = {"data_file": (custom_filename, f)}
            return requests.post(url, headers=headers, data=data_json, files=files, timeout=30)

    resp = make_request_with_retries(_request, max_retries=3, delay=5)
    if not resp or resp.status_code != 201:
        logger.error(f"[Speechmatics] Ошибка загрузки {file_path.name}: "
                     f"{resp.status_code if resp else 'NoResp'} {resp.text if resp else ''}")
        return None

    job_id = resp.json().get("id")
    logger.info(f"Speechmatics: Файл {file_path.name} загружен, job_id={job_id}")
    return job_id


def speechmatics_wait_transcript(job_id: str, max_retries=30, delay=15) -> str:
    """
    Ждём готовность -> возвращаем текст (Speaker: content)
    """
    url = f"https://asr.api.speechmatics.com/v2/jobs/{job_id}/transcript"
    headers = {"Authorization": f"Bearer {config.SPEECHMATICS_API_KEY}"}

    for attempt in range(max_retries):
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            return format_transcript(data)
        elif resp.status_code == 404:
            logger.info(f"Транскрипция не готова, попытка {attempt+1}/{max_retries}, ждем {delay} сек.")
            time.sleep(delay)
        else:
            logger.error(f"Speechmatics: неожиданный ответ: {resp.status_code}, {resp.text}")
            time.sleep(delay)
    return ""


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


def thebai_analyze(transcript: str, prompt: str) -> str:
    """
    Отправляем запрос к TheB.ai
    """
    if not transcript.strip():
        return "Пустой транскрипт, нет анализа."

    payload = {
        "model": config.THEBAI_MODEL,
        "messages": [{"role": "user", "content": f"{prompt}\n\nВот диалог:\n{transcript}"}],
        #"stream": False
    }
    headers = {
        "Authorization": f"Bearer {config.THEBAI_API_KEY}",
        "Content-Type": "application/json"
    }

    def _request():
        return requests.post(config.THEBAI_URL, headers=headers, json=payload, timeout=90)

    resp = make_request_with_retries(_request, max_retries=3, delay=10)
    if not resp or resp.status_code != 200:
        logger.error(f"TheB.ai анализ ошибка: {resp.status_code if resp else 'No resp'}, {resp.text if resp else ''}")
        return "Ошибка анализа"

    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Ошибка парсинга ответа TheB.ai: {e}")
        return "Ошибка анализа"


def save_transcript_analysis(file_path: Path, transcript_text: str, analysis_text: str) -> Path:
    today_subdir = datetime.now().strftime("%Y/%m/%d")
    trans_dir = config.BASE_RECORDS_PATH / today_subdir / "transcriptions"
    os.makedirs(trans_dir, exist_ok=True)
    result_file = trans_dir / f"{file_path.stem}.txt"

    if result_file.exists():
        logger.info(f"Файл-результат уже существует: {result_file}")
        return result_file
    try:
        with result_file.open("w", encoding="utf-8") as f:
            f.write("Диалог:\n\n")
            f.write(transcript_text)
            f.write("\n\nАнализ:\n\n")
            f.write(analysis_text)
        logger.info(f"Результат сохранён: {result_file}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении {result_file}: {e}")
    return result_file


def is_no_result_call(analysis_text: str) -> bool:
    upper_text = analysis_text.upper().replace(" ", "")
    return ("[ТИПЗВОНКА:ЦЕЛЕВОЙ]" in upper_text) and ("[РЕЗУЛЬТАТ:НЕТ]" in upper_text)
