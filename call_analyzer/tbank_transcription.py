# call_analyzer/tbank_transcription.py

import logging
import os
import time
import wave
import grpc
import jwt
from pathlib import Path
from typing import Tuple
import sys
from pydub import AudioSegment
import numpy as np
import config

# Workaround для совместимости со старыми сгенерированными protobuf файлами
# Используем pure-Python реализацию protobuf для избежания ошибки "Descriptors cannot be created directly"
if "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION" not in os.environ:
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

logger = logging.getLogger(__name__)


def _install_message_to_dict_compat():
    """
    Устанавливает совместимую версию MessageToDict, которая корректно работает
    с protobuf < 3.20 (без параметра including_default_value_fields).
    """
    try:
        from google.protobuf.json_format import MessageToDict as _base_message_to_dict
        from tinkoff_voicekit_client.speech_utils import infrastructure as _infra  # type: ignore
    except Exception as exc:
        logger.debug("Не удалось включить совместимость MessageToDict: %s", exc)
        return

    def _compat_message_to_dict(message, **kwargs):
        try:
            return _base_message_to_dict(message, **kwargs)
        except TypeError:
            kwargs.pop("including_default_value_fields", None)
            return _base_message_to_dict(message, **kwargs)

    _infra.MessageToDict = _compat_message_to_dict


_install_message_to_dict_compat()

# Ленивый импорт для избежания проблем с зависимостями при старте
_ClientSTT = None

def _get_client_stt():
    """Ленивая загрузка ClientSTT для избежания проблем с импортом при старте"""
    global _ClientSTT
    if _ClientSTT is None:
        try:
            from tinkoff_voicekit_client import ClientSTT as _ClientSTT_class
            _ClientSTT = _ClientSTT_class
        except ImportError as e:
            logger.error(f"Не удалось импортировать ClientSTT: {e}")
            raise ImportError(
                "Не удалось загрузить tinkoff_voicekit_client. "
                "Убедитесь, что установлены все зависимости: pip install tinkoff-voicekit-client boto3"
            ) from e
        except Exception as e:
            logger.error(f"Неожиданная ошибка при импорте ClientSTT: {e}")
            raise
    return _ClientSTT


def _authorization_metadata(api_key: str, secret_key: str, scope: str = "tinkoff.cloud.stt"):
    """Создает метаданные авторизации для gRPC"""
    now = int(time.time())
    payload = {"iss": api_key, "sub": api_key, "aud": scope, "exp": now + 3600, "iat": now}
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    return [("authorization", f"Bearer {token}")]


