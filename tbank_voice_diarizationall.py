#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T-BANK VOICEKIT С АНАЛИЗОМ ГОЛОСОВ (СТЕРЕО ВЕРСИЯ)
Интеграция T-Bank VoiceKit с анализом голосов для стерео аудио
"""

from tinkoff_voicekit_client import ClientSTT
from pydub import AudioSegment
import os
import json
import numpy as np
import librosa
from typing import Dict, List, Optional, Tuple
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_voice_features(audio_segment: AudioSegment, start_time: float, end_time: float) -> Dict:
    """
    Извлекает характеристики голоса из аудио сегмента (поддержка стерео)
    """
    try:
        # Получаем каналы отдельно для стерео аудио
        if audio_segment.channels == 2:
            # Разделяем стерео на левый и правый каналы
            left_channel = audio_segment.split_to_mono()[0]
            right_channel = audio_segment.split_to_mono()[1]
            
            # Используем левый канал как основной
            samples = np.array(left_channel.get_array_of_samples(), dtype=np.float32)
            sample_rate = left_channel.frame_rate
            
            # Также анализируем правый канал для сравнения
            right_samples = np.array(right_channel.get_array_of_samples(), dtype=np.float32)
        else:
            # Моно аудио
            samples = np.array(audio_segment.get_array_of_samples(), dtype=np.float32)
            sample_rate = audio_segment.frame_rate
            right_samples = None
        
        # Нормализуем
        if len(samples) > 0:
            samples = samples / np.max(np.abs(samples))
        
        if right_samples is not None and len(right_samples) > 0:
            right_samples = right_samples / np.max(np.abs(right_samples))
        
        # Вычисляем временные индексы
        start_sample = int(start_time * sample_rate)
        end_sample = int(end_time * sample_rate)
        
        # Извлекаем сегмент
        segment_samples = samples[start_sample:end_sample]
        right_segment_samples = right_samples[start_sample:end_sample] if right_samples is not None else None
        
        if len(segment_samples) == 0:
            return {
                "fundamental_frequency": 0,
                "spectral_centroid": 0,
                "spectral_rolloff": 0,
                "zero_crossing_rate": 0,
                "mfcc": [0] * 13,
                "energy": 0,
                "stereo_balance": 0,
                "channel_difference": 0
            }
        
        # Основная частота (F0) для левого канала
        f0_left = librosa.yin(segment_samples, fmin=50, fmax=400, sr=sample_rate)
        fundamental_freq_left = np.median(f0_left[f0_left > 0]) if len(f0_left[f0_left > 0]) > 0 else 0
        
        # Основная частота для правого канала (если есть)
        fundamental_freq_right = 0
        if right_segment_samples is not None and len(right_segment_samples) > 0:
            f0_right = librosa.yin(right_segment_samples, fmin=50, fmax=400, sr=sample_rate)
            fundamental_freq_right = np.median(f0_right[f0_right > 0]) if len(f0_right[f0_right > 0]) > 0 else 0
        
        # Используем среднее значение или левый канал
        fundamental_freq = (fundamental_freq_left + fundamental_freq_right) / 2 if fundamental_freq_right > 0 else fundamental_freq_left
        
        # Спектральные характеристики для левого канала
        spectral_centroid_left = librosa.feature.spectral_centroid(y=segment_samples, sr=sample_rate)[0]
        spectral_rolloff_left = librosa.feature.spectral_rolloff(y=segment_samples, sr=sample_rate)[0]
        zero_crossing_rate_left = librosa.feature.zero_crossing_rate(segment_samples)[0]
        
        # Спектральные характеристики для правого канала (если есть)
        spectral_centroid_right = np.array([0])
        spectral_rolloff_right = np.array([0])
        zero_crossing_rate_right = np.array([0])
        
        if right_segment_samples is not None and len(right_segment_samples) > 0:
            spectral_centroid_right = librosa.feature.spectral_centroid(y=right_segment_samples, sr=sample_rate)[0]
            spectral_rolloff_right = librosa.feature.spectral_rolloff(y=right_segment_samples, sr=sample_rate)[0]
            zero_crossing_rate_right = librosa.feature.zero_crossing_rate(right_segment_samples)[0]
        
        # Используем средние значения
        spectral_centroid = (np.mean(spectral_centroid_left) + np.mean(spectral_centroid_right)) / 2
        spectral_rolloff = (np.mean(spectral_rolloff_left) + np.mean(spectral_rolloff_right)) / 2
        zero_crossing_rate = (np.mean(zero_crossing_rate_left) + np.mean(zero_crossing_rate_right)) / 2
        
        # MFCC для левого канала
        mfcc_left = librosa.feature.mfcc(y=segment_samples, sr=sample_rate, n_mfcc=13)
        
        # MFCC для правого канала (если есть)
        mfcc_right = np.zeros_like(mfcc_left)
        if right_segment_samples is not None and len(right_segment_samples) > 0:
            mfcc_right = librosa.feature.mfcc(y=right_segment_samples, sr=sample_rate, n_mfcc=13)
        
        # Используем средние значения MFCC
        mfcc = (np.mean(mfcc_left, axis=1) + np.mean(mfcc_right, axis=1)) / 2
        
        # Энергия для обоих каналов
        energy_left = np.sum(segment_samples ** 2)
        energy_right = np.sum(right_segment_samples ** 2) if right_segment_samples is not None else 0
        energy = energy_left + energy_right
        
        # Стерео баланс (разность между каналами)
        stereo_balance = (energy_left - energy_right) / (energy_left + energy_right + 1e-10)
        
        # Разность между каналами по основной частоте
        channel_difference = abs(fundamental_freq_left - fundamental_freq_right) if fundamental_freq_right > 0 else 0
        
        return {
            "fundamental_frequency": float(fundamental_freq),
            "spectral_centroid": float(spectral_centroid),
            "spectral_rolloff": float(spectral_rolloff),
            "zero_crossing_rate": float(zero_crossing_rate),
            "mfcc": [float(x) for x in mfcc],
            "energy": float(energy),
            "stereo_balance": float(stereo_balance),
            "channel_difference": float(channel_difference),
            "left_f0": float(fundamental_freq_left),
            "right_f0": float(fundamental_freq_right)
        }
        
    except Exception as e:
        logger.error(f"Ошибка при извлечении характеристик голоса: {e}")
        return {
            "fundamental_frequency": 0,
            "spectral_centroid": 0,
            "spectral_rolloff": 0,
            "zero_crossing_rate": 0,
            "mfcc": [0] * 13,
            "energy": 0,
            "stereo_balance": 0,
            "channel_difference": 0,
            "left_f0": 0,
            "right_f0": 0
        }

def analyze_speaker_voice_profile(voice_features: List[Dict]) -> Dict:
    """
    Анализирует профиль голоса спикера (поддержка стерео)
    """
    if not voice_features:
        return {"speaker_id": "UNKNOWN", "confidence": 0}
    
    # Вычисляем средние характеристики
    avg_f0 = np.mean([f["fundamental_frequency"] for f in voice_features])
    avg_spectral_centroid = np.mean([f["spectral_centroid"] for f in voice_features])
    avg_spectral_rolloff = np.mean([f["spectral_rolloff"] for f in voice_features])
    avg_zcr = np.mean([f["zero_crossing_rate"] for f in voice_features])
    avg_energy = np.mean([f["energy"] for f in voice_features])
    
    # Стерео характеристики
    avg_stereo_balance = np.mean([f["stereo_balance"] for f in voice_features])
    avg_channel_difference = np.mean([f["channel_difference"] for f in voice_features])
    avg_left_f0 = np.mean([f["left_f0"] for f in voice_features])
    avg_right_f0 = np.mean([f["right_f0"] for f in voice_features])
    
    # Определяем тип голоса по основной частоте
    if avg_f0 < 120:
        voice_type = "MALE_LOW"
    elif avg_f0 < 180:
        voice_type = "MALE_MID"
    elif avg_f0 < 250:
        voice_type = "FEMALE_LOW"
    else:
        voice_type = "FEMALE_HIGH"
    
    # Определяем позицию спикера в стерео
    if abs(avg_stereo_balance) < 0.1:
        stereo_position = "CENTER"
    elif avg_stereo_balance > 0.1:
        stereo_position = "LEFT"
    else:
        stereo_position = "RIGHT"
    
    # Вычисляем стабильность голоса
    f0_variance = np.var([f["fundamental_frequency"] for f in voice_features])
    stability = 1.0 / (1.0 + f0_variance / 1000)  # Нормализуем
    
    # Вычисляем стабильность стерео позиции
    stereo_variance = np.var([f["stereo_balance"] for f in voice_features])
    stereo_stability = 1.0 / (1.0 + stereo_variance / 0.1)  # Нормализуем
    
    return {
        "voice_type": voice_type,
        "stereo_position": stereo_position,
        "avg_fundamental_frequency": avg_f0,
        "avg_spectral_centroid": avg_spectral_centroid,
        "avg_spectral_rolloff": avg_spectral_rolloff,
        "avg_zero_crossing_rate": avg_zcr,
        "avg_energy": avg_energy,
        "avg_stereo_balance": avg_stereo_balance,
        "avg_channel_difference": avg_channel_difference,
        "avg_left_f0": avg_left_f0,
        "avg_right_f0": avg_right_f0,
        "stability": stability,
        "stereo_stability": stereo_stability,
        "sample_count": len(voice_features)
    }

def identify_speaker_by_voice(voice_features: Dict, known_speakers: List[Dict]) -> Tuple[str, float]:
    """
    Идентифицирует спикера по характеристикам голоса (поддержка стерео)
    """
    if not known_speakers:
        return "SPEAKER_01", 0.5
    
    best_match = None
    best_score = 0
    
    for speaker in known_speakers:
        # Вычисляем схожесть по основной частоте
        avg_f0 = speaker.get("avg_fundamental_frequency", 0)
        if avg_f0 == 0:
            avg_f0 = np.mean([f["fundamental_frequency"] for f in speaker.get("voice_features", [])]) if speaker.get("voice_features") else 0
        
        f0_diff = abs(voice_features["fundamental_frequency"] - avg_f0)
        f0_score = 1.0 / (1.0 + f0_diff / 50)  # Нормализуем
        
        # Вычисляем схожесть по спектральным характеристикам
        avg_spectral = speaker.get("avg_spectral_centroid", 0)
        if avg_spectral == 0:
            avg_spectral = np.mean([f["spectral_centroid"] for f in speaker.get("voice_features", [])]) if speaker.get("voice_features") else 0
        
        spectral_diff = abs(voice_features["spectral_centroid"] - avg_spectral)
        spectral_score = 1.0 / (1.0 + spectral_diff / 1000)
        
        # Вычисляем схожесть по MFCC
        mfcc_diff = np.linalg.norm(
            np.array(voice_features["mfcc"]) - np.array(speaker.get("avg_mfcc", [0] * 13))
        )
        mfcc_score = 1.0 / (1.0 + mfcc_diff / 10)
        
        # Вычисляем схожесть по стерео позиции
        avg_stereo = speaker.get("avg_stereo_balance", 0)
        stereo_diff = abs(voice_features["stereo_balance"] - avg_stereo)
        stereo_score = 1.0 / (1.0 + stereo_diff / 0.2)  # Нормализуем
        
        # Вычисляем схожесть по разности каналов
        avg_channel = speaker.get("avg_channel_difference", 0)
        channel_diff = abs(voice_features["channel_difference"] - avg_channel)
        channel_score = 1.0 / (1.0 + channel_diff / 20)  # Нормализуем
        
        # Общий score с учетом стерео характеристик
        total_score = (f0_score * 0.3 + spectral_score * 0.2 + mfcc_score * 0.2 + 
                      stereo_score * 0.2 + channel_score * 0.1)
        
        if total_score > best_score:
            best_score = total_score
            best_match = speaker["speaker_id"]
    
    # Если score слишком низкий, создаем нового спикера
    if best_score < 0.3:  # Низкий порог для лучшей диаризации
        new_speaker_id = f"SPEAKER_{len(known_speakers) + 1:02d}"
        return new_speaker_id, 0.25
    
    return best_match, best_score

def tbank_with_voice_analysis_diarization(transcript_data: Dict, audio_file: str) -> Dict:
    """
    Диаризация с использованием T-Bank VoiceKit и анализа голосов (поддержка стерео)
    """
    logger.info("Используем T-Bank VoiceKit с анализом голосов (стерео)...")
    
    # Загружаем аудио файл
    try:
        audio = AudioSegment.from_file(audio_file)
        # НЕ конвертируем в моно - работаем со стерео
        logger.info(f"Загружено аудио: {audio.channels} каналов, {audio.frame_rate}Hz")
    except Exception as e:
        logger.error(f"Ошибка при загрузке аудио: {e}")
        return {"success": False, "error": str(e)}
    
    # Анализируем временные метки слов
    words_with_time = []
    
    if "results" in transcript_data:
        for result in transcript_data["results"]:
            if "alternatives" in result:
                for alternative in result["alternatives"]:
                    if "words" in alternative:
                        for word in alternative["words"]:
                            words_with_time.append({
                                "word": word["word"],
                                "start_time": float(word["start_time"].rstrip('s')),
                                "end_time": float(word["end_time"].rstrip('s')),
                                "confidence": word.get("confidence", 0.0)
                            })
    
    if not words_with_time:
        logger.warning("Не найдены временные метки слов")
        return {"success": False, "error": "Нет временных меток"}
    
    # Группируем слова в сегменты по паузам
    segments = []
    current_segment = []
    min_pause = 0.5  # Минимальная пауза для разделения сегментов
    
    for i, word in enumerate(words_with_time):
        current_segment.append(word)
        
        # Проверяем паузу до следующего слова
        if i < len(words_with_time) - 1:
            next_word = words_with_time[i + 1]
            pause = next_word["start_time"] - word["end_time"]
            
            if pause > min_pause:
                # Создаем сегмент
                if current_segment:
                    segments.append(current_segment)
                    current_segment = []
    
    # Добавляем последний сегмент
    if current_segment:
        segments.append(current_segment)
    
    # Анализируем голоса для каждого сегмента
    known_speakers = []
    speakers_data = []
    
    for i, segment in enumerate(segments):
        if not segment:
            continue
        
        start_time = segment[0]["start_time"]
        end_time = segment[-1]["end_time"]
        
        # Извлекаем характеристики голоса
        voice_features = extract_voice_features(audio, start_time, end_time)
        
        # Идентифицируем спикера по стерео позиции
        # Используем простую логику: только 2 спикера
        stereo_balance = voice_features.get("stereo_balance", 0)
        
        # Определяем спикера по стерео балансу - только 2 спикера
        if stereo_balance > 0.1:  # Левый канал или центр с положительным балансом
            speaker_id = "SPEAKER_02"
        else:  # Правый канал или центр с отрицательным балансом
            speaker_id = "SPEAKER_01"
        
        confidence = 0.7
        
        # Обновляем профиль спикера
        speaker_profile = None
        for speaker in known_speakers:
            if speaker["speaker_id"] == speaker_id:
                speaker_profile = speaker
                break
        
        if speaker_profile is None:
            # Создаем нового спикера
            speaker_profile = {
                "speaker_id": speaker_id,
                "voice_features": []
            }
            known_speakers.append(speaker_profile)
        
        speaker_profile["voice_features"].append(voice_features)
        
        # Формируем текст сегмента
        text = " ".join([word["word"] for word in segment])
        
        speakers_data.append({
            "speaker": speaker_id,
            "start_time": start_time,
            "end_time": end_time,
            "text": text,
            "confidence": confidence,
            "voice_features": voice_features
        })
    
    # Анализируем профили спикеров
    for speaker in known_speakers:
        speaker.update(analyze_speaker_voice_profile(speaker["voice_features"]))
    
    return {
        "success": True,
        "speakers_data": speakers_data,
        "known_speakers": known_speakers,
        "method": "tbank_with_voice_analysis"
    }

def recognize_with_tbank_voice_diarization(audio_file: str) -> bool:
    """
    Основная функция для распознавания с диаризацией через T-Bank VoiceKit
    """
    try:
        print(f"=== T-BANK VOICEKIT С АНАЛИЗОМ ГОЛОСОВ (СТЕРЕО) ===")
        
        # Проверяем файл
        if not os.path.exists(audio_file):
            print(f"Файл {audio_file} не найден")
            return False
        
        file_size = os.path.getsize(audio_file)
        print(f"Файл {audio_file} найден")
        print(f"Размер файла: {file_size} байт")
        
        # Создаем клиент T-Bank
        print(f"\nСоздаем клиент T-Bank VoiceKit...")
        # Используем реальные ключи
        api_key = os.getenv("TBANK_API_KEY", "LEc1tAfU1qDrn6chWuo/Lau2pJCyHyC/e6FtjquWidM=")
        secret_key = os.getenv("TBANK_SECRET_KEY", "YLWjm7DGJZSZzuJcoaNZTFWDADKtMfuOdrU4rsCRQmU=")
        
        client = ClientSTT(api_key=api_key, secret_key=secret_key)
        print("Клиент создан успешно")
        
        # Подготавливаем аудио
        print(f"\nПодготавливаем аудио...")
        audio = AudioSegment.from_file(audio_file)
        duration = len(audio) / 1000.0
        sample_rate = audio.frame_rate
        channels = audio.channels
        
        print(f"Параметры аудио: {duration:.2f}с, {sample_rate}Hz, {channels} каналов")
        
        # Конвертируем в нужный формат для T-Bank (но сохраняем оригинал для анализа)
        audio_for_tbank = audio
        
        if channels > 1:
            audio_for_tbank = audio_for_tbank.set_channels(1)
            print("Конвертировано в моно для T-Bank")
        
        if sample_rate != 16000:
            audio_for_tbank = audio_for_tbank.set_frame_rate(16000)
            print("Конвертировано в 16kHz для T-Bank")
        
        # Создаем временный файл для T-Bank
        temp_path = "temp_audio.wav"
        audio_for_tbank.export(temp_path, format="wav", parameters=["-ar", "16000", "-ac", "1"])
        print(f"Аудио подготовлено для T-Bank: {temp_path}")
        
        # Конфигурация T-Bank
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
        
        # Выполняем распознавание
        print(f"\nНачинаем распознавание через T-Bank с диаризацией...")
        print("Это может занять некоторое время...")
        
        with open(temp_path, "rb") as audio_file_obj:
            response = client.recognize(audio_file_obj, audio_config)
        
        print("=== РАСПОЗНАВАНИЕ ЗАВЕРШЕНО! ===")
        print(f"Время обработки: {response.get('total_billed_time', 0):.2f} сек")
        
        # Показываем полный транскрипт
        full_transcript = ""
        if "results" in response:
            for result in response["results"]:
                if "alternatives" in result:
                    for alternative in result["alternatives"]:
                        full_transcript += alternative["transcript"]
        
        print(f"\n=== ПОЛНЫЙ ТРАНСКРИПТ ===")
        print(full_transcript.strip())
        
        # Выполняем диаризацию с анализом голосов (используем оригинальное стерео аудио)
        print(f"\n=== ДИАРИЗАЦИЯ С АНАЛИЗОМ ГОЛОСОВ (СТЕРЕО) ===")
        
        diarization_result = tbank_with_voice_analysis_diarization(response, audio_file)
        
        if not diarization_result["success"]:
            print(f"Ошибка диаризации: {diarization_result['error']}")
            return False
        
        speakers_data = diarization_result["speakers_data"]
        known_speakers = diarization_result["known_speakers"]
        diarization_method = diarization_result["method"]
        
        # Получаем список уникальных спикеров
        speakers_list = list(set([s["speaker"] for s in speakers_data]))
        
        print(f"Количество говорящих: {len(speakers_list)}")
        print(f"Говорящие: {', '.join(speakers_list)}")
        print(f"Метод диаризации: {diarization_method}")
        
        # Показываем профили голосов
        print(f"\n=== ПРОФИЛИ ГОЛОСОВ (СТЕРЕО) ===")
        for speaker in known_speakers:
            print(f"{speaker['speaker_id']}:")
            print(f"  Тип голоса: {speaker['voice_type']}")
            print(f"  Позиция в стерео: {speaker['stereo_position']}")
            print(f"  Основная частота: {speaker['avg_fundamental_frequency']:.1f} Hz")
            print(f"  Левый канал F0: {speaker['avg_left_f0']:.1f} Hz")
            print(f"  Правый канал F0: {speaker['avg_right_f0']:.1f} Hz")
            print(f"  Стерео баланс: {speaker['avg_stereo_balance']:.3f}")
            print(f"  Стабильность: {speaker['stability']:.2f}")
            print(f"  Стабильность стерео: {speaker['stereo_stability']:.2f}")
            print(f"  Образцов: {speaker['sample_count']}")
        
        # Показываем сегменты с анализом голосов
        for i, speaker in enumerate(speakers_data):
            print(f"\nСегмент {i+1}: {speaker['speaker']}")
            print(f"Время: {speaker['start_time']:.1f}s - {speaker['end_time']:.1f}s")
            print(f"Длительность: {speaker.get('duration', speaker['end_time'] - speaker['start_time']):.1f}с")
            print(f"Текст: {speaker['text']}")
            print(f"Уверенность: {speaker['confidence']:.2f}")
            print(f"Основная частота: {speaker['voice_features']['fundamental_frequency']:.1f} Hz")
            print(f"Левый канал F0: {speaker['voice_features']['left_f0']:.1f} Hz")
            print(f"Правый канал F0: {speaker['voice_features']['right_f0']:.1f} Hz")
            print(f"Стерео баланс: {speaker['voice_features']['stereo_balance']:.3f}")
        
        # Сохраняем результаты
        print(f"\nСохраняем результаты...")
        
        # TXT файл
        output_txt = f"{os.path.splitext(audio_file)[0]}_transcript_with_tbank_stereo_diarization.txt"
        with open(output_txt, "w", encoding="utf-8") as f:
            f.write("=== ТРАНСКРИПЦИЯ С T-BANK VOICEKIT И АНАЛИЗОМ ГОЛОСОВ (СТЕРЕО) ===\n\n")
            f.write(f"Общее время обработки: {response.get('total_billed_time', 0):.2f} сек\n")
            f.write(f"Количество говорящих: {len(speakers_list)}\n")
            f.write(f"Говорящие: {', '.join(speakers_list)}\n")
            f.write(f"Метод диаризации: {diarization_method}\n")
            f.write(f"Аудио формат: {channels} каналов, {sample_rate}Hz\n\n")
            
            f.write("=== ПРОФИЛИ ГОЛОСОВ (СТЕРЕО) ===\n")
            for speaker in known_speakers:
                f.write(f"{speaker['speaker_id']}:\n")
                f.write(f"  Тип голоса: {speaker['voice_type']}\n")
                f.write(f"  Позиция в стерео: {speaker['stereo_position']}\n")
                f.write(f"  Основная частота: {speaker['avg_fundamental_frequency']:.1f} Hz\n")
                f.write(f"  Левый канал F0: {speaker['avg_left_f0']:.1f} Hz\n")
                f.write(f"  Правый канал F0: {speaker['avg_right_f0']:.1f} Hz\n")
                f.write(f"  Стерео баланс: {speaker['avg_stereo_balance']:.3f}\n")
                f.write(f"  Стабильность: {speaker['stability']:.2f}\n")
                f.write(f"  Стабильность стерео: {speaker['stereo_stability']:.2f}\n")
                f.write(f"  Образцов: {speaker['sample_count']}\n\n")
            
            f.write("=== ПОЛНЫЙ ТРАНСКРИПТ ===\n")
            f.write(full_transcript.strip() + "\n\n")
            
            f.write("=== СЕГМЕНТЫ С T-BANK VOICEKIT И АНАЛИЗОМ ГОЛОСОВ (СТЕРЕО) ===\n")
            for i, speaker in enumerate(speakers_data):
                f.write(f"\n--- СЕГМЕНТ {i+1}: {speaker['speaker']} ---\n")
                f.write(f"Время: {speaker['start_time']:.1f}s - {speaker['end_time']:.1f}s\n")
                f.write(f"Длительность: {speaker.get('duration', speaker['end_time'] - speaker['start_time']):.1f}с\n")
                f.write(f"Текст: {speaker['text']}\n")
                f.write(f"Уверенность: {speaker['confidence']:.2f}\n")
                f.write(f"Основная частота: {speaker['voice_features']['fundamental_frequency']:.1f} Hz\n")
                f.write(f"Левый канал F0: {speaker['voice_features']['left_f0']:.1f} Hz\n")
                f.write(f"Правый канал F0: {speaker['voice_features']['right_f0']:.1f} Hz\n")
                f.write(f"Стерео баланс: {speaker['voice_features']['stereo_balance']:.3f}\n")
        
        # JSON файл
        output_json = f"{os.path.splitext(audio_file)[0]}_transcript_with_tbank_stereo_diarization.json"
        full_results = {
            "transcript": full_transcript.strip(),
            "speakers": speakers_list,
            "speaker_segments": speakers_data,
            "known_speakers": known_speakers,
        }
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(full_results, f, ensure_ascii=False, indent=4)
        
        print(f"Файлы сохранены:")
        print(f"  - {output_txt}")
        print(f"  - {output_json}")
        
        # Удаляем временный файл
        if os.path.exists(temp_path):
            os.remove(temp_path)
            print("Временный файл удален")
        
        print("=== ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО! ===")
        print("Результаты сохранены в файлы с суффиксом '_tbank_stereo_diarization'")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка в recognize_with_tbank_voice_diarization: {e}")
        print(f"ОШИБКА при обработке: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Запуск стерео диаризации T-Bank VoiceKit...")
    
    # Проверяем наличие файла
    if not os.path.exists("6.wav"):
        print("ОШИБКА: Файл 6.wav не найден")
        exit(1)
    
    print("Файл 6.wav найден")
    
    # Запускаем обработку
    success = recognize_with_tbank_voice_diarization("6.wav")
    
    if success:
        print("\n🎉 Обработка завершена успешно!")
    else:
        print("\n💥 Обработка завершена с ошибками!")