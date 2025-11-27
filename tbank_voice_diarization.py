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

# Семантические словари для определения ролей
SEMANTIC_VOCAB = {
    "manager": [
        "сервис", "центр", "мастер", "приемщик", "компания", "бествей", "bestway",
        "администратор", "запись", "записать", "свободное", "время", "дата",
        "стоимость", "цена", "рублей", "диагностика", "осмотр", "ремонт",
        "запчасти", "детали", "заказ", "ожидать", "готово", "забирать",
        "документы", "подпишите", "касса", "оплата", "гарантия",
        "алло", "здравствуйте", "добрый день", "добрый вечер", "доброе утро",
        "узнаю", "перезвоню", "подсказать", "уточнить"
    ],
    "client": [
        "я", "мне", "мое", "моя", "машина", "автомобиль", "стучит", "гремит",
        "сломалась", "не едет", "глохнет", "шумит", "скрипит", "течет",
        "пробег", "год", "модель", "марка", "вин", "номер",
        "когда", "сколько", "можно", "приеду", "подъеду", "заберу",
        "посмотрите", "проверьте", "сделайте", "поменяйте",
        "лада", "гранта", "веста", "рио", "солярис", "киа", "хендай",
        "тойота", "ниссан", "фольксваген", "шкода", "мазда", "форд",
        "опель", "рено", "ситроен", "пежо", "хонда", "сузуки", "митсубиси",
        "мерседес", "бмв", "ауди", "лексус", "инфинити", "вольво", "ленд ровер",
        "ягуар", "порше", "субару", "фиат", "джип", "додж", "крайслер", "кадиллак",
        "шевроле", "уаз", "газ", "ваз", "нива", "патриот", "ларгус", "веста", "иксрей",
        "черри", "хавал", "джили", "чанган", "эксид", "омода"
    ]
}