def _streaming_recognize_with_diarization(temp_path: Path, sample_rate: int, channels: int, 
                                          api_key: str, secret_key: str) -> dict:
    """
    Выполняет потоковое распознавание с встроенной диаризацией T-Bank через gRPC StreamingRecognize.
    
    Returns:
        dict: Ответ с распознаванием и диаризацией
    """
    try:
        # Импортируем protobuf модули для gRPC
        try:
            from tinkoff.cloud.stt.v1 import stt_pb2, stt_pb2_grpc
        except ImportError:
            logger.error("Не удалось импортировать protobuf модули для StreamingRecognize")
            logger.info("Попытка использовать синхронный метод recognize() с enable_diarization")
            return None
        
        VOICEKIT_ENDPOINT = os.getenv("VOICEKIT_ENDPOINT", "api.tinkoff.ai:443")
        
        # Создаем gRPC канал
        channel = grpc.secure_channel(VOICEKIT_ENDPOINT, grpc.ssl_channel_credentials())
        stub = stt_pb2_grpc.SpeechToTextStub(channel)
        
        # Создаем метаданные авторизации
        metadata = _authorization_metadata(api_key, secret_key)
        
        # Функция для генерации запросов
        def gen_requests(frame_ms: int = 100):
            # Первый запрос - конфигурация
            req = stt_pb2.StreamingRecognizeRequest()
            cfg = req.streaming_config.config
            
            cfg.encoding = stt_pb2.AudioEncoding.LINEAR16
            cfg.sample_rate_hertz = sample_rate
            cfg.num_channels = channels
            cfg.language_code = "ru-RU"
            
            # Ключевые флаги для диаризации
            cfg.enable_automatic_punctuation = True
            cfg.enable_diarization = True  # Включаем встроенную диаризацию
            cfg.do_not_perform_vad = False
            cfg.vad_config.silence_duration_threshold = 0.6
            
            # Промежуточные результаты не нужны
            req.streaming_config.interim_results_config.enable_interim_results = False
            
            yield req
            
            # Читаем файл и отправляем чанками
            with wave.open(str(temp_path), "rb") as wf:
                samples_per_frame = sample_rate * frame_ms // 1000
                bytes_per_frame = samples_per_frame * channels * wf.getsampwidth()
                
                while True:
                    data = wf.readframes(samples_per_frame)
                    if not data:
                        break
                    req = stt_pb2.StreamingRecognizeRequest()
                    req.audio_content = data
                    yield req
        
        # Выполняем потоковое распознавание
        logger.info("Начинаем потоковое распознавание с диаризацией...")
        responses = stub.StreamingRecognize(gen_requests(), metadata=metadata)
        
        # Собираем результаты
        all_results = []
        for resp in responses:
            for r in resp.results:
                if r.is_final and r.recognition_result:
                    all_results.append(r.recognition_result)
        
        # Формируем ответ в формате, совместимом с синхронным API
        response_dict = {
            "results": []
        }
        
        for rr in all_results:
            if rr.alternatives:
                result_dict = {
                    "alternatives": []
                }
                for alt in rr.alternatives:
                    alt_dict = {
                        "transcript": alt.transcript,
                        "words": []
                    }
                    # Обрабатываем слова с метками спикеров
                    if alt.words:
                        for word in alt.words:
                            word_dict = {
                                "word": word.word,
                                "start_time": f"{word.start_time.seconds + word.start_time.nanos / 1e9:.3f}s",
                                "end_time": f"{word.end_time.seconds + word.end_time.nanos / 1e9:.3f}s"
                            }
                            # Пробуем разные варианты названий полей для метки спикера
                            speaker_tag = None
                            if hasattr(word, "speaker_tag"):
                                speaker_tag = word.speaker_tag
                            elif hasattr(word, "speaker"):
                                speaker_tag = word.speaker
                            elif hasattr(word, "speaker_label"):
                                speaker_tag = word.speaker_label
                            
                            word_dict["speaker_tag"] = speaker_tag if speaker_tag is not None else 0
                            alt_dict["words"].append(word_dict)
                    result_dict["alternatives"].append(alt_dict)
                response_dict["results"].append(result_dict)
        
        logger.info(f"Потоковое распознавание завершено, получено {len(response_dict['results'])} результатов")
        return response_dict
        
    except Exception as e:
        logger.error(f"Ошибка при потоковом распознавании: {e}", exc_info=True)
        return None


