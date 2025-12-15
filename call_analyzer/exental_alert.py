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

def detect_manager_speaker(dialog_text: str) -> str:
    """
    Автоматически определяет, какой спикер является менеджером.
    Возвращает 'SPEAKER_00' или 'SPEAKER_01' (или 'SPEAKER_01' по умолчанию).
    
    Критерии определения менеджера:
    1. Первый спикер, который приветствует и называет компанию
    2. Спикер, который называет компанию/магазин/сервис
    3. Спикер, который называет должность (мастер приемщик, консультант и т.д.)
    4. Спикер, который представляется по имени
    5. Спикер, который говорит фразы типа "слушаю", "чем могу помочь"
    6. Кто говорит первым (обычно менеджер отвечает на звонок)
    """
    if not dialog_text:
        return "SPEAKER_01"  # По умолчанию
    
    lines = dialog_text.splitlines()
    speaker_00_score = 0
    speaker_01_score = 0
    
    # Признаки менеджера
    greeting_words = ["добрый день", "доброе утро", "добрый вечер", "здравствуйте", "здравствуй"]
    # Расширенный список слов компаний/сервисов
    company_words = [
        "магазин", "компания", "автосервис", "сервис", "автовектор", "фокус",
        "сервисный центр", "попутчик", "автоцентр", "техцентр", "сто",
        "автосалон", "дилер", "официальный дилер", "бествей"
    ]
    # Должности менеджеров/консультантов
    position_words = [
        "мастер приемщик", "мастер-приемщик", "приемщик", "консультант",
        "менеджер", "специалист", "оператор", "администратор"
    ]
    service_phrases = ["слушаю", "чем могу помочь", "готов вас выслушать", "спрос", "слушаю вас"]
    name_patterns = [r"меня зовут", r"я\s+\w+", r"это\s+\w+"]
    
    # Определяем, кто говорит первым (важный признак - менеджер обычно отвечает первым)
    first_speaker = None
    for line in lines[:10]:
        line_lower = line.lower().strip()
        if line_lower.startswith("speaker_00:") or line_lower.startswith("speaker_0:"):
            first_speaker = "SPEAKER_00"
            break
        elif line_lower.startswith("speaker_01:") or line_lower.startswith("speaker_1:"):
            first_speaker = "SPEAKER_01"
            break
    
    # Анализируем первые 10 реплик каждого спикера
    speaker_00_first_lines = []
    speaker_01_first_lines = []
    
    for line in lines[:30]:  # Первые 30 строк обычно содержат приветствие
        line_lower = line.lower().strip()
        if line_lower.startswith("speaker_00:") or line_lower.startswith("speaker_0:"):
            text = line.split(":", 1)[1].strip().lower() if ":" in line else ""
            speaker_00_first_lines.append(text)
        elif line_lower.startswith("speaker_01:") or line_lower.startswith("speaker_1:"):
            text = line.split(":", 1)[1].strip().lower() if ":" in line else ""
            speaker_01_first_lines.append(text)
    
    # Объединяем первые реплики для анализа (берем первые 3 реплики для более точного анализа)
    speaker_00_text = " ".join(speaker_00_first_lines[:3])
    speaker_01_text = " ".join(speaker_01_first_lines[:3])
    
    # Проверяем SPEAKER_00
    has_greeting_00 = False
    has_company_00 = False
    has_position_00 = False
    has_name_00 = False
    
    for word in greeting_words:
        if word in speaker_00_text:
            speaker_00_score += 2
            has_greeting_00 = True
    for word in company_words:
        if word in speaker_00_text:
            speaker_00_score += 4  # Увеличиваем вес
            has_company_00 = True
    for word in position_words:
        if word in speaker_00_text:
            speaker_00_score += 5  # Должность - очень сильный признак
            has_position_00 = True
    for phrase in service_phrases:
        if phrase in speaker_00_text:
            speaker_00_score += 2
    for pattern in name_patterns:
        if re.search(pattern, speaker_00_text):
            speaker_00_score += 2
            has_name_00 = True
    
    # Бонус за комбинацию признаков (компания + приветствие + имя = очень сильный признак)
    if has_company_00 and has_greeting_00:
        speaker_00_score += 3
    if has_company_00 and has_greeting_00 and has_name_00:
        speaker_00_score += 5  # Максимальный бонус за полное представление
    
    # Бонус за то, что говорит первым (если при этом есть приветствие или компания)
    if first_speaker == "SPEAKER_00" and (has_greeting_00 or has_company_00):
        speaker_00_score += 3
    
    # Проверяем SPEAKER_01
    has_greeting_01 = False
    has_company_01 = False
    has_position_01 = False
    has_name_01 = False
    
    for word in greeting_words:
        if word in speaker_01_text:
            speaker_01_score += 2
            has_greeting_01 = True
    for word in company_words:
        if word in speaker_01_text:
            speaker_01_score += 4
            has_company_01 = True
    for word in position_words:
        if word in speaker_01_text:
            speaker_01_score += 5
            has_position_01 = True
    for phrase in service_phrases:
        if phrase in speaker_01_text:
            speaker_01_score += 2
    for pattern in name_patterns:
        if re.search(pattern, speaker_01_text):
            speaker_01_score += 2
            has_name_01 = True
    
    # Бонус за комбинацию признаков
    if has_company_01 and has_greeting_01:
        speaker_01_score += 3
    if has_company_01 and has_greeting_01 and has_name_01:
        speaker_01_score += 5
    
    # Бонус за то, что говорит первым
    if first_speaker == "SPEAKER_01" and (has_greeting_01 or has_company_01):
        speaker_01_score += 3
    
    # Если SPEAKER_00 набрал больше баллов, он менеджер
    if speaker_00_score > speaker_01_score:
        logger.info(f"[exental_alert] Определен менеджер: SPEAKER_00 (баллы: {speaker_00_score} vs {speaker_01_score})")
        return "SPEAKER_00"
    else:
        logger.info(f"[exental_alert] Определен менеджер: SPEAKER_01 (баллы: {speaker_01_score} vs {speaker_00_score})")
        return "SPEAKER_01"

