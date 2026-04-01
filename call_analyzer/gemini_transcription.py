# -*- coding: utf-8 -*-
"""
Транскрибация аудио через Google Gemini API (пакет google-genai), по той же схеме,
что и в проекте okpd-2-procurement-guide: клиент GoogleGenAI / generateContent.
Ключ API — из настроек профиля (api_keys.gemini_api_key) или переменной GEMINI_API_KEY.
"""
from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from call_analyzer.gemini_proxy import mask_proxy_for_log, resolve_gemini_proxy_url
except ImportError:
    from gemini_proxy import mask_proxy_for_log, resolve_gemini_proxy_url

# Лимит inline-части для multimodal; больше — загрузка через Files API
_MAX_INLINE_BYTES = 18 * 1024 * 1024


def _mime_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    mapping = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
    }
    if ext in mapping:
        return mapping[ext]
    guess, _ = mimetypes.guess_type(str(path))
    return guess or "audio/mpeg"


def _build_prompt(stereo_mode: bool, additional_vocab) -> str:
    lines = [
        "Ты помогаешь расшифровать запись телефонного разговора (автосервис / контакт-центр).",
        "Верни полную дословную транскрипцию на русском языке.",
        'Формат: каждая реплика с новой строки, префикс спикера, например: "Спикер 1: …" или "Оператор: …" / "Клиент: …".',
        "Не добавляй вступлений и пояснений, только текст диалога.",
    ]
    if stereo_mode:
        lines.append(
            "Запись стерео: каналы могут соответствовать разным участникам — разделяй реплики по спикерам."
        )
    if additional_vocab and isinstance(additional_vocab, list) and len(additional_vocab) > 0:
        sample = ", ".join(str(x) for x in additional_vocab[:80])
        if len(additional_vocab) > 80:
            sample += ", …"
        lines.append(f"Учти возможные имена и термины из предметной области: {sample}.")
    return "\n".join(lines)


def transcribe_audio_with_gemini(
    file_path,
    api_key: str,
    model: str,
    stereo_mode: bool = False,
    additional_vocab=None,
    timeout: int = 600,
):
    """
    Транскрибирует файл через Gemini. Возвращает текст или None при ошибке.
    """
    try:
        import httpx
        from google import genai
        from google.genai import types
    except ImportError:
        logger.error(
            "Пакет google-genai не установлен. Установите: pip install google-genai"
        )
        return None

    path = Path(file_path)
    if not path.is_file():
        logger.error("Gemini транскрипция: файл не найден: %s", file_path)
        return None

    key = (api_key or "").strip()
    if not key:
        key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        logger.error("Gemini транскрипция: не задан API-ключ (настройки или GEMINI_API_KEY).")
        return None

    model_id = (model or os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()
    prompt = _build_prompt(stereo_mode, additional_vocab)

    size = path.stat().st_size
    logger.info(
        "Gemini транскрипция: model=%s, file=%s, size=%s байт, stereo=%s",
        model_id,
        path.name,
        size,
        stereo_mode,
    )

    # Прокси только для этого httpx-клиента (как withGeminiProxy в okpd), trust_env=False —
    # не подмешивать переменные окружения к маршрутизации внутри клиента.
    httpx_client = None
    http_opts = None
    try:
        proxy_url = resolve_gemini_proxy_url()
    except ValueError as ve:
        logger.error("Неверный GEMINI_PROXY: %s", ve)
        proxy_url = None

    if proxy_url:
        logger.info(
            "Gemini: исходящий трафик API через прокси: %s",
            mask_proxy_for_log(proxy_url),
        )
        httpx_client = httpx.Client(
            proxy=proxy_url,
            timeout=float(timeout or 600),
            trust_env=False,
        )
        http_opts = types.HttpOptions(httpx_client=httpx_client)
    elif timeout:
        http_opts = types.HttpOptions(timeout=int(timeout))

    client = None
    try:
        if http_opts is not None:
            client = genai.Client(api_key=key, http_options=http_opts)
        else:
            client = genai.Client(api_key=key)
        gen_cfg = None
        uploaded = None
        try:
            if size <= _MAX_INLINE_BYTES:
                data = path.read_bytes()
                mime = _mime_for_path(path)
                parts = [
                    types.Part.from_bytes(data=data, mime_type=mime),
                    prompt,
                ]
                contents = parts
            else:
                logger.info(
                    "Файл больше %s МБ — загрузка через Files API",
                    _MAX_INLINE_BYTES // (1024 * 1024),
                )
                uploaded = client.files.upload(file=str(path))
                contents = [uploaded, prompt]

            response = client.models.generate_content(
                model=model_id,
                contents=contents,
                config=gen_cfg,
            )

            text = getattr(response, "text", None)
            if not text and getattr(response, "candidates", None):
                try:
                    parts_out = response.candidates[0].content.parts
                    text = "".join(
                        getattr(p, "text", "") or "" for p in (parts_out or [])
                    )
                except (IndexError, AttributeError, TypeError):
                    text = None

            text = (text or "").strip()
            if not text:
                logger.error("Gemini вернул пустой текст для %s", path.name)
                return None
            return text
        except Exception as e:
            logger.error("Ошибка Gemini транскрипции: %s", e, exc_info=True)
            return None
        finally:
            if uploaded is not None and client is not None:
                try:
                    fname = getattr(uploaded, "name", None)
                    if fname:
                        client.files.delete(name=fname)
                except Exception as del_exc:
                    logger.debug(
                        "Не удалось удалить временный файл Gemini: %s", del_exc
                    )
    finally:
        if httpx_client is not None:
            try:
                httpx_client.close()
            except Exception:
                pass