def detect_call_type(audio: AudioSegment, min_channel_energy_ratio: float = 0.3, 
                     min_channel_difference: float = 0.15) -> Tuple[bool, dict]:
    """
    Автоматически определяет тип звонка (моно/стерео) на основе анализа аудио.
    
    Анализирует различия между каналами:
    - Если каналов < 2, возвращает False (моно)
    - Если каналов == 2, анализирует энергию и различия между каналами
    - Если каналы сильно различаются (разные спикеры), возвращает True (стерео)
    - Если каналы похожи (дублирование моно), возвращает False (моно)
    
    Args:
        audio: AudioSegment для анализа
        min_channel_energy_ratio: Минимальное соотношение энергии между каналами (0.0-1.0)
        min_channel_difference: Минимальная разница между каналами для определения стерео (0.0-1.0)
    
    Returns:
        Tuple[bool, dict]: (is_stereo, analysis_info)
            - is_stereo: True если стерео (реальные различия), False если моно
            - analysis_info: Словарь с деталями анализа
    """
    try:
        channels = audio.channels
        
        # Если каналов меньше 2, точно моно
        if channels < 2:
            return False, {
                "channels": channels,
                "reason": "Моно аудио (1 канал)",
                "is_stereo": False
            }
        
        # Если каналов больше 2, берем первые 2 для анализа
        if channels > 2:
            logger.warning(f"Обнаружено {channels} каналов, анализируем первые 2")
        
        # Разделяем стерео на каналы
        mono_channels = audio.split_to_mono()
        left_channel = mono_channels[0]
        right_channel = mono_channels[1] if len(mono_channels) > 1 else mono_channels[0]
        
        # Получаем сэмплы
        left_samples = np.array(left_channel.get_array_of_samples(), dtype=np.float32)
        right_samples = np.array(right_channel.get_array_of_samples(), dtype=np.float32)
        
        # Нормализуем для анализа
        if len(left_samples) > 0:
            left_max = np.max(np.abs(left_samples))
            if left_max > 0:
                left_samples = left_samples / left_max
        
        if len(right_samples) > 0:
            right_max = np.max(np.abs(right_samples))
            if right_max > 0:
                right_samples = right_samples / right_max
        
        # Вычисляем энергию каждого канала (RMS)
        left_energy = np.sqrt(np.mean(left_samples ** 2)) if len(left_samples) > 0 else 0.0
        right_energy = np.sqrt(np.mean(right_samples ** 2)) if len(right_samples) > 0 else 0.0
        
        # Вычисляем соотношение энергий
        total_energy = left_energy + right_energy
        if total_energy > 0:
            left_ratio = left_energy / total_energy
            right_ratio = right_energy / total_energy
        else:
            left_ratio = 0.5
            right_ratio = 0.5
        
        # Вычисляем разницу между каналами (корреляция)
        # Если каналы идентичны, корреляция будет близка к 1.0
        # Если каналы разные, корреляция будет ниже
        if len(left_samples) == len(right_samples) and len(left_samples) > 0:
            # Нормализуем для корреляции
            left_norm = left_samples - np.mean(left_samples)
            right_norm = right_samples - np.mean(right_samples)
            
            left_std = np.std(left_norm)
            right_std = np.std(right_norm)
            
            if left_std > 0 and right_std > 0:
                correlation = np.corrcoef(left_norm, right_norm)[0, 1]
                if np.isnan(correlation):
                    correlation = 1.0
            else:
                correlation = 1.0
        else:
            correlation = 1.0
        
        # Вычисляем разницу между каналами
        channel_difference = 1.0 - abs(correlation)
        
        # Вычисляем разницу энергий между каналами
        energy_difference = abs(left_ratio - right_ratio)
        
        # Определяем, является ли это реальным стерео
        # Условия для стерео:
        # 1. Разница между каналами должна быть значительной
        # 2. Энергия должна быть распределена неравномерно между каналами
        # 3. Оба канала должны иметь достаточную энергию (не пустые)
        
        has_significant_difference = channel_difference >= min_channel_difference
        has_uneven_energy = energy_difference >= min_channel_energy_ratio
        both_channels_active = left_energy > 0.01 and right_energy > 0.01
        
        is_stereo = (
            has_significant_difference and 
            has_uneven_energy and 
            both_channels_active
        )
        
        # Дополнительная проверка: если один канал почти пустой, это точно моно
        if left_energy < 0.001 or right_energy < 0.001:
            is_stereo = False
            reason = "Один из каналов пустой или почти пустой"
        elif is_stereo:
            reason = f"Стерео: значительные различия (diff={channel_difference:.3f}, energy_diff={energy_difference:.3f})"
        else:
            reason = f"Моно: каналы похожи (diff={channel_difference:.3f}, energy_diff={energy_difference:.3f})"
        
        analysis_info = {
            "channels": channels,
            "is_stereo": is_stereo,
            "reason": reason,
            "left_energy": float(left_energy),
            "right_energy": float(right_energy),
            "left_ratio": float(left_ratio),
            "right_ratio": float(right_ratio),
            "channel_difference": float(channel_difference),
            "energy_difference": float(energy_difference),
            "correlation": float(correlation) if 'correlation' in locals() else 1.0
        }
        
        logger.info(f"Автоопределение типа звонка: {'СТЕРЕО' if is_stereo else 'МОНО'} - {reason}")
        logger.debug(f"Детали анализа: {analysis_info}")
        
        return is_stereo, analysis_info
        
    except Exception as e:
        logger.error(f"Ошибка при автоопределении типа звонка: {e}", exc_info=True)
        # В случае ошибки возвращаем консервативное значение (моно)
        return False, {
            "channels": audio.channels if hasattr(audio, 'channels') else 1,
            "is_stereo": False,
            "reason": f"Ошибка анализа: {str(e)}"
        }


