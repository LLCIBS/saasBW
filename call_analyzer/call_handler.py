# call_analyzer/call_handler.py

import logging
import re
import time
import os
import json
import requests
import yaml
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from watchdog.events import FileSystemEventHandler
import random
import config

try:
    from call_analyzer.utils import (
        wait_for_file,
        send_alert,
        notify_on_error,
        make_request_with_retries,
        parse_filename,
        is_legal_entity_call,
        send_legal_entity_notification,
    )
except ImportError:
    from utils import (
        wait_for_file,
        send_alert,
        notify_on_error,
        make_request_with_retries,
        parse_filename,
        is_legal_entity_call,
        send_legal_entity_notification,
    )

try:
    from call_analyzer.transfer_recall.transfer import (
        check_new_call_for_transfer,
        add_transfer_case,
        pending_transfers,
        save_transfer_cases,
        get_station_name,
    )
    from call_analyzer.transfer_recall.recall import (
        add_recall_case,
        check_new_call_for_recall,
        pending_recalls,
        save_recall_cases,
    )
except ImportError:
    from transfer_recall.transfer import (
        check_new_call_for_transfer,
        add_transfer_case,
        pending_transfers,
        save_transfer_cases,
        get_station_name,
    )
    from transfer_recall.recall import (
        add_recall_case,
        check_new_call_for_recall,
        pending_recalls,
        save_recall_cases,
    )

try:
    from call_analyzer.exental_alert import run_exental_alert  # type: ignore
except ImportError:
    from exental_alert import run_exental_alert

try:
    from call_analyzer.internal_transcription import transcribe_audio_with_internal_service
except ImportError:
    from internal_transcription import transcribe_audio_with_internal_service

from concurrent.futures import ThreadPoolExecutor
executor = ThreadPoolExecutor(max_workers=4)

# Дедупликация обработки событий для одних и тех же файлов
from threading import Lock
_processed_files_lock = Lock()
_processed_files = set()


def ensure_daily_folder(target_date: datetime | None = None) -> Path:
    """Гарантирует наличие каталога BASE_RECORDS_PATH/YYYY/MM/DD и возвращает его Path."""
    base_path = Path(str(config.BASE_RECORDS_PATH))
    base_path.mkdir(parents=True, exist_ok=True)
    dt = target_date or datetime.now()
    day_path = base_path / f"{dt:%Y}" / f"{dt:%m}" / f"{dt:%d}"
    day_path.mkdir(parents=True, exist_ok=True)
    return day_path

def get_main_station_code(station_code):
    """
    Преобразует код подстанции в основной код станции.
    
    Args:
        station_code (str): Код станции (может быть основной или подстанция)
        
    Returns:
        str: Основной код станции или None, если не найден
    """
    # Сначала проверяем, есть ли код в основных станциях
    if station_code in config.STATION_NAMES:
        return station_code
    
    # Ищем в маппинге подстанций
    for main_code, sub_codes in config.STATION_MAPPING.items():
        if station_code in sub_codes:
            return main_code
    
    return None