def apply_semantic_correction(speakers_data: List[Dict]) -> List[Dict]:
    """
    Применяет семантическую коррекцию диаризации на основе анализа текста.
    1. Определяет роли спикеров (Менеджер/Клиент).
    2. Исправляет очевидные ошибки атрибуции на основе ключевых слов.
    3. Сглаживает короткие "вставки" (sandwich rule).
    """
    if not speakers_data:
        return speakers_data

    logger.info("Запуск семантической пост-обработки диаризации...")
    
    # 1. Определение ролей спикеров
    speaker_scores = {
        "SPEAKER_01": {"manager": 0, "client": 0},
        "SPEAKER_02": {"manager": 0, "client": 0}
    }
    
    # Анализируем первые 10 сегментов для определения ролей (приветствие и суть)
    # и весь диалог для общей статистики
    for i, segment in enumerate(speakers_data):
        text = segment.get("text", "").lower()
        speaker = segment.get("speaker")
        
        # Вес слов в начале диалога выше (представление)
        weight = 2.0 if i < 5 else 1.0
        
        for word in SEMANTIC_VOCAB["manager"]:
            if word in text:
                speaker_scores[speaker]["manager"] += weight
                
        for word in SEMANTIC_VOCAB["client"]:
            if word in text:
                speaker_scores[speaker]["client"] += weight

    # Определяем, кто есть кто
    s1_m_score = speaker_scores["SPEAKER_01"]["manager"]
    s2_m_score = speaker_scores["SPEAKER_02"]["manager"]
    
    manager_id = "SPEAKER_01" if s1_m_score >= s2_m_score else "SPEAKER_02"
    client_id = "SPEAKER_02" if manager_id == "SPEAKER_01" else "SPEAKER_01"
    
    logger.info(f"Семантический анализ ролей: Менеджер={manager_id} (score={max(s1_m_score, s2_m_score)}), Клиент={client_id}")

    corrected_data = []
    changes_count = 0
    
    # 2. Якорная коррекция и разделение смешанных сегментов
    new_corrected_data = []
    
    for i, segment in enumerate(speakers_data):
        text = segment.get("text", "").lower()
        current_speaker = segment.get("speaker")
        original_speaker = current_speaker
        start_time = segment.get("start_time")
        end_time = segment.get("end_time")
        
        # Проверяем, не является ли сегмент смешанным (диалог внутри одного сегмента)
        # Паттерн: Вопрос (менеджер) -> Ответ (клиент) или наоборот
        # Пример: "какой автомобиль у вас а какие спекта седьмой год" -> "какой автомобиль у вас" (М) + "а какие спекта седьмой год" (К)
        
        # Список разделителей фраз
        split_phrases = [
            "какой автомобиль", "какая машина", "какой год", "какой пробег",
            "как вас зовут", "на какое время", "когда удобно"
        ]
        
        is_split = False
        
        # Если текущий спикер - Клиент, но в тексте есть явный вопрос Менеджера
        if current_speaker == client_id:
             for phrase in split_phrases:
                 if phrase in text:
                     # Ищем позицию фразы
                     idx = text.find(phrase)
                     if idx > 5: # Если фраза не в самом начале (иначе это просто ошибка атрибуции всего сегмента)
                         # Разделяем сегмент
                         split_point_time = start_time + (end_time - start_time) * (idx / len(text))
                         
                         # Первая часть (до вопроса) - Клиент
                         part1_text = segment["text"][:idx].strip()
                         part1 = segment.copy()
                         part1["text"] = part1_text
                         part1["end_time"] = split_point_time
                         part1["speaker"] = client_id
                         
                         # Вторая часть (вопрос) - Менеджер
                         part2_text = segment["text"][idx:].strip()
                         part2 = segment.copy()
                         part2["text"] = part2_text
                         part2["start_time"] = split_point_time
                         part2["speaker"] = manager_id
                         
                         new_corrected_data.append(part1)
                         new_corrected_data.append(part2)
                         logger.info(f"Разделение смешанного сегмента {i}: '{text}' -> '{part1_text}' (К) + '{part2_text}' (М)")
                         is_split = True
                         changes_count += 1
                         break
        
        if is_split:
            continue

        # Считаем слова
        m_words = sum(1 for w in SEMANTIC_VOCAB["manager"] if w in text)
        c_words = sum(1 for w in SEMANTIC_VOCAB["client"] if w in text)
        
        # Если спикер Клиент, но говорит "Я перезвоню" или "Узнаю цену" -> Менеджер
        if current_speaker == client_id:
            if m_words >= 2 or \
               ("узнаю" in text and "перезвоню" in text) or \
               ("стоимость" in text and "рублей" in text and "?" not in text) or \
               ("сервис" in text and "центр" in text) or \
               ("какой автомобиль" in text): # Явный вопрос менеджера
                current_speaker = manager_id
                logger.debug(f"Коррекция сегмента {i}: {original_speaker} -> {manager_id} (strong manager keywords)")

        # Если спикер Менеджер, но называет марку авто или спрашивает цену -> Клиент
        elif current_speaker == manager_id:
            if c_words >= 2 or \
               any(brand in text for brand in SEMANTIC_VOCAB["client"][30:]) or \
               ("сколько" in text and "стоит" in text) or \
               ("подскажите" in text and "пожалуйста" in text) or \
               ("седьмой год" in text): # Ответ про год
                current_speaker = client_id
                logger.debug(f"Коррекция сегмента {i}: {original_speaker} -> {client_id} (strong client keywords)")
        
        # Сохраняем (возможно измененный) сегмент
        new_segment = segment.copy()
        new_segment["speaker"] = current_speaker
        new_corrected_data.append(new_segment)
        
        if current_speaker != original_speaker:
            changes_count += 1

    # Используем новый список сегментов для следующего этапа
    corrected_data = new_corrected_data
    
    # 3. Сглаживание (Sandwich rule) и коррекция коротких ответов
    # Ищем паттерны A -> B (коротко) -> A и меняем B на A, если B семантически пуст
    final_data = []
    if corrected_data:
        final_data.append(corrected_data[0])
        
        for i in range(1, len(corrected_data) - 1):
            prev_seg = final_data[-1] # Уже обработанный предыдущий
            curr_seg = corrected_data[i]
            next_seg = corrected_data[i+1]
            
            prev_spk = prev_seg["speaker"]
            curr_spk = curr_seg["speaker"]
            next_spk = next_seg["speaker"]
            
            # Если сегмент "зажат" другим спикером
            if prev_spk == next_spk and curr_spk != prev_spk:
                text = curr_seg.get("text", "").lower().strip()
                words_count = len(text.split())
                duration = curr_seg["end_time"] - curr_seg["start_time"]
                
                # Условия "незначительности" сегмента:
                # 1. Очень короткий (< 1.5 сек)
                # 2. Мало слов (< 3)
                # 3. Нет явных ключевых слов "чужого" типа
                is_short = duration < 1.5 or words_count <= 3
                is_neutral = True
                
                # Проверяем, не содержит ли он важных слов СВОЕГО (текущего) типа
                curr_role_vocab = SEMANTIC_VOCAB["manager"] if curr_spk == manager_id else SEMANTIC_VOCAB["client"]
                for w in curr_role_vocab:
                    if w in text:
                        is_neutral = False
                        break
                
                if is_short and is_neutral:
                    # Проверяем контекст вопроса
                    # Если предыдущий спикер задал вопрос, а текущий коротко ответил "да/нет",
                    # то текущий спикер должен быть ДРУГИМ.
                    # Если sandwich rule пытается сделать их ОДНИМ, это ошибка.
                    
                    # Но если это просто пауза/вдох/шум, который ошибочно приписан другому, то sandwich rule верен.
                    
                    # В данном случае, доверяем sandwich rule для "схлопывания" мусорных сегментов
                    logger.debug(f"Сглаживание сегмента {i}: {curr_spk} -> {prev_spk} (sandwich rule: '{text}')")
                    curr_seg["speaker"] = prev_spk
                    changes_count += 1
            
            # Дополнительное правило: короткие ответы "да/нет/хорошо" после длинной фразы другого спикера
            # должны оставаться у другого спикера (т.е. это диалог), а не прилипать (если это не sandwich)
            elif prev_spk != curr_spk:
                 text = curr_seg.get("text", "").lower().strip()
                 words = text.split()
                 if len(words) <= 3 and any(w in text for w in ["да", "нет", "ага", "хорошо", "ладно", "угу", "спасибо", "пожалуйста"]):
                     # Это похоже на валидный ответ, не меняем спикера
                     pass
            
            final_data.append(curr_seg)
        
        final_data.append(corrected_data[-1])
    else:
        final_data = corrected_data

    logger.info(f"Семантическая коррекция завершена: {changes_count} изменений")
    return final_data

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
        
        # Spectral Contrast для левого канала (добавляем для улучшения моно диаризации)
        try:
            contrast_left = librosa.feature.spectral_contrast(y=segment_samples, sr=sample_rate)
            contrast_mean_left = np.mean(contrast_left)
        except Exception:
            contrast_mean_left = 0

        # MFCC для правого канала (если есть)
        mfcc_right = np.zeros_like(mfcc_left)
        contrast_mean_right = 0
        if right_segment_samples is not None and len(right_segment_samples) > 0:
            mfcc_right = librosa.feature.mfcc(y=right_segment_samples, sr=sample_rate, n_mfcc=13)
            try:
                contrast_right = librosa.feature.spectral_contrast(y=right_segment_samples, sr=sample_rate)
                contrast_mean_right = np.mean(contrast_right)
            except Exception:
                contrast_mean_right = 0
        
        # Используем средние значения MFCC и Contrast
        mfcc = (np.mean(mfcc_left, axis=1) + np.mean(mfcc_right, axis=1)) / 2
        
        # Если правый канал есть, берем среднее, иначе только левый
        if right_segment_samples is not None and len(right_segment_samples) > 0:
            spectral_contrast = (contrast_mean_left + contrast_mean_right) / 2
        else:
            spectral_contrast = contrast_mean_left
        
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
            "spectral_contrast": float(spectral_contrast),
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
    avg_spectral_contrast = np.mean([f.get("spectral_contrast", 0) for f in voice_features])
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
        "avg_spectral_contrast": avg_spectral_contrast,
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

        # Вычисляем схожесть по спектральному контрасту
        avg_contrast = speaker.get("avg_spectral_contrast", 0)
        if avg_contrast == 0:
             avg_contrast = np.mean([f.get("spectral_contrast", 0) for f in speaker.get("voice_features", [])]) if speaker.get("voice_features") else 0
        
        contrast_diff = abs(voice_features.get("spectral_contrast", 0) - avg_contrast)
        contrast_score = 1.0 / (1.0 + contrast_diff / 5)
        
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
        
        # Для моно аудио стерео-характеристики неинформативны, перераспределяем веса
        # Проверяем, является ли это моно (нет правого канала - right_f0 == 0)
        is_mono = (voice_features.get("right_f0", 0) == 0 and 
                   voice_features.get("channel_difference", 0) == 0)
        
        if is_mono:
            # Для моно: используем голосовые характеристики (F0, spectral, MFCC, contrast)
            # Перераспределяем веса: F0 и MFCC более важны, добавляем Contrast
            # Увеличиваем вес MFCC и F0, так как они наиболее надежны для идентификации голоса
            total_score = (f0_score * 0.35 + spectral_score * 0.1 + mfcc_score * 0.35 + contrast_score * 0.2)
        else:
            # Для стерео: используем все характеристики
            total_score = (f0_score * 0.2 + spectral_score * 0.1 + mfcc_score * 0.15 + contrast_score * 0.1 +
                          stereo_score * 0.25 + channel_score * 0.2)
        
        if total_score > best_score:
            best_score = total_score
            best_match = speaker["speaker_id"]
    
    # Если score слишком низкий, создаем нового спикера
    # Ограничиваем количество спикеров до 2
    if best_score < 0.4:  # Повышенный порог для лучшего различения спикеров
        if len(known_speakers) < 2:
            new_speaker_id = f"SPEAKER_{len(known_speakers) + 1:02d}"
            return new_speaker_id, 0.3
        else:
            # Если уже есть 2 спикера, выбираем наиболее похожего, но с низким confidence
            # Это позволит вызывающему коду использовать чередование
            return best_match if best_match else "SPEAKER_01", best_score if best_score > 0 else 0.3
    
    # Если score высокий, возвращаем найденного спикера
    return best_match, best_score

