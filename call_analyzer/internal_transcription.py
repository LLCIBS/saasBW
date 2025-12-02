import logging
import os
import time
import requests
import json
import config

logger = logging.getLogger(__name__)

def transcribe_audio_with_internal_service(file_path, stereo_mode=None, additional_vocab=None):
    """
    Транскрибирует аудио файл используя внутренний сервис Whisper/PyAnnote.
    Возвращает отформатированный текст транскрипции или None в случае ошибки.
    
    Args:
        file_path: Путь к аудио файлу
        stereo_mode: Если True - стерео режим (2 спикера, диаризация по каналам),
                     Если False - моно режим. Если None - берется из config.TBANK_STEREO_ENABLED
        additional_vocab: Список дополнительных слов для улучшения распознавания (опционально)
    """
    if not os.path.exists(file_path):
        logger.error(f"Файл '{file_path}' не найден.")
        return None

    api_url = config.INTERNAL_TRANSCRIPTION_URL
    
    # Определяем режим стерео/моно
    if stereo_mode is None:
        stereo_mode = getattr(config, 'TBANK_STEREO_ENABLED', False)
    
    mode_str = "стерео" if stereo_mode else "моно"
    logger.info(f"Начало транскрипции через внутренний сервис ({mode_str} режим): {api_url} для файла {file_path}")

    start_time = time.time()

    try:
        with open(file_path, "rb") as f:
            files = {"file": f}
            # Передаем флаг стерео/моно через data параметр
            data = {"stereo": "true" if stereo_mode else "false"}
            
            # Передаем дополнительный словарь, если он указан
            if additional_vocab and isinstance(additional_vocab, list) and len(additional_vocab) > 0:
                # Преобразуем список в JSON строку для передачи
                data["vocab"] = json.dumps(additional_vocab, ensure_ascii=False)
                logger.info(f"Передаем словарь из {len(additional_vocab)} слов на сервер транскрипции: {', '.join(additional_vocab[:5])}{'...' if len(additional_vocab) > 5 else ''}")
            else:
                logger.debug("Словарь не передан (пустой или не указан)")
            
            logger.info(f"Отправка файла на сервер (режим: {mode_str})...")
            
            # timeout=600 (10 минут) - достаточно для большинства файлов
            response = requests.post(api_url, files=files, data=data, timeout=600) 

        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "success":
                duration = time.time() - start_time
                logger.info(f"Транскрипция успешно завершена за {duration:.2f} сек.")
                return format_transcription_result(result["data"])
            else:
                logger.error(f"Ошибка API транскрипции: {result}")
                return None
        else:
            logger.error(f"Ошибка сервера транскрипции: {response.status_code} - {response.text}")
            return None

    except requests.exceptions.ConnectionError:
        logger.error("Ошибка: Не удалось подключиться к серверу транскрипции. Проверьте IP и запущен ли сервис.")
        return None
    except requests.exceptions.ReadTimeout:
        logger.error("Ошибка: Сервер транскрипции не ответил за 10 минут.")
        return None
    except Exception as e:
        logger.error(f"Произошла ошибка при транскрипции: {e}")
        return None

def format_transcription_result(data):
    """Форматирует JSON результат в строку диалога."""
    lines = []
    current_speaker = None
    current_text_buffer = []
    
    for segment in data:
        speaker = segment.get('speaker', 'Unknown')
        text = segment.get('text', '').strip()
        
        if not text:
            continue
            
        if speaker != current_speaker:
            if current_speaker is not None:
                lines.append(f"{current_speaker}: {' '.join(current_text_buffer)}")
            current_speaker = speaker
            current_text_buffer = [text]
        else:
            current_text_buffer.append(text)
            
    if current_speaker is not None:
        lines.append(f"{current_speaker}: {' '.join(current_text_buffer)}")
        
    return "\n".join(lines)