@notify_on_error()
def transcribe_and_analyze(file_path: Path, station_code: str):
    filename = file_path.name
    logger.info(f"Начало обработки файла {filename} (станция {station_code}).")

    # 1. Сразу парсим phone_number, station_code_parsed, call_time
    phone_number, station_code_parsed, call_time = parse_filename(filename)

    # 2. Отправляем файл на транскрипцию (Internal Service)
    # Передаем режим стерео/моно из профиля пользователя
    # Сначала пытаемся прочитать из PROFILE_SETTINGS (для worker процессов)
    # Если нет, то из глобального TBANK_STEREO_ENABLED
    stereo_mode = False
    if hasattr(config, 'PROFILE_SETTINGS') and config.PROFILE_SETTINGS:
        transcription_cfg = config.PROFILE_SETTINGS.get('transcription') or {}
        stereo_mode = bool(transcription_cfg.get('tbank_stereo_enabled', False))
    else:
        stereo_mode = getattr(config, 'TBANK_STEREO_ENABLED', False)
    transcript_text = transcribe_audio_with_internal_service(file_path, stereo_mode=stereo_mode)
    if not transcript_text:
        logger.error(f"Транскрипт не получен для файла {filename}.")
        return

    # 3. Анализ через TheB.ai
    station_prompt = station_prompts.get(station_code, station_prompts.get("default", "Определи результат разговора."))
    analysis_text = thebai_analyze(transcript_text, station_prompt)
    analysis_upper = analysis_text.upper()

    # 4. Сохраняем результат
    result_filename = save_transcript_analysis(file_path, transcript_text, analysis_text)
    
    # 4.1. Сохраняем транскрипцию для новой системы аналитики
    try:
        from call_analyzer.utils import save_transcript_for_analytics  # type: ignore
    except ImportError:
        from utils import save_transcript_for_analytics
    save_transcript_for_analytics(transcript_text, phone_number, station_code, call_time, filename)

    # 4.2. Проверяем, является ли звонок от юридического лица
    if is_legal_entity_call(transcript_text):
        logger.info(f"Обнаружен звонок от юридического лица: {phone_number}")
        send_legal_entity_notification(
            phone_number=phone_number,
            station_code=station_code,
            call_time=call_time,
            transcript_text=transcript_text,
            analysis_text=analysis_text,
            filename=filename
        )

    # 5. Запускаем расширенный разбор по чек-листу (ТОЛЬКО ДЛЯ ЦЕЛЕВЫХ/ПЕРВИЧНЫХ ЗВОНКОВ)
    # Проверяем наличие маркера ЦЕЛЕВОЙ (или ПЕРВИЧНЫЙ) в результате анализа якоря.
    # Это экономит ресурсы и исключает оценку менеджера по ошибочным звонкам.
    if "[ТИПЗВОНКА:ЦЕЛЕВОЙ]" in analysis_upper or "ПЕРВИЧНЫЙ" in analysis_upper:
        logger.info("Звонок определен как ЦЕЛЕВОЙ/ПЕРВИЧНЫЙ. Запускаем расширенный разбор (чек-лист).")
        if phone_number and call_time:
            run_exental_alert(
                txt_path=str(result_filename),
                station_code=station_code,
                phone_number=phone_number,
                date_str=call_time.strftime("%Y-%m-%d-%H-%M-%S")
            )
        else:
            logger.warning("Слишком мало данных (phone_number/call_time), не можем вызвать exental_alert.")
    else:
        logger.info(f"Звонок НЕ является целевым (анализ: {analysis_upper[:50]}...). Чек-лист пропущен.")

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
        save_dir = Path(config.BASE_RECORDS_PATH) / today_folder / "transcriptions" / "transfer_analysis"
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
        save_dir = Path(config.BASE_RECORDS_PATH) / today_folder / "transcriptions" / "recall_analysis"
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
    Возвращает путь к текущей дате на основе config.BASE_RECORDS_PATH.
    Пример: BASE_RECORDS_PATH/YYYY/mm/dd
    """
    return str(ensure_daily_folder().as_posix())


class IngressHandler(FileSystemEventHandler):
    """Следит за корневой папкой и переносит файлы в папку дня."""

    def __init__(self, downstream_handler):
        super().__init__()
        self.base_path = Path(str(config.BASE_RECORDS_PATH)).resolve()
        self.downstream_handler = downstream_handler
        self.logger = logging.getLogger(__name__)

    def _should_skip(self, relative_parts):
        if not relative_parts:
            return False
        first = relative_parts[0].lower()
        if first == 'runtime':
            return True
        return False

    def on_created(self, event):
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        if not file_path.exists():
            return
        try:
            relative = file_path.resolve().relative_to(self.base_path)
        except Exception:
            return
        rel_dirs = relative.parts[:-1]
        if self._should_skip(rel_dirs):
            return
        if len(rel_dirs) >= 3:
            return
        target_dir = ensure_daily_folder()
        target_path = target_dir / file_path.name
        try:
            wait_for_file(file_path)
            shutil.move(str(file_path), str(target_path))
            self.logger.info("[Ingress] Файл %s перемещён в %s", file_path.name, target_dir)
            mock_event = SimpleNamespace(src_path=str(target_path), is_directory=False)
            self.downstream_handler.on_created(mock_event)
        except Exception as exc:
            self.logger.warning("[Ingress] Не удалось переместить %s: %s", file_path, exc)

# Загружаем промпты (Bestway) из config.PROMPTS_FILE
def load_prompts():
    if not config.PROMPTS_FILE.exists():
        logger.warning(f"Файл промптов {config.PROMPTS_FILE} не найден, используем дефолтный.")
        return {}
    try:
        with config.PROMPTS_FILE.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            # Проверяем, что data не None и является словарем
            if data is None:
                logger.warning(f"Файл промптов {config.PROMPTS_FILE} пуст или невалиден, используем дефолтный.")
                return {}
            if not isinstance(data, dict):
                logger.warning(f"Файл промптов {config.PROMPTS_FILE} имеет неверный формат, используем дефолтный.")
                return {}
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

        # Нормализуем путь для кроссплатформенности
        # На Ubuntu важно использовать resolve() для получения абсолютного пути
        # Это работает корректно и на Windows
        try:
            file_path = Path(event.src_path).resolve()
        except (OSError, ValueError) as e:
            # Если не удалось разрешить путь, пробуем без resolve()
            logger.warning(f"Не удалось разрешить путь {event.src_path}, используем как есть: {e}")
            file_path = Path(event.src_path)
        
        name_lower = file_path.name.lower()
        # Принимаем стандартные записи fs_*, external-* и новый формат вход_*; расширения из конфигурации
        # Файлы формата out-* пропускаются
        if not (
            name_lower.startswith("fs_") or 
            name_lower.startswith("external-") or 
            name_lower.startswith("вход_")
        ):
            return
        
        # Для формата external-* пропускаем файлы с хвостами .wav-out. и .wav-in.
        if name_lower.startswith("external-"):
            if ".wav-out." in name_lower or ".wav-in." in name_lower:
                logger.debug(f"Пропускаем файл с хвостом .wav-out. или .wav-in.: {file_path.name}")
                return
        
        if file_path.suffix and file_path.suffix.lower() not in config.FILENAME_PATTERNS['supported_extensions']:
            return

        # Дедупликация: если этот файл уже обрабатывается/обработан, выходим
        with _processed_files_lock:
            if file_path.name in _processed_files:
                logger.info(f"Пропуск повтора обработки для {file_path.name}")
                return
            _processed_files.add(file_path.name)

        # Межпроцессная дедупликация: создаём lock-файл для имени звонка
        # Нормализуем путь для кроссплатформенности
        try:
            base_path = Path(config.BASE_RECORDS_PATH).resolve()
        except (OSError, ValueError):
            base_path = Path(config.BASE_RECORDS_PATH)
        
        lock_dir = base_path / "runtime" / "locks"
        lock_path = None  # Инициализируем для использования в замыкании
        has_lock = False
        
        try:
            os.makedirs(lock_dir, exist_ok=True)
            # Нормализуем lock_path для единообразия
            lock_path = (lock_dir / f"{file_path.name}.lock")
            try:
                lock_path = lock_path.resolve()
            except (OSError, ValueError):
                pass  # Используем как есть, если не удалось разрешить
            # атомарное создание
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            has_lock = True
        except FileExistsError:
            # Если lock уже существует, проверим его «протухание»: возможно, остался от упавшего процесса
            try:
                # lock_path должен быть уже определен выше, но на всякий случай проверяем
                if lock_path is None:
                    lock_path = (lock_dir / f"{file_path.name}.lock")
                    try:
                        lock_path = lock_path.resolve()
                    except (OSError, ValueError):
                        pass
                
                if lock_path.exists():
                    mtime = os.path.getmtime(lock_path)
                    age_sec = time.time() - mtime
                    # Если старше 10 минут — считаем протухшим, удаляем и пробуем снова
                    if age_sec > 600:
                        logger.warning(f"Обнаружен протухший lock ({int(age_sec)} сек) для {file_path.name}, удаляем и продолжаем")
                        os.remove(lock_path)
                        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                        os.close(fd)
                        has_lock = True
                    else:
                        logger.info(f"Пропуск (lock существует) для {file_path.name}")
                        return
                else:
                    # Теоретически не должно случиться, но подстрахуемся: создадим заново
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd)
                    has_lock = True
            except Exception as e:
                logger.warning(f"Не удалось обработать/создать lock для {file_path.name}: {e}")
                return
        except Exception as e:
            logger.warning(f"Не удалось создать lock для {file_path.name}: {e}")
            has_lock = False

        # Помощник для безопасного снятия lock
        def _release_lock():
            try:
                # Проверяем, что lock_path был определен и has_lock установлен
                # Используем nonlocal для доступа к переменным внешней области видимости
                nonlocal lock_path, has_lock
                if lock_path is not None and has_lock and os.path.exists(lock_path):
                    os.remove(lock_path)
            except Exception:
                pass

        try:
            # Пауза, чтобы файл точно записался
            time.sleep(3)
            if not wait_for_file(file_path):
                logger.error(f"Файл {file_path} недоступен (после нескольких попыток).")
                return

            phone_number, station_code, call_dt = parse_filename(file_path.name)
            logger.info(f"Новый файл: {file_path} (номер={phone_number}, станция={station_code})")

            # Если не удалось распарсить номер/станцию, пропускаем спец-проверки, чтобы избежать ошибок
            if not phone_number or not station_code:
                logger.warning(f"Не удалось распарсить имя файла, пропускаю спец-проверки transfer/recall: {file_path.name}")
                return

            # Получаем основной код станции для проверок
            main_station_code = get_main_station_code(station_code)

            # Первым делом проверяем, не закрывает ли этот звонок ожидающий перевод
            # Используем основной код станции для корректной проверки
            if check_new_call_for_transfer(phone_number, main_station_code or station_code, call_dt, file_path):
                return

            # 2. Проверяем, не закрывает ли этот звонок ожидание «перезвона»
            # Используем основной код станции для корректной проверки
            if check_new_call_for_recall(phone_number, main_station_code or station_code, call_dt, file_path):
                return  # если «закрыло» перезвон, тоже выходим

            # Если звонок не является закрывающим перевод, продолжаем стандартную обработку
            global last_processed_time
            last_processed_time = datetime.now()

            # Логируем информацию о привязке подстанции к основной станции
            if main_station_code and main_station_code != station_code:
                logger.info(f"Подстанция {station_code} привязана к основной станции {main_station_code}")

            if main_station_code in config.STATION_NAMES:
                logger.info(f"Станция {station_code} (основная: {main_station_code}) – локальная (Bestway). Запуск транскрипции + анализа.")
                def _wrapped_process():
                    try:
                        transcribe_and_analyze(file_path, main_station_code)
                    finally:
                        # снимаем lock после завершения обработки
                        _release_lock()
                executor.submit(_wrapped_process)
            else:
                logger.warning(f"Неизвестный код станции: {station_code} (файл {file_path.name})")
        finally:
            _release_lock()


def parse_datetime_from_string(date_str: str) -> datetime:
    # "2025-12-31-16-00-00" -> datetime(2025,12,31,16,0,0)
    return datetime.strptime(date_str, "%Y-%m-%d-%H-%M-%S")


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
    """
    Сохраняет транскрипт и анализ в папку transcriptions относительно исходного файла.
    Это гарантирует, что файлы сохраняются в правильной папке пользователя.
    """
    # Определяем путь относительно исходного файла, а не используем общий BASE_RECORDS_PATH
    # Это важно для многопользовательского режима, когда файлы могут быть в /var/calls/users/1/
    try:
        # Нормализуем путь исходного файла
        file_path = file_path.resolve()
    except (OSError, ValueError):
        pass  # Используем как есть, если не удалось разрешить
    
    # Определяем базовую директорию дня (YYYY/MM/DD) относительно исходного файла
    # Если файл в /var/calls/users/1/2025/11/17/file.wav, то transcriptions будет в /var/calls/users/1/2025/11/17/transcriptions/
    file_parent = file_path.parent
    
    # Проверяем, находится ли файл в структуре YYYY/MM/DD
    # Проверяем последние 3 компонента пути: должны быть YYYY (4 цифры), MM (2 цифры), DD (2 цифры)
    is_in_date_structure = False
    if file_parent.exists() and len(file_parent.parts) >= 3:
        # Берем последние 3 части пути
        last_three_parts = file_parent.parts[-3:]
        # Проверяем формат: YYYY (4 цифры), MM (2 цифры), DD (2 цифры)
        if (len(last_three_parts[0]) == 4 and last_three_parts[0].isdigit() and
            len(last_three_parts[1]) == 2 and last_three_parts[1].isdigit() and
            len(last_three_parts[2]) == 2 and last_three_parts[2].isdigit()):
            # Дополнительная проверка: год должен быть разумным (1900-2100), месяц 01-12, день 01-31
            try:
                year = int(last_three_parts[0])
                month = int(last_three_parts[1])
                day = int(last_three_parts[2])
                if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                    is_in_date_structure = True
            except ValueError:
                pass  # Если не удалось преобразовать в числа, структура неверна
    
    # Если файл в правильной структуре даты, используем родительскую директорию дня
    # Если нет, используем config.BASE_RECORDS_PATH как fallback
    if is_in_date_structure:
        trans_dir = file_parent / "transcriptions"
    else:
        today_subdir = datetime.now().strftime("%Y/%m/%d")
        trans_dir = config.BASE_RECORDS_PATH / today_subdir / "transcriptions"
        logger.debug(f"Файл не в структуре дня (путь: {file_parent}), используем fallback: {trans_dir}")
    
    # Создаем директорию используя метод Path (не os.makedirs, так как trans_dir это Path объект)
    trans_dir.mkdir(parents=True, exist_ok=True)
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


def is_target_call(analysis_text: str) -> bool:
    """Целевой звонок: достаточно наличия тега [ТИПЗВОНКА: ЦЕЛЕВОЙ]."""
    upper_text = analysis_text.upper().replace(" ", "")
    return "[ТИПЗВОНКА:ЦЕЛЕВОЙ]" in upper_text