def tbank_with_voice_analysis_diarization(transcript_data: Dict, audio_file: str) -> Dict:
    """
    Диаризация с использованием T-Bank VoiceKit и анализа голосов.
    Поддерживает как моно, так и стерео аудио. Всегда определяет 2 спикера.
    """
    logger.info("Используем T-Bank VoiceKit с анализом голосов для диаризации...")
    
    # Загружаем аудио файл
    try:
        audio = AudioSegment.from_file(audio_file)
        # Работаем с оригинальным аудио (моно или стерео)
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
    is_stereo = audio.channels >= 2
    
    logger.info(f"Диаризация для {'стерео' if is_stereo else 'моно'} аудио ({audio.channels} каналов)")
    
    for i, segment in enumerate(segments):
        if not segment:
            continue
        
        start_time = segment[0]["start_time"]
        end_time = segment[-1]["end_time"]
        
        # Извлекаем характеристики голоса
        voice_features = extract_voice_features(audio, start_time, end_time)
        
        # Определяем спикера в зависимости от типа аудио
        if is_stereo:
            # Для стерео: используем стерео баланс
            stereo_balance = voice_features.get("stereo_balance", 0)
            if stereo_balance > 0.1:  # Левый канал или центр с положительным балансом
                speaker_id = "SPEAKER_02"
            else:  # Правый канал или центр с отрицательным балансом
                speaker_id = "SPEAKER_01"
            confidence = 0.7
        else:
            # Для моно: используем гибридный подход - чередование + анализ голоса
            if len(known_speakers) == 0:
                # Первый сегмент - всегда SPEAKER_01
                speaker_id = "SPEAKER_01"
                confidence = 0.5
            elif len(known_speakers) == 1:
                # Если есть только один спикер, создаем второго
                speaker_id = "SPEAKER_02"
                confidence = 0.5
            else:
                # Если уже есть 2 спикера, используем полноценный анализ голоса вместо принудительного чередования
                best_match, score = identify_speaker_by_voice(voice_features, known_speakers)
                
                # Логика "инерции" разговора:
                # Если скор не очень высокий, отдаем небольшое предпочтение предыдущему спикеру
                # (люди редко говорят по одной короткой фразе, часто говорят блоками)
                if len(speakers_data) > 0:
                    last_speaker = speakers_data[-1].get("speaker")
                    
                    # Получаем характеристики последнего сегмента этого спикера для сравнения
                    # Это помогает понять, продолжается ли та же фраза/мысль
                    
                    # Если алгоритм предлагает сменить спикера
                    if last_speaker != best_match:
                        # Вводим штраф за переключение спикера ("инерция")
                        # Если уверенность в смене спикера низкая (score < 0.65), оставляем старого
                        if score < 0.65:
                            logger.debug(f"Сегмент {i+1} моно: удержание спикера {last_speaker} (score смены {score:.2f} < 0.65)")
                            best_match = last_speaker
                            # Снижаем уверенность, так как мы пошли против алгоритма
                            score = max(0.4, score * 0.8)
                    
                    # Если алгоритм предлагает того же спикера
                    if last_speaker == best_match:
                        score += 0.15 # Повышенный бонус за непрерывность
                
                speaker_id = best_match
                confidence = score
                logger.debug(f"Сегмент {i+1} моно: анализ -> {speaker_id} (score={score:.2f})")
        
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
    
    # Применяем семантическую пост-обработку
    try:
        speakers_data = apply_semantic_correction(speakers_data)
    except Exception as e:
        logger.error(f"Ошибка семантической коррекции: {e}", exc_info=True)
        # Не прерываем работу, если семантика упала
    
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
    if not os.path.exists("5.mp3"):
        print("ОШИБКА: Файл 5.mp3 не найден")
        exit(1)
    
    print("Файл 5.mp3 найден")
    
    # Запускаем обработку
    success = recognize_with_tbank_voice_diarization("5.mp3")
    
    if success:
        print("\n🎉 Обработка завершена успешно!")
    else:
        print("\n💥 Обработка завершена с ошибками!")