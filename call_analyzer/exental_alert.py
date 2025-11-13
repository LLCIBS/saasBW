# call_analyzer/exental_alert.py

import os
import re
import yaml
import requests
import logging
from datetime import datetime
from pathlib import Path

import config

try:
    from call_analyzer.utils import ensure_telegram_ready  # type: ignore
except ImportError:
    from utils import ensure_telegram_ready

logger = logging.getLogger(__name__)

# Список вопросов по умолчанию (fallback на случай отсутствия YAML)
DEFAULT_QUESTIONS = [
    "Представился/приветствовал?",
    "Выяснил имя клиента?",
    "Имя звучало >2 раз?",
    "Предложил решение?",
    "Клиент записан?",
    "Остались вопросы?",
    "Резюмировал результат?",
    "Поблагодарил/попрощался?"
]

# Простая эвристическая валидация имени
_NAME_STOPWORDS = set([
    "я", "меня", "мое", "это", "здравствуйте", "добрый", "день", "вечер", "утро",
    "магазин", "магазине", "слушаю", "вас", "угу", "ага", "алло", "да", "нет", "так",
    # Частые слова из названий/адресов
    "фокус", "рено", "пежо", "крауля", "малышева", "пешей", "вкус", "сорок", "четыре"
])

def _is_probable_russian_name(token: str) -> bool:
    """Возвращает True, если token похож на русское имя (простая эвристика)."""
    if not token:
        return False
    t = token.strip()
    # Только кириллица, с заглавной буквы
    if not re.match(r"^[А-ЯЁ][а-яё]+$", t):
        return False
    # Разумная длина
    if len(t) < 3 or len(t) > 14:
        return False
    # Исключаем служебные/частые слова
    if t.lower() in _NAME_STOPWORDS:
        return False
    return True

def run_exental_alert(txt_path: str, station_code: str, phone_number: str, date_str: str):
    """
    Точка входа для расширенного анализа и отправки сообщения,
    заменяет exental_alert.exe.
    """
    logger.info(f"[exental_alert] Запуск. txt={txt_path}, station={station_code}, phone={phone_number}, date={date_str}")

    dialog_text = extract_dialog_from_txt(txt_path)
    if not dialog_text.strip():
        logger.warning("[exental_alert] Диалог пуст, завершаем.")
        return

    script_prompt_8 = config.SCRIPT_PROMPT_8_PATH  # Пусть в config.py будет SCRIPT_PROMPT_8_PATH
    if not script_prompt_8.exists():
        logger.error(f"[exental_alert] Файл промпта {script_prompt_8} не найден.")
        return
    prompt_8, checklist_titles, checklist_prompts = load_script_prompt_8(script_prompt_8)
    if not prompt_8.strip():
        logger.warning("[exental_alert] Пустой prompt_8, завершаем.")
        return

    # Дополним общий промпт подсказками по каждому пункту чек-листа,
    # чтобы модели было проще детектировать признаки выполнения.
    if checklist_titles:
        hints_lines = [
            "Правила оценивания (строго соблюдать):",
            "1) Учитывай ТОЛЬКО реплики менеджера (SPEAKER_01).",
            "2) Если признаков недостаточно или сомневаешься — ставь [ОТВЕТ: НЕТ].",
            "3) Формат ответа — одна строка на пункт в порядке 1..N:",
            "   'i. <Название пункта> [ОТВЕТ: ДА|НЕТ] [ОБОСНОВАНИЕ: кратко, цитаты/парафразы SPEAKER_01]'.",
            "4) Для 'Выявление потребности' считай ДА только если есть ≥2 вопроса менеджера и ≥1 открытый вопрос или перефраз ('правильно понимаю...').",
            "5) Для 'Инициативность менеджера' считай ДА только если есть явное предложение следующего шага ('предлагаю/давайте/могу/забронирую/созвонимся/назначим/оформим' и т.п.).",
            "Подсказки по пунктам (ориентиры, не отменяют правила):"
        ]
        for idx, title in enumerate(checklist_titles, start=1):
            tip = (checklist_prompts[idx - 1] if idx - 1 < len(checklist_prompts) else "").strip()
            if tip:
                hints_lines.append(f"{idx}. {title}\nПодсказка: {tip}")
            else:
                hints_lines.append(f"{idx}. {title}")
        enriched_prompt = f"{prompt_8}\n\n" + "\n".join(hints_lines)
    else:
        enriched_prompt = prompt_8

    # Отправляем диалог на TheB.ai с расширенным промптом
    new_analysis = call_theb_ai(dialog_text, enriched_prompt)
    if not new_analysis.strip():
        logger.warning("[exental_alert] TheB.ai вернул пустой результат.")
        return

    caption, raw_analysis, qa_text, overall = parse_answers_and_form_message(
        new_analysis, station_code, phone_number, date_str, checklist_titles, dialog_text, checklist_prompts
    )
    if not caption:
        logger.warning("[exental_alert] Недостаточно ответов для формирования сообщения.")
        return

    analysis_path = save_analysis(txt_path, dialog_text, new_analysis, qa_text, overall)
    logger.info(f"[exental_alert] Итоговый анализ сохранён: {analysis_path}")

    mp3_path = guess_mp3_path(txt_path)
    send_exental_results(station_code, caption, overall, mp3_path, analysis_path)

    logger.info("[exental_alert] Завершено.")