def transcribe_audio_with_tbank(file_path: Path) -> str | None:
    """
    Транскрибирует аудио файл используя T-Bank VoiceKit с автоопределением типа звонка.
    
    Автоматически определяет тип звонка (моно/стерео) и всегда выполняет диаризацию
    для определения 2 спикеров (даже для моно звонков).
    
    Args:
        file_path: Путь к аудио файлу
        
    Returns:
        Текст транскрипции с диаризацией (2 спикера) или None при ошибке
    """
    try:
        logger.info(f"Начинаем транскрипцию через T-Bank VoiceKit для файла {file_path.name}")
        
        # Проверяем файл
        if not file_path.exists():
            logger.error(f"Файл {file_path} не найден")
            return None
        
        # Создаем клиент T-Bank (ленивый импорт)
        try:
            ClientSTT = _get_client_stt()
        except ImportError as e:
            logger.error(f"T-Bank клиент недоступен: {e}")
            return None
        
        api_key = os.getenv("TBANK_API_KEY", config.TBANK_API_KEY)
        secret_key = os.getenv("TBANK_SECRET_KEY", config.TBANK_SECRET_KEY)
        
        if not api_key or not secret_key:
            logger.error("T-Bank API ключи не настроены")
            return None
        
        try:
            client = ClientSTT(api_key=api_key, secret_key=secret_key)
        except Exception as e:
            logger.error(f"Ошибка при создании T-Bank клиента: {e}")
            return None
        logger.info("Клиент T-Bank создан успешно")
        
        # Инициализируем переменные для автоопределения
        detected_stereo = False
        analysis_info = {}
        
        # Подготавливаем аудио
        try:
            audio = AudioSegment.from_file(str(file_path))
            duration = len(audio) / 1000.0
            sample_rate = audio.frame_rate
            channels = audio.channels
            
            logger.info(f"Параметры аудио: {duration:.2f}с, {sample_rate}Hz, {channels} каналов")
            
            # Автоопределение типа звонка (моно/стерео)
            detected_stereo, analysis_info = detect_call_type(audio)
            logger.info(f"Автоопределение типа звонка: {'СТЕРЕО' if detected_stereo else 'МОНО'} "
                       f"(каналы: {channels}, разница: {analysis_info.get('channel_difference', 0):.3f}, "
                       f"энергия: {analysis_info.get('energy_difference', 0):.3f})")

            # ИНТЕГРАЦИЯ SPEECH SEPARATION (ОПЦИОНАЛЬНО)
            # Если обнаружено МОНО, пробуем разделить на псевдо-стерео через SpeechBrain
            # Проверяем наличие модуля и конфиг (если нужно)
            use_separation = not detected_stereo and os.getenv("ENABLE_SPEECH_SEPARATION", "false").lower() == "true"
            
            pseudo_stereo_path = None
            if use_separation:
                try:
                    from .audio_separator import convert_mono_to_stereo_split
                    logger.info("Включено разделение речи (Speech Separation) для моно-звонка")
                    
                    temp_sep_dir = Path(config.BASE_RECORDS_PATH) / "runtime" / "temp_sep"
                    temp_sep_dir.mkdir(parents=True, exist_ok=True)
                    pseudo_stereo_path = temp_sep_dir / f"sep_{file_path.stem}.wav"
                    
                    success = convert_mono_to_stereo_split(str(file_path), str(pseudo_stereo_path))
                    
                    if success:
                        logger.info(f"Успешно создано псевдо-стерео: {pseudo_stereo_path}")
                        # Подменяем аудио для дальнейшей обработки на новое псевдо-стерео
                        audio = AudioSegment.from_file(str(pseudo_stereo_path))
                        channels = 2 # Теперь это стерео
                        detected_stereo = True # Теперь мы считаем это стерео
                        logger.info("Переключаем режим обработки на СТЕРЕО (после разделения)")
                    else:
                        logger.warning("Не удалось разделить аудио, продолжаем как моно")
                        
                except ImportError:
                    logger.warning("Модуль audio_separator не найден или отсутствуют зависимости (speechbrain, torchaudio)")
                except Exception as e:
                    logger.error(f"Ошибка при попытке разделения речи: {e}")

        except Exception as e:
            logger.error(f"Ошибка при загрузке аудио файла {file_path}: {e}", exc_info=True)
            return None
        
        # Конвертируем в нужный формат для T-Bank (моно, 16kHz)
        audio_for_tbank = audio
        
        try:
            if channels > 1:
                audio_for_tbank = audio_for_tbank.set_channels(1)
                logger.info("Конвертировано в моно для T-Bank")
            
            if sample_rate != 16000:
                audio_for_tbank = audio_for_tbank.set_frame_rate(16000)
                logger.info("Конвертировано в 16kHz для T-Bank")
        except Exception as e:
            logger.error(f"Ошибка при конвертации аудио: {e}", exc_info=True)
            return None
        
        # Создаем временный файл для T-Bank
        temp_dir = Path(config.BASE_RECORDS_PATH) / "runtime" / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"tbank_{file_path.stem}.wav"
        
        try:
            audio_for_tbank.export(str(temp_path), format="wav", parameters=["-ar", "16000", "-ac", "1"])
            logger.info(f"Аудио подготовлено для T-Bank: {temp_path}")
            
            # Проверяем, что файл создан и не пустой
            if not temp_path.exists() or temp_path.stat().st_size == 0:
                logger.error(f"Ошибка: временный файл {temp_path} не создан или пуст")
                return None
                
            logger.info(f"Размер временного файла: {temp_path.stat().st_size} байт")
        except Exception as e:
            logger.error(f"Ошибка при экспорте аудио в временный файл: {e}", exc_info=True)
            return None
        
        # Конфигурация T-Bank (базовая, без enable_diarization для синхронного метода)
        audio_config = {
            "encoding": "LINEAR16",
            "sample_rate_hertz": 16000,
            "num_channels": 1,
            "language_code": "ru-RU",
            "enable_automatic_punctuation": True,
            "enable_denormalization": True,
            "enable_rescoring": True,
            "model": "general"
        }
        
        # Выполняем распознавание с встроенной диаризацией
        # Пробуем использовать StreamingRecognize для встроенной диаризации
        logger.info("Начинаем распознавание через T-Bank с встроенной диаризацией...")
        
        try:
            # Пробуем использовать StreamingRecognize (поддерживает enable_diarization)
            response = _streaming_recognize_with_diarization(
                temp_path, sample_rate, 1, api_key, secret_key
            )
            
            # Если StreamingRecognize не сработал, используем синхронный метод (без enable_diarization)
            if response is None:
                logger.info("StreamingRecognize недоступен, используем синхронный метод recognize() с последующей самописной диаризацией")
                with open(temp_path, "rb") as audio_file_obj:
                    response = client.recognize(audio_file_obj, audio_config)
                # Для синхронного метода встроенная диаризация недоступна, используем самописную
                logger.info("Используем самописную диаризацию для синхронного метода")
            else:
                logger.info("Потоковое распознавание с диаризацией завершено успешно")
            
            if not response:
                logger.warning("Получен пустой ответ от T-Bank API")
                return None
                
            logger.debug(f"Структура ответа T-Bank: {list(response.keys()) if isinstance(response, dict) else type(response)}")
            
            # Определяем, использовался ли StreamingRecognize (есть ли слова с метками спикеров)
            using_streaming = False
            if "results" in response:
                for result in response.get("results", []):
                    for alternative in result.get("alternatives", []):
                        if "words" in alternative and alternative["words"]:
                            # Проверяем, есть ли метки спикеров в словах
                            for word in alternative["words"]:
                                if isinstance(word, dict) and "speaker_tag" in word:
                                    using_streaming = True
                                    break
                            if using_streaming:
                                break
                    if using_streaming:
                        break
            
            # Если используется StreamingRecognize, парсим встроенную диаризацию
            # Иначе используем самописную диаризацию
            if using_streaming:
                logger.info(f"Обрабатываем ответ с встроенной диаризацией T-Bank (тип: {'СТЕРЕО' if detected_stereo else 'МОНО'})")
            else:
                logger.info(f"Используем самописную диаризацию (тип: {'СТЕРЕО' if detected_stereo else 'МОНО'})")
            
            try:
                # Если используется StreamingRecognize, обрабатываем встроенную диаризацию
                # Иначе используем самописную диаризацию
                if using_streaming:
                    # Обрабатываем ответ с диаризацией от T-Bank
                    # Группируем слова по сегментам с одинаковым спикером
                    lines = []
                    current_segment = None  # (speaker_id, words_list)
                    
                    if "results" in response:
                        for result in response["results"]:
                            if "alternatives" in result:
                                for alternative in result["alternatives"]:
                                    # Проверяем наличие слов с метками спикеров
                                    if "words" in alternative:
                                        for word in alternative["words"]:
                                            # Получаем метку спикера (может быть speaker_tag, speaker, или speaker_label)
                                            speaker_tag = word.get("speaker_tag") or word.get("speaker") or word.get("speaker_label") or 0
                                            speaker_id = f"SPEAKER_{speaker_tag:02d}" if isinstance(speaker_tag, int) else f"SPEAKER_{speaker_tag}"
                                            word_text = word.get("word", "").strip()
                                            
                                            if not word_text:
                                                continue
                                            
                                            # Если это новый спикер или первый сегмент, создаем новый сегмент
                                            if current_segment is None or current_segment[0] != speaker_id:
                                                # Сохраняем предыдущий сегмент
                                                if current_segment is not None:
                                                    segment_text = " ".join(current_segment[1]).strip()
                                                    if segment_text:
                                                        lines.append(f"{current_segment[0]}: {segment_text}")
                                                # Создаем новый сегмент
                                                current_segment = (speaker_id, [word_text])
                                            else:
                                                # Добавляем слово к текущему сегменту
                                                current_segment[1].append(word_text)
                                    else:
                                        # Если нет слов с метками, проверяем транскрипт целиком
                                        transcript = alternative.get("transcript", "").strip()
                                        if transcript:
                                            # Если нет диаризации, используем один спикер
                                            if current_segment is None or current_segment[0] != "SPEAKER_01":
                                                if current_segment is not None:
                                                    segment_text = " ".join(current_segment[1]).strip()
                                                    if segment_text:
                                                        lines.append(f"{current_segment[0]}: {segment_text}")
                                                current_segment = ("SPEAKER_01", [transcript])
                                            else:
                                                current_segment[1].append(transcript)
                    
                    # Сохраняем последний сегмент
                    if current_segment is not None:
                        segment_text = " ".join(current_segment[1]).strip()
                        if segment_text:
                            lines.append(f"{current_segment[0]}: {segment_text}")
                    
                    # Если диаризация не вернула данные, используем обычный транскрипт
                    if not lines:
                        logger.warning("Встроенная диаризация не вернула метки спикеров, используем весь транскрипт")
                        transcript_lines = []
                        if "results" in response:
                            for result in response["results"]:
                                if "alternatives" in result:
                                    for alternative in result["alternatives"]:
                                        transcript = alternative.get("transcript", "").strip()
                                        if transcript:
                                            transcript_lines.append(f"SPEAKER_01: {transcript}")
                        lines = transcript_lines
                    
                    # Если все еще нет спикеров, используем фоллбэк
                    if not lines:
                        logger.warning("Диаризация не вернула сегменты, используем простую транскрипцию")
                        raise RuntimeError("no speaker segments found")
                    
                    # Проверяем, что есть хотя бы 2 спикера
                    unique_speakers = set()
                    for line in lines:
                        if ":" in line:
                            speaker = line.split(":")[0].strip()
                            unique_speakers.add(speaker)
                    
                    logger.info(f"Обнаружено спикеров: {len(unique_speakers)} ({', '.join(sorted(unique_speakers))})")
                    
                    # Если только 1 спикер, используем фоллбэк на самописную диаризацию
                    if len(unique_speakers) == 1:
                        logger.warning("Встроенная диаризация определила только 1 спикера, используем самописную диаризацию")
                        raise RuntimeError("only one speaker detected")
                    
                    full_transcript = "\n".join(lines)
                else:
                    # Используем самописную диаризацию для синхронного метода
                    raise RuntimeError("using custom diarization")
            except Exception as e:
                logger.error(f"Ошибка обработки встроенной диаризации: {e}", exc_info=True)
                # Фоллбэк на самописную диаризацию
                logger.info("Откат к самописной диаризации")
                try:
                    # Импортируем алгоритм диаризации из корня проекта
                    project_root = Path(__file__).resolve().parents[1]
                    if str(project_root) not in sys.path:
                        sys.path.insert(0, str(project_root))
                    import tbank_voice_diarization as tvd  # type: ignore

                    diar = tvd.tbank_with_voice_analysis_diarization(response, str(file_path))
                    if not diar or not diar.get("success"):
                        logger.warning("Самописная диаризация не вернула результат, используем простую транскрипцию")
                        raise RuntimeError("fallback diarization failed")

                    lines = []
                    for seg in diar.get("speakers_data", []):
                        spk = seg.get("speaker", "SPEAKER_01")
                        text = seg.get("text", "").strip()
                        if text:
                            lines.append(f"{spk}: {text}")
                    
                    if lines:
                        full_transcript = "\n".join(lines)
                    else:
                        raise RuntimeError("no speaker segments found")
                except Exception as fallback_error:
                    logger.error(f"Ошибка самописной диаризации: {fallback_error}", exc_info=True)
                    # Финальный фоллбэк на простую транскрипцию с одним спикером
                    logger.info("Финальный откат к простой транскрипции без диаризации")
                    transcript_lines = []
                    if "results" in response:
                        for result in response["results"]:
                            if "alternatives" in result:
                                for alternative in result["alternatives"]:
                                    transcript = alternative.get("transcript", "").strip()
                                    if transcript:
                                        transcript_lines.append(f"SPEAKER_01: {transcript}")
                    full_transcript = "\n".join(transcript_lines) if transcript_lines else ""
            logger.info(f"Транскрипт получен, длина: {len(full_transcript)} символов")
            
            return full_transcript
            
        except Exception as e:
            logger.error(f"Ошибка при вызове T-Bank API: {e}", exc_info=True)
            return None
        finally:
            # Удаляем временный файл
            if temp_path.exists():
                try:
                    os.remove(temp_path)
                    logger.info("Временный файл удален")
                except Exception as e:
                    logger.warning(f"Не удалось удалить временный файл {temp_path}: {e}")
            
            # Очищаем старые временные файлы (старше 1 часа)
            for old_file in temp_dir.glob("tbank_*.wav"):
                try:
                    if os.path.getmtime(old_file) < os.path.getmtime(file_path) - 3600:
                        os.remove(old_file)
                except Exception:
                    pass
                    
    except Exception as e:
        logger.error(f"Ошибка при транскрипции через T-Bank: {e}")
        return None

