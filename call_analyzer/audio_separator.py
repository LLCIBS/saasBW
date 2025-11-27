import os
import torch
import torchaudio
from speechbrain.inference.separation import SepformerSeparation
from pydub import AudioSegment
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Глобальная переменная для модели, чтобы не загружать каждый раз
_SEPARATOR_MODEL = None

def get_separator_model():
    global _SEPARATOR_MODEL
    if _SEPARATOR_MODEL is None:
        logger.info("Загрузка модели SpeechBrain SepFormer (может занять время при первом запуске)...")
        try:
            _SEPARATOR_MODEL = SepformerSeparation.from_hparams(
                source="speechbrain/sepformer-libri2mix",
                savedir="pretrained_models/sepformer-libri2mix",
                run_opts={"device": "cuda" if torch.cuda.is_available() else "cpu"}
            )
            logger.info("Модель SepFormer успешно загружена")
        except Exception as e:
            logger.error(f"Ошибка при загрузке модели SepFormer: {e}")
            raise
    return _SEPARATOR_MODEL

def convert_mono_to_stereo_split(input_file: str, output_file: str) -> bool:
    """
    Превращает моно запись в псевдо-стерео, разделяя спикеров с помощью нейросети.
    Левый канал - Спикер 1, Правый канал - Спикер 2.
    """
    try:
        model = get_separator_model()
        
        logger.info(f"Начинаем разделение голосов для файла: {input_file}")
        
        # SpeechBrain требует, чтобы файл был совместим (обычно 8kHz или 16kHz)
        # SepFormer-libri2mix работает лучше всего на 8kHz
        
        # 1. Разделение
        est_sources = model.separate_file(path=input_file)
        
        # est_sources shape: [batch, time, sources]
        # Берем первый элемент батча
        src1 = est_sources[:, :, 0].detach().cpu()
        src2 = est_sources[:, :, 1].detach().cpu()
        
        # 2. Сохранение временных файлов
        temp_dir = Path(output_file).parent
        temp_s1 = temp_dir / "temp_sep_s1.wav"
        temp_s2 = temp_dir / "temp_sep_s2.wav"
        
        # Сохраняем в 8kHz (родная частота модели)
        torchaudio.save(str(temp_s1), src1, 8000)
        torchaudio.save(str(temp_s2), src2, 8000)
        
        # 3. Сведение в стерео
        s1_seg = AudioSegment.from_wav(str(temp_s1))
        s2_seg = AudioSegment.from_wav(str(temp_s2))
        
        # Если длительности отличаются (из-за округлений), подравниваем
        min_len = min(len(s1_seg), len(s2_seg))
        s1_seg = s1_seg[:min_len]
        s2_seg = s2_seg[:min_len]
        
        # Создаем стерео: левый канал - s1, правый - s2
        # AudioSegment.from_mono_audiosegments создает честное стерео
        stereo_sound = AudioSegment.from_mono_audiosegments(s1_seg, s2_seg)
        
        # Экспортируем
        # Ресемплим обратно в 16kHz для T-Bank, если нужно, но 8kHz тоже ок
        stereo_sound = stereo_sound.set_frame_rate(16000) 
        stereo_sound.export(output_file, format="wav")
        
        logger.info(f"Разделение завершено. Стерео файл сохранен: {output_file}")
        
        # Чистим
        if temp_s1.exists(): os.remove(temp_s1)
        if temp_s2.exists(): os.remove(temp_s2)
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при разделении аудио: {e}", exc_info=True)
        return False