def extract_dialog_from_txt(txt_path: str) -> str:
    """
    Извлекаем текст между 'Диалог:' и 'Анализ:' из файла txt.
    """
    if not os.path.isfile(txt_path):
        logger.error(f"[exental_alert] Файл {txt_path} не найден.")
        return ""
    with open(txt_path, "r", encoding="utf-8") as f:
        full_text = f.read()
    start_marker = "Диалог:"
    end_marker = "Анализ:"
    start_idx = full_text.find(start_marker)
    if start_idx == -1:
        logger.warning(f"[exental_alert] 'Диалог:' не найден, возвращаем весь текст.")
        return full_text
    start_idx += len(start_marker)
    end_idx = full_text.find(end_marker, start_idx)
    if end_idx == -1:
        dialog_text = full_text[start_idx:].strip()
    else:
        dialog_text = full_text[start_idx:end_idx].strip()
    return dialog_text

def extract_operator_name_from_transcript(dialog_text: str, station_code: str = None) -> str:
    """
    Извлекает имя оператора из транскрипции разговора, когда консультант представляется.
    Ищет в первых репликах SPEAKER_01 фразы с представлением.
    Если имя не найдено, возвращает None.
    
    Args:
        dialog_text: Текст диалога с репликами вида "SPEAKER_01: текст"
        station_code: Код станции для fallback (опционально)
    
    Returns:
        Имя оператора (только имя, без фамилии) или None
    """
    if not dialog_text:
        return None
    
    # Ищем первые 5 реплик SPEAKER_01 (обычно там происходит представление)
    lines = dialog_text.splitlines()
    manager_first_lines = []
    count = 0
    for line in lines:
        line_stripped = line.strip()
        if (line_stripped.startswith("SPEAKER_01:") or line_stripped.startswith("Speaker_01:")) and count < 5:
            # Извлекаем текст после "SPEAKER_01:"
            text = line_stripped.split(":", 1)[1].strip() if ":" in line_stripped else line_stripped
            manager_first_lines.append(text)
            count += 1
    
    if not manager_first_lines:
        return None
    
    # Объединяем первые реплики для поиска (сохраняем оригинальный регистр для извлечения имени)
    first_text_original = " ".join(manager_first_lines)
    first_text = first_text_original.lower()
    
    # Паттерны для поиска имени при представлении (работаем с оригинальным текстом для извлечения имени с правильным регистром)
    patterns = [
        # "меня зовут [Имя]" или "меня зовут [Имя] [Фамилия]"
        (r'меня\s+зовут\s+([А-ЯЁ][а-яё]+)', 1, True),
        # "мое имя [Имя]"
        (r'мое\s+имя\s+([А-ЯЁ][а-яё]+)', 1, True),
        # "здравствуйте, меня зовут [Имя]"
        (r'здравствуйте[,\s]+меня\s+зовут\s+([А-ЯЁ][а-яё]+)', 1, True),
        # "добрый день, меня зовут [Имя]"
        (r'добрый\s+(?:день|вечер|утро)[,\s]+меня\s+зовут\s+([А-ЯЁ][а-яё]+)', 1, True),
        # "доброе утро, меня зовут [Имя]"
        (r'доброе\s+утро[,\s]+меня\s+зовут\s+([А-ЯЁ][а-яё]+)', 1, True),
        # "здравствуйте, я [Имя]"
        (r'здравствуйте[,\s]+я\s+([А-ЯЁ][а-яё]+)', 1, True),
        # "[Имя] слушаю" - имя перед "слушаю" (самый распространенный формат)
        (r'([А-ЯЁ][а-яё]{2,})\s+слушаю\s+вас', 1, True),
        (r'([А-ЯЁ][а-яё]{2,})\s+слушаю', 1, True),
        # "[Имя] здравствуйте" - имя в начале реплики
        (r'^([А-ЯЁ][а-яё]{2,})\s+здравствуйте', 1, True),
        # "[Имя] добрый день/вечер" - имя в начале реплики
        (r'^([А-ЯЁ][а-яё]{2,})\s+добрый\s+(?:день|вечер)', 1, True),
        # "я [Имя]" (в контексте представления, но не в середине предложения)
        (r'^я\s+([А-ЯЁ][а-яё]+)', 1, True),
        # "это [Имя]" (в начале разговора)
        (r'^это\s+([А-ЯЁ][а-яё]+)', 1, True),
    ]
    
    # Ищем по паттернам (сначала в оригинальном тексте для извлечения имени с правильным регистром)
    for pattern, group_num, use_original in patterns:
        search_text = first_text_original if use_original else first_text
        match = re.search(pattern, search_text, re.IGNORECASE | re.MULTILINE)
        if match:
            name = match.group(group_num)
            # Берем только имя (первое слово), если есть фамилия
            name_parts = name.split()
            if name_parts:
                extracted_name = name_parts[0].capitalize()
                # Валидируем, что это похоже на имя
                if _is_probable_russian_name(extracted_name):
                    logger.info(f"[exental_alert] Извлечено имя оператора из транскрипции: {extracted_name}")
                    return extracted_name
    
    # Дополнительная проверка: ищем последнее слово перед приветствиями (формат: "... имя добрый вечер")
    # Это нужно для случаев типа "магазин рено пежо малышева евгения добрый вечер"
    greeting_patterns = [
        r'([А-ЯЁ][а-яё]{2,})\s+добрый\s+(?:день|вечер|утро)',
        r'([А-ЯЁ][а-яё]{2,})\s+здравствуйте',
    ]
    for greeting_pattern in greeting_patterns:
        matches = re.finditer(greeting_pattern, first_text_original, re.IGNORECASE)
        for match in matches:
            # Берем слово перед приветствием
            word_before = match.group(1)
            if word_before:
                extracted_name = word_before.capitalize()
                # Валидируем, что это похоже на имя (не название магазина/адрес)
                if _is_probable_russian_name(extracted_name):
                    # Дополнительная проверка: не должно быть частью названия магазина
                    # Проверяем контекст - если перед именем есть слова типа "магазин", "рено" и т.д., это может быть имя
                    start_pos = match.start()
                    context_before = first_text_original[max(0, start_pos-50):start_pos].lower()
                    # Если в контексте есть слова магазина, но имя валидно - принимаем
                    if extracted_name.lower() not in ['малышева', 'рено', 'пежо', 'фокус', 'крауля']:
                        logger.info(f"[exental_alert] Извлечено имя оператора из транскрипции (перед приветствием): {extracted_name}")
                        return extracted_name
    
    # Если не найдено, логируем для отладки (только если есть реплики)
    if manager_first_lines:
        logger.debug(f"[exental_alert] Имя оператора не найдено в транскрипции. Первые реплики: {first_text[:200] if first_text else 'пусто'}")
    return None