def run_exental_alert(txt_path: str, station_code: str, phone_number: str, date_str: str, operator_station_code: str = None):
    """
    Точка входа для расширенного анализа и отправки сообщения,
    заменяет exental_alert.exe.
    
    Args:
        txt_path: Путь к файлу транскрипции
        station_code: Основной код станции (для отправки в чаты)
        phone_number: Номер телефона
        date_str: Дата и время звонка
        operator_station_code: Оригинальный код станции из имени файла (может быть подстанцией, используется для определения оператора)
    """
    logger.info(f"[exental_alert] Запуск. txt={txt_path}, station={station_code}, phone={phone_number}, date={date_str}")

    dialog_text = extract_dialog_from_txt(txt_path)
    if not dialog_text.strip():
        logger.warning("[exental_alert] Диалог пуст, завершаем.")
        return

    # Получаем путь к script_prompt_8.yaml из конфигурации пользователя
    # Приоритет: 1) PROFILE_SETTINGS, 2) SCRIPT_PROMPT_8_PATH из config
    script_prompt_8 = None
    if hasattr(config, 'PROFILE_SETTINGS') and config.PROFILE_SETTINGS:
        paths_cfg = config.PROFILE_SETTINGS.get('paths') or {}
        script_prompt_file = paths_cfg.get('script_prompt_file')
        if script_prompt_file:
            script_prompt_8 = Path(script_prompt_file)
            logger.debug(f"[exental_alert] Используется script_prompt_file из PROFILE_SETTINGS: {script_prompt_8}")
    
    if not script_prompt_8 or not script_prompt_8.exists():
        # Fallback на SCRIPT_PROMPT_8_PATH из config
        script_prompt_8 = config.SCRIPT_PROMPT_8_PATH
        logger.debug(f"[exental_alert] Используется SCRIPT_PROMPT_8_PATH из config: {script_prompt_8}")
    
    # Логируем, какой файл будет использоваться
    logger.info(f"[exental_alert] Используется файл чек-листа: {script_prompt_8} (существует: {script_prompt_8.exists()})")
    
    # Автоматическое создание файла промпта, если он отсутствует
    if not script_prompt_8.exists():
        try:
            logger.info(f"[exental_alert] Файл промпта {script_prompt_8} не найден. Создаю файл по умолчанию.")
            script_prompt_8.parent.mkdir(parents=True, exist_ok=True)
            
            default_content = """checklist:
  - title: "1. Приветствие"
    prompt: "Консультант поздоровался и представился"
  - title: "2. Выявление потребности"
    prompt: "Консультант задал уточняющие вопросы"
  - title: "3. Результат"
    prompt: "Клиент записан или договорились о звонке"

prompt: |
  Оцени звонок по пунктам чек-листа ниже. Для КАЖДОГО пункта ответь строго формой '[ОТВЕТ: ДА]' или '[ОТВЕТ: НЕТ]' без дополнительных слов после него.

  После всех ответов добавь блок <общая оценка>... </общая оценка> с кратким выводом.

  Если пункт неприменим, ставь '[ОТВЕТ: НЕТ]'.

  Чек-лист:
  1. Приветствие
  2. Выявление потребности
  3. Результат
"""
            with script_prompt_8.open("w", encoding="utf-8") as f:
                f.write(default_content)
        except Exception as e:
            logger.error(f"[exental_alert] Не удалось создать файл промпта по умолчанию: {e}")
            return

    if not script_prompt_8.exists():
        logger.error(f"[exental_alert] Файл промпта {script_prompt_8} всё ещё не найден.")
        return
        
    prompt_8, checklist_titles, checklist_prompts = load_script_prompt_8(script_prompt_8)
    if not prompt_8.strip():
        logger.warning("[exental_alert] Пустой prompt_8, завершаем.")
        return

    # Автоматически определяем, кто является менеджером
    manager_speaker = detect_manager_speaker(dialog_text)
    logger.info(f"[exental_alert] Используется менеджер: {manager_speaker}")

    # Дополним общий промпт подсказками по каждому пункту чек-листа,
    # чтобы модели было проще детектировать признаки выполнения.
    if checklist_titles:
        hints_lines = [
            "Правила оценивания (строго соблюдать):",
            f"1) Учитывай ТОЛЬКО реплики менеджера ({manager_speaker}).",
            "2) Если признаков недостаточно или сомневаешься — ставь [ОТВЕТ: НЕТ].",
            "3) Формат ответа — одна строка на пункт в порядке 1..N:",
            f"   'i. <Название пункта> [ОТВЕТ: ДА|НЕТ] [ОБОСНОВАНИЕ: кратко, цитаты/парафразы {manager_speaker}]'.",
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

    # Используем оригинальный код станции для определения оператора, если он передан
    operator_station = operator_station_code if operator_station_code else station_code
    
    # Передаем определенного менеджера в функцию парсинга
    # Используем operator_station для определения оператора в сообщении
    caption, raw_analysis, qa_text, overall = parse_answers_and_form_message(
        new_analysis, station_code, phone_number, date_str, checklist_titles, dialog_text, checklist_prompts, manager_speaker, operator_station_code=operator_station
    )
    if not caption:
        logger.warning("[exental_alert] Недостаточно ответов для формирования сообщения.")
        return

    analysis_path = save_analysis(txt_path, dialog_text, new_analysis, qa_text, overall)
    logger.info(f"[exental_alert] Итоговый анализ сохранён: {analysis_path}")
    
    mp3_path = guess_mp3_path(txt_path)
    send_exental_results(station_code, caption, overall, mp3_path, analysis_path)
    
    logger.info("[exental_alert] Завершено.")
    # Возвращаем данные разбора для использования в веб-интерфейсе (страница тестирования чек-листов)
    return caption, raw_analysis, qa_text, overall


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
    Автоматически определяет менеджера и ищет в его первых репликах фразы с представлением.
    Если имя не найдено, возвращает None.
    
    Args:
        dialog_text: Текст диалога с репликами вида "SPEAKER_XX: текст"
        station_code: Код станции для fallback (опционально)
    
    Returns:
        Имя оператора (только имя, без фамилии) или None
    """
    if not dialog_text:
        return None
    
    # Автоматически определяем менеджера
    manager_speaker = detect_manager_speaker(dialog_text)
    
    # Ищем первые 5 реплик менеджера (обычно там происходит представление)
    lines = dialog_text.splitlines()
    manager_first_lines = []
    count = 0
    manager_patterns = [
        manager_speaker + ":",
        manager_speaker.lower() + ":",
        manager_speaker.replace("_", "_0") + ":" if "_0" not in manager_speaker else manager_speaker + ":"
    ]
    for line in lines:
        line_stripped = line.strip()
        if any(line_stripped.startswith(pattern) for pattern in manager_patterns) and count < 5:
            # Извлекаем текст после "SPEAKER_XX:"
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
    1. Если включено автоматическое определение: из транскрипции (когда консультант представляется), затем из таблицы
    2. Если выключено: сразу из таблицы EMPLOYEE_BY_EXTENSION по коду станции
    
    Args:
        dialog_text: Текст диалога (опционально)
        station_code: Код станции
    
    Returns:
        Имя оператора или 'Не указано'
    """
    # Проверяем настройку автоматического определения имени оператора
    auto_detect = getattr(config, 'AUTO_DETECT_OPERATOR_NAME', True)
    
    # Если автоматическое определение включено, пытаемся извлечь из транскрипции
    if auto_detect and dialog_text:
        name_from_transcript = extract_operator_name_from_transcript(dialog_text, station_code)
        if name_from_transcript:
            return name_from_transcript
    
    # Берем из таблицы привязки (всегда как fallback или если автоматическое определение выключено)
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

def parse_answers_and_form_message(analysis_text: str, station_code: str, phone_number: str, date_str: str, checklist_titles, dialog_text: str = None, checklist_prompts=None, manager_speaker: str = "SPEAKER_01", operator_station_code: str = None):
    """
    Ищем [ОТВЕТ: ДА/НЕТ] по количеству пунктов чек-листа. Если ответов нет — возвращаем (None, None).
    
    Args:
        manager_speaker: Спикер, который является менеджером (SPEAKER_00 или SPEAKER_01)
        operator_station_code: Оригинальный код станции для определения оператора (может быть подстанцией)
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
            # Реплики менеджера (используем определенного спикера)
            manager_lines = []
            manager_patterns = [
                manager_speaker + ":",
                manager_speaker.lower() + ":",
                manager_speaker.replace("_", "_0") + ":" if "_0" not in manager_speaker else manager_speaker + ":"
            ]
            for line in dialog_text.splitlines():
                ls = line.strip()
                # Проверяем все возможные варианты написания спикера
                if any(ls.startswith(pattern) for pattern in manager_patterns):
                    manager_lines.append(ls.split(":", 1)[1].strip().lower() if ":" in ls else ls.lower())
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
        # Добавляем эмодзи в зависимости от ответа
        emoji = "🟢" if answers[i] == "ДА" else "🔴"
        qa_lines.append(f"{i+1}. {emoji} {title} — {answers[i]}")
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
    # Используем оригинальный код станции для определения оператора, если он передан
    operator_station = operator_station_code if operator_station_code else station_code
    operator_name = get_operator_name(dialog_text, operator_station)
    
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
    Использует Path для кроссплатформенности и правильной обработки путей.
    """
    # Используем Path для кроссплатформенности и нормализации путей
    txt_path_obj = Path(txt_path)
    
    # Нормализуем путь для получения абсолютного пути (важно для Ubuntu)
    try:
        txt_path_obj = txt_path_obj.resolve()
    except (OSError, ValueError):
        # Если не удалось разрешить, используем как есть
        pass
    
    # base_dir - это директория, где находится txt файл (обычно transcriptions/)
    base_dir = txt_path_obj.parent
    script_dir = base_dir / "script_8"
    
    # Создаем директорию script_8 если её нет
    script_dir.mkdir(parents=True, exist_ok=True)
    
    # Нормализуем путь script_dir для единообразия
    try:
        script_dir = script_dir.resolve()
    except (OSError, ValueError):
        pass

    # Получаем базовое имя файла без расширения
    base_name = txt_path_obj.stem
    analysis_filename = f"{base_name}_analysis.txt"
    analysis_path = script_dir / analysis_filename
    
    try:
        with analysis_path.open("w", encoding="utf-8") as f:
            f.write("Диалог (из исходного TXT):\n\n")
            f.write(dialog_text)
            f.write("\n\nРаспознавание по чек-листу:\n\n")
            f.write(qa_text)
            f.write("\n\nИтог:\n\n")
            f.write(overall_text)
        logger.info(f"[exental_alert] Файл анализа сохранён: {analysis_path}")
    except Exception as e:
        logger.error(f"[exental_alert] Ошибка при сохранении {analysis_path}: {e}")
    return str(analysis_path)

def guess_mp3_path(txt_path: str) -> str:
    """
    Пытаемся вывести путь к .mp3. Если TXT лежит в папке /transcriptions/,
    то mp3 обычно на уровень выше.
    Использует Path для кроссплатформенности (Windows/Ubuntu).
    """
    if not txt_path.lower().endswith(".txt"):
        return txt_path
    
    # Используем Path для кроссплатформенности
    txt_path_obj = Path(txt_path)
    
    # Нормализуем путь для получения абсолютного пути (важно для Ubuntu)
    try:
        txt_path_obj = txt_path_obj.resolve()
    except (OSError, ValueError):
        # Если не удалось разрешить, используем как есть
        pass
    
    # Определяем базовое имя без расширения
    base_filename = txt_path_obj.stem
    
    # Если TXT в папке transcriptions, оригинальный аудио файл на уровень выше
    if "transcriptions" in str(txt_path_obj):
        parent_dir = txt_path_obj.parent.parent
    else:
        parent_dir = txt_path_obj.parent

    # Пытаемся определить фактическое расширение аудио
    mp3_path = parent_dir / (base_filename + ".mp3")
    wav_path = parent_dir / (base_filename + ".wav")
    
    # Нормализуем пути для проверки существования
    try:
        mp3_path = mp3_path.resolve()
    except (OSError, ValueError):
        pass
    try:
        wav_path = wav_path.resolve()
    except (OSError, ValueError):
        pass

    if mp3_path.exists() and mp3_path.is_file():
        return str(mp3_path)
    if wav_path.exists() and wav_path.is_file():
        return str(wav_path)
    # Если ничего не найдено, по умолчанию возвращаем mp3-путь (для обратной совместимости)
    return str(mp3_path)

def send_exental_results(station_code: str, caption: str, overall_text: str, mp3_path: str, analysis_path: str):
    """
    Отправляем аудио + (опционально) текстовый файл в чаты станции, взятые из config.
    """
    chat_list = config.STATION_CHAT_IDS.get(station_code, [config.ALERT_CHAT_ID])
    for cid in chat_list:
        audio_sent = False
        # Используем Path для кроссплатформенности
        mp3_path_obj = Path(mp3_path)
        # Нормализуем путь для проверки существования (важно для Ubuntu)
        try:
            mp3_path_obj = mp3_path_obj.resolve()
        except (OSError, ValueError):
            pass
        
        if mp3_path_obj.exists() and mp3_path_obj.is_file():
            audio_sent = send_telegram_audio(cid, str(mp3_path_obj), caption)
        else:
            logger.warning(f"[exental_alert] MP3 {mp3_path_obj} не найден, не отправляем аудио.")
        
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
