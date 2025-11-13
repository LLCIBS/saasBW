# call_analyzer/resend_analyses.py

import os
import sys
import re
import logging
from pathlib import Path
from datetime import datetime

# Добавляем путь к модулям call_analyzer
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

import config
from exental_alert import send_exental_results, guess_mp3_path, send_telegram_message, get_operator_name, extract_dialog_from_txt

logger = logging.getLogger(__name__)

def parse_analysis_file(analysis_path: str):
    """
    Парсит файл анализа и извлекает qa_text и overall_text.
    """
    with open(analysis_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Разделяем на секции
    parts = content.split("\n\nРаспознавание по чек-листу:\n\n")
    if len(parts) < 2:
        return None, None
    
    qa_and_overall = parts[1]
    parts2 = qa_and_overall.split("\n\nИтог:\n\n")
    
    qa_text = parts2[0].strip() if len(parts2) > 0 else ""
    overall_text = parts2[1].strip() if len(parts2) > 1 else ""
    
    return qa_text, overall_text

def extract_info_from_filename(filename: str):
    """
    Извлекает station_code, phone_number, date_str из имени файла анализа.
    Поддерживает форматы: вход_*, fs_*, external-*, in-*
    """
    base_name = filename.replace("_analysis.txt", "")
    
    # Формат: вход_StationNameStationCode_с_phone_на_to_от_YYYY_MM_DD
    match = re.match(r'вход_[^_]+(\d+)_с_(\d+)_на_\d+_от_(\d{4})_(\d{1,2})_(\d{1,2})', base_name)
    if match:
        station_code = match.group(1)
        phone_number = "+" + match.group(2)
        year = match.group(3)
        month = match.group(4).zfill(2)
        day = match.group(5).zfill(2)
        # Используем 00-00-00 для времени, так как точное время не в имени файла
        date_str = f"{year}-{month}-{day}-00-00-00"
        return station_code, phone_number, date_str
    
    # Формат: fs_phone_station_YYYY-MM-DD-HH-MM-SS
    match = re.match(r'fs_(\+?\d+)_(\d+)_(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})', base_name)
    if match:
        phone_number = match.group(1)
        if not phone_number.startswith("+"):
            phone_number = "+" + phone_number
        station_code = match.group(2)
        date_str = match.group(3)
        return station_code, phone_number, date_str
    
    # Формат: external-station-phone-YYYYMMDD-HHMMSS
    match = re.match(r'external-(\d+)-(\d+)-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})', base_name)
    if match:
        station_code = match.group(1)
        phone_number = "+" + match.group(2)
        date_str = f"{match.group(3)}-{match.group(4)}-{match.group(5)}-{match.group(6)}-{match.group(7)}-{match.group(8)}"
        return station_code, phone_number, date_str
    
    # Формат: in-station-phone-YYYYMMDD-HHMMSS
    match = re.match(r'in-(\d+)-(\d+)-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})', base_name)
    if match:
        station_code = match.group(1)
        phone_number = "+" + match.group(2)
        date_str = f"{match.group(3)}-{match.group(4)}-{match.group(5)}-{match.group(6)}-{match.group(7)}-{match.group(8)}"
        return station_code, phone_number, date_str
    
    return None, None, None

def calculate_percent_score(qa_text: str):
    """
    Подсчитывает процент 'ДА' из qa_text.
    Формат: "1. Название — ДА" или "1. Название — НЕТ"
    """
    lines = qa_text.split("\n")
    total = 0
    yes_count = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Ищем паттерн "— ДА" или "— НЕТ"
        if "—" in line:
            total += 1
            if "— ДА" in line.upper():
                yes_count += 1
    
    if total == 0:
        return 0.0
    return (yes_count / total) * 100

def recreate_caption(station_code: str, phone_number: str, date_str: str, qa_text: str, dialog_text: str = None):
    """
    Воссоздает caption из сохраненных данных.
    
    Args:
        station_code: Код станции
        phone_number: Номер телефона
        date_str: Строка даты
        qa_text: Текст вопросов-ответов
        dialog_text: Текст диалога (опционально, для извлечения имени оператора)
    """
    station_name = config.STATION_NAMES.get(station_code, station_code)
    percent_score = calculate_percent_score(qa_text)
    
    formatted_date = date_str
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d-%H-%M-%S")
        formatted_date = dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        pass
    
    # Получаем имя оператора (приоритет: из транскрипции, затем из таблицы)
    operator_name = get_operator_name(dialog_text, station_code)
    
    caption = (
        f"<b>Анализ звонка по чек-листу</b>\n"
        f"Станция: <b>{station_name}</b>\n"
        f"Оператор: <b>{operator_name}</b>\n"
        f"Номер: <b>{phone_number}</b>\n"
        f"Дата: <b>{formatted_date}</b>\n\n"
        f"Процент 'ДА': {percent_score:.1f}%\n\n"
        f"{qa_text}"
    )
    return caption

def resend_analysis_files(base_path: str = None, today_only: bool = True):
    """
    Находит все файлы *_analysis.txt и переотправляет их в чат.
    
    Args:
        base_path: Базовый путь для поиска (по умолчанию config.BASE_RECORDS_PATH)
        today_only: Если True, переотправляет только файлы за сегодняшний день
    """
    if base_path is None:
        base_path = str(config.BASE_RECORDS_PATH)
    
    # Находим все файлы анализа
    analysis_files = []
    today_subdir = datetime.now().strftime("%Y/%m/%d")
    
    for root, dirs, files in os.walk(base_path):
        if "script_8" in root:
            # Если today_only=True, проверяем что путь содержит сегодняшнюю дату
            if today_only and today_subdir.replace("/", os.sep) not in root:
                continue
            for file in files:
                if file.endswith("_analysis.txt"):
                    analysis_files.append(os.path.join(root, file))
    
    logger.info(f"Найдено {len(analysis_files)} файлов анализа для переотправки")
    
    success_count = 0
    error_count = 0
    
    for analysis_path in analysis_files:
        try:
            # Парсим файл
            qa_text, overall_text = parse_analysis_file(analysis_path)
            if not qa_text:
                logger.warning(f"Не удалось извлечь qa_text из {analysis_path}")
                error_count += 1
                continue
            
            # Извлекаем информацию из имени файла
            filename = os.path.basename(analysis_path)
            station_code, phone_number, date_str = extract_info_from_filename(filename)
            
            if not station_code or not phone_number:
                logger.warning(f"Не удалось извлечь station_code/phone_number из {filename}")
                error_count += 1
                continue
            
            # Находим txt файл для извлечения диалога
            # Анализ лежит в script_8/, исходный txt на уровень выше в transcriptions/
            # Используем os.path для корректной работы с путями
            analysis_dir = os.path.dirname(analysis_path)
            parent_dir = os.path.dirname(analysis_dir)  # Выходим из script_8
            base_name = os.path.splitext(os.path.basename(analysis_path))[0].replace("_analysis", "")
            txt_path = os.path.join(parent_dir, "transcriptions", base_name + ".txt")
            
            # Извлекаем диалог из txt файла для определения имени оператора
            dialog_text = None
            if os.path.exists(txt_path):
                try:
                    dialog_text = extract_dialog_from_txt(txt_path)
                except Exception as e:
                    logger.warning(f"Не удалось извлечь диалог из {txt_path}: {e}")
            
            # Воссоздаем caption с именем оператора
            caption = recreate_caption(station_code, phone_number, date_str, qa_text, dialog_text)
            
            mp3_path = guess_mp3_path(txt_path)
            
            # Отправляем
            send_exental_results(station_code, caption, overall_text, mp3_path, analysis_path)
            success_count += 1
            logger.info(f"Успешно переотправлен: {filename}")
            
        except Exception as e:
            logger.error(f"Ошибка при обработке {analysis_path}: {e}")
            error_count += 1
    
    logger.info(f"Переотправка завершена. Успешно: {success_count}, Ошибок: {error_count}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger.info("Начинаем переотправку файлов анализа за сегодняшний день...")
    resend_analysis_files(today_only=True)