def get_operator_name(dialog_text: str = None, station_code: str = None) -> str:
    """
    Получает имя оператора по приоритету:
    1. Из транскрипции (когда консультант представляется)
    2. Из таблицы EMPLOYEE_BY_EXTENSION по коду станции
    
    Args:
        dialog_text: Текст диалога (опционально)
        station_code: Код станции
    
    Returns:
        Имя оператора или 'Не указано'
    """
    # Первично: пытаемся извлечь из транскрипции
    if dialog_text:
        name_from_transcript = extract_operator_name_from_transcript(dialog_text, station_code)
        if name_from_transcript:
            return name_from_transcript
    
    # Вторично: берем из таблицы привязки
    if station_code:
        employee_full = config.EMPLOYEE_BY_EXTENSION.get(station_code)
        if employee_full:
            # Берем только имя (первое слово)
            name = employee_full.split()[0] if employee_full else None
            if name:
                return name
    
    return 'Не указано'

def load_script_prompt_8(prompt_path: Path):
    """
    Читаем YAML, достаём общий 'prompt' и пункты чек-листа.
    Возвращает кортеж:
      (prompt_text: str, checklist_titles: list[str], checklist_prompts: list[str])
    """
    try:
        with prompt_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            prompt_text = str(data.get("prompt", ""))
            checklist = data.get("checklist") or []
            titles = []
            prompts = []
            for item in checklist:
                item = item or {}
                title = str(item.get("title", "")).strip()
                tip = str(item.get("prompt", "")).strip()
                if title:
                    titles.append(title)
                    prompts.append(tip)
            if not titles:
                return prompt_text, DEFAULT_QUESTIONS, [""] * len(DEFAULT_QUESTIONS)
            return prompt_text, titles, prompts
    except Exception as e:
        logger.error(f"[exental_alert] Ошибка чтения {prompt_path}: {e}")
        return "", DEFAULT_QUESTIONS, [""] * len(DEFAULT_QUESTIONS)

def call_theb_ai(dialog_text: str, script_prompt: str) -> str:
    """
    Запрос к TheB.ai (конфиг из config).
    """
    full_prompt = f"{script_prompt}\n\nВот диалог:\n{dialog_text}"
    headers = {
        "Authorization": f"Bearer {config.THEBAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": full_prompt}],
        #"stream": False
    }
    try:
        resp = requests.post(config.THEBAI_URL, headers=headers, json=payload, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        else:
            logger.error(f"[exental_alert] Ошибка TheB.ai: {resp.status_code} {resp.text}")
            return ""
    except Exception as e:
        logger.error(f"[exental_alert] Сетевая ошибка при запросе к TheB.ai: {e}")
        return ""

def parse_answers_and_form_message(analysis_text: str, station_code: str, phone_number: str, date_str: str, checklist_titles, dialog_text: str = None, checklist_prompts=None):
    """
    Ищем [ОТВЕТ: ДА/НЕТ] по количеству пунктов чек-листа. Если ответов нет — возвращаем (None, None).
    """
    # Нормируем количество вопросов
    total_q = max(1, len(checklist_titles) if checklist_titles else len(DEFAULT_QUESTIONS))
    # Пытаемся детерминированно вытащить ответы для каждого пункта 1..N
    answers = []
    for i in range(1, total_q + 1):
        m = re.search(rf"{i}\.\s.*?[\r\n]*\[ОТВЕТ:\s*(ДА|НЕТ)\]", analysis_text, re.IGNORECASE | re.DOTALL)
        ans = m.group(1).upper() if m else None
        answers.append(ans)

    # Если такой разметки нет, пробуем общий поиск всех ответов подряд
    if not any(a in ("ДА", "НЕТ") for a in answers):
        flat = re.findall(r"\[ОТВЕТ:\s*(ДА|НЕТ)\]", analysis_text, re.IGNORECASE)
        for idx in range(min(total_q, len(flat))):
            answers[idx] = flat[idx].upper()

    # Усечение/заполнение до нужной длины
    answers = [(a if a in ("ДА", "НЕТ") else "НЕТ") for a in answers[:total_q]]

    # ===== Точечные эвристики лишь для П3 (выявление потребностей) и П11 (инициативность) =====
    try:
        if dialog_text and checklist_titles:
            text_lower = dialog_text.lower()
            # Реплики менеджера (SPEAKER_01)
            manager_lines = []
            for line in dialog_text.splitlines():
                ls = line.strip()
                if ls.startswith("SPEAKER_01:") or ls.startswith("Speaker_01:"):
                    manager_lines.append(ls.split(":", 1)[1].strip().lower())
            manager_text = "\n".join(manager_lines) if manager_lines else text_lower

            for i, title in enumerate(checklist_titles[:len(answers)]):
                t = (title or "").lower()
                # П3: выявление потребностей — нужны открытые вопросы/уточнения
                if "потреб" in t or "выявлен" in t:
                    open_q_words = ("что", "как", "почему", "зачем", "кто", "когда", "сколько", "какой", "какие", "какую")
                    num_questions = manager_text.count("?")
                    num_open = sum(1 for w in open_q_words if f"{w} " in manager_text)
                    has_rephrase = ("правильно понимаю" in manager_text) or ("верно ли" in manager_text)
                    if not ((num_questions >= 2 and num_open >= 1) or has_rephrase):
                        answers[i] = "НЕТ"
                # П11: инициативность — явное предложение следующего шага
                if "инициатив" in t:
                    initiative_markers = (
                        "предлагаю", "давайте", "могу", "заброниру", "отправлю", "пришлю", "созвонимся", "назначим", "оформим", "держать цену"
                    )
                    has_marker = any(m in manager_text for m in initiative_markers)
                    if not has_marker:
                        answers[i] = "НЕТ"
    except Exception:
        pass

    qa_lines = []
    for i in range(total_q):
        title = checklist_titles[i] if i < len(checklist_titles) else f"Пункт {i+1}"
        qa_lines.append(f"{i+1}. {title} — {answers[i]}")
    qa_text = "\n".join(qa_lines)

    yes_count = sum(1 for a in answers if a == "ДА")
    percent_score = (yes_count / float(total_q)) * 100

    overall_match = re.search(r"<общая\s*оценка>(.*?)</общая\s*оценка>", analysis_text, re.IGNORECASE | re.DOTALL)
    overall = overall_match.group(1).strip() if overall_match else "Нет общего вывода."

    formatted_date = date_str
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d-%H-%M-%S")
        formatted_date = dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        pass

    station_name = config.STATION_NAMES.get(station_code, station_code)
    # Получаем имя оператора (приоритет: из транскрипции, затем из таблицы)
    operator_name = get_operator_name(dialog_text, station_code)
    
    # Короткий caption без общего вывода, чтобы не превышать лимит Telegram
    caption = (
        f"<b>Анализ звонка по чек-листу</b>\n"
        f"Станция: <b>{station_name}</b>\n"
        f"Оператор: <b>{operator_name}</b>\n"
        f"Номер: <b>{phone_number}</b>\n"
        f"Дата: <b>{formatted_date}</b>\n\n"
        f"Процент 'ДА': {percent_score:.1f}%\n\n"
        f"{qa_text}"
    )
    return caption, analysis_text, qa_text, overall

def save_analysis(txt_path: str, dialog_text: str, new_analysis: str, qa_text: str, overall_text: str) -> str:
    """
    Сохраняем итог расширенного анализа рядом (script_8/).
    """
    base_dir = os.path.dirname(txt_path)
    script_dir = os.path.join(base_dir, "script_8")
    if not os.path.exists(script_dir):
        os.makedirs(script_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(txt_path))[0]
    analysis_filename = f"{base_name}_analysis.txt"
    analysis_path = os.path.join(script_dir, analysis_filename)
    try:
        with open(analysis_path, "w", encoding="utf-8") as f:
            f.write("Диалог (из исходного TXT):\n\n")
            f.write(dialog_text)
            f.write("\n\nРаспознавание по чек-листу:\n\n")
            f.write(qa_text)
            f.write("\n\nИтог:\n\n")
            f.write(overall_text)
        logger.info(f"[exental_alert] Файл анализа сохранён: {analysis_path}")
    except Exception as e:
        logger.error(f"[exental_alert] Ошибка при сохранении {analysis_path}: {e}")
    return analysis_path

def guess_mp3_path(txt_path: str) -> str:
    """
    Пытаемся вывести путь к .mp3. Если TXT лежит в papke /transcriptions/,
    то mp3 обычно на уровень выше.
    """
    if not txt_path.lower().endswith(".txt"):
        return txt_path
    # Определяем базовое имя без расширения
    base_filename = os.path.splitext(os.path.basename(txt_path))[0]
    # Если TXT в папке transcriptions, оригинальный аудио файл на уровень выше
    if "transcriptions" in os.path.normpath(txt_path):
        parent_dir = os.path.dirname(os.path.dirname(txt_path))
    else:
        parent_dir = os.path.dirname(txt_path)

    # Пытаемся определить фактическое расширение аудио
    mp3_path = os.path.join(parent_dir, base_filename + ".mp3")
    wav_path = os.path.join(parent_dir, base_filename + ".wav")

    if os.path.isfile(mp3_path):
        return mp3_path
    if os.path.isfile(wav_path):
        return wav_path
    # Если ничего не найдено, по умолчанию возвращаем mp3-путь (для обратной совместимости)
    return mp3_path

def send_exental_results(station_code: str, caption: str, overall_text: str, mp3_path: str, analysis_path: str):
    """
    Отправляем аудио + (опционально) текстовый файл в чаты станции, взятые из config.
    """
    chat_list = config.STATION_CHAT_IDS.get(station_code, [config.ALERT_CHAT_ID])
    for cid in chat_list:
        audio_sent = False
        if os.path.isfile(mp3_path):
            audio_sent = send_telegram_audio(cid, mp3_path, caption)
        else:
            logger.warning(f"[exental_alert] MP3 {mp3_path} не найден, не отправляем аудио.")
        
        # Если аудио не удалось отправить, отправляем caption отдельным текстовым сообщением
        if not audio_sent:
            logger.info(f"[exental_alert] Отправляем caption как текстовое сообщение (аудио не отправлено)")
            send_telegram_message(cid, caption)

        # Вторым сообщением отправляем общий вывод (короткий текст)
        if overall_text:
            send_telegram_message(cid, f"<b>Общий вывод</b>: {overall_text}")

        # Если нужно отправлять txt (отключено по умолчанию)
        # send_telegram_document(cid, analysis_path, "<b>Дополнительный анализ (скрипт-8):</b>")

def send_telegram_audio(chat_id: str, audio_path: str, caption: str):
    """
    Отправляет аудио файл в Telegram чат.
    Возвращает True если успешно, False если не удалось.
    """
    if not ensure_telegram_ready("экстренное оповещение (аудио)"):
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendAudio"
    if not os.path.isfile(audio_path):
        logger.warning(f"[exental_alert] Аудио {audio_path} не найдено.")
        return False
    try:
        with open(audio_path, "rb") as f:
            files = {"audio": (os.path.basename(audio_path), f.read())}
            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            resp = requests.post(url, files=files, data=data, timeout=60)
        if resp.status_code == 200:
            logger.info(f"[exental_alert] Аудио {audio_path} отправлено в чат {chat_id}")
            return True
        else:
            logger.error(f"[exental_alert] Ошибка при отправке аудио: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        logger.error(f"[exental_alert] Исключение при отправке аудио {audio_path} в чат {chat_id}: {e}")
        return False

def send_telegram_message(chat_id: str, text: str):
    if not ensure_telegram_ready("экстренное оповещение (сообщение)"):
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        resp = requests.post(url, data=data, timeout=15)
        if resp.status_code == 200:
            logger.info(f"[exental_alert] Текстовое сообщение отправлено в чат {chat_id}")
        else:
            logger.error(f"[exental_alert] Ошибка при отправке сообщения: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"[exental_alert] Исключение при отправке сообщения в чат {chat_id}: {e}")

def send_telegram_document(chat_id: str, doc_path: str, caption: str):
    if not ensure_telegram_ready("экстренное оповещение (документ)"):
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendDocument"
    if not os.path.isfile(doc_path):
        logger.warning(f"[exental_alert] Документ {doc_path} не найден.")
        return
    try:
        with open(doc_path, "rb") as doc_file:
            files = {"document": doc_file}
            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            resp = requests.post(url, files=files, data=data, timeout=15)
        if resp.status_code == 200:
            logger.info(f"[exental_alert] Документ {doc_path} отправлен в чат {chat_id}")
        else:
            logger.error(f"[exental_alert] Ошибка при отправке документа: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"[exental_alert] Ошибка при отправке {doc_path} в чат {chat_id}: {e}")
