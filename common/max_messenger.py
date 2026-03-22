# -*- coding: utf-8 -*-
"""
MAX Bot API: отправка текста, файлов и аудио (дубль сценариев Telegram).
https://dev.max.ru/docs-api
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

MAX_API = "https://platform-api.max.ru"


def _authorization_value(raw_token: str) -> str:
    t = (raw_token or "").strip()
    if not t:
        return ""
    if t.lower().startswith("bearer "):
        return t
    return t


def _extract_upload_token(upload_response_body: Any) -> str:
    if isinstance(upload_response_body, dict):
        tok = upload_response_body.get("token")
        if tok:
            return str(tok)
        payload = upload_response_body.get("payload")
        if isinstance(payload, dict) and payload.get("token"):
            return str(payload["token"])
    raise ValueError(f"Не удалось извлечь token из ответа загрузки: {upload_response_body!r}")


def _upload_to_slot(
    access_token: str,
    upload_url: str,
    file_path: str,
    timeout_upload: int = 300,
) -> str:
    """
    Загрузка файла на fu.oneme.ru (type=file, clientType=10).
    CDN принимает resumable upload: raw binary + Content-Range.
    Multipart даёт 403 «There is no file in request» на этом CDN.
    """
    path = os.path.abspath(file_path)
    filename = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    size = len(data)
    r2 = requests.post(
        upload_url,
        data=data,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}",
        },
        timeout=timeout_upload,
    )
    if not r2.ok:
        logger.warning("MAX upload to slot: %s %s", r2.status_code, r2.text[:500])
        r2.raise_for_status()
    try:
        body = r2.json()
    except json.JSONDecodeError as e:
        raise ValueError(f"MAX: не JSON после загрузки: {r2.text[:500]}") from e
    return _extract_upload_token(body)


def _request_upload_slot(access_token: str, upload_type: str) -> tuple[str, Optional[str]]:
    """Возвращает (upload_url, pre_token).
    Для type=file|image token приходит в ответе на POST на CDN.
    Для type=audio|video в доке MAX token чаще приходит в JSON ответа CDN после загрузки;
    иногда дублируется в ответе /uploads — см. upload_audio_get_token."""
    auth = _authorization_value(access_token)
    r1 = requests.post(
        f"{MAX_API}/uploads",
        params={"type": upload_type},
        headers={"Authorization": auth},
        timeout=60,
    )
    if not r1.ok:
        logger.warning("MAX uploads slot: %s %s", r1.status_code, r1.text)
        r1.raise_for_status()
    slot = r1.json()
    upload_url = slot.get("url")
    if not upload_url:
        raise ValueError(f"MAX /uploads: нет url в ответе: {slot!r}")
    pre_token = slot.get("token") or None
    return upload_url, pre_token


def upload_file_get_token(access_token: str, file_path: str, timeout_upload: int = 300) -> str:
    upload_url, _ = _request_upload_slot(access_token, "file")
    return _upload_to_slot(access_token, upload_url, file_path, timeout_upload=timeout_upload)


def upload_audio_get_token(access_token: str, audio_path: str, timeout_upload: int = 300) -> str:
    """
    Загрузка аудио на CDN по URL из POST /uploads?type=audio.
    Официальный сценарий MAX (dev.max.ru): multipart form, поле ``data``,
    без Authorization на CDN; ``token`` для вложения — в JSON ответа CDN
    (как curl: -F \"data=@file.mp3\"). Raw binary на vu.okcdn.ru даёт 415
    с X-Reason error.fileName — нужен multipart с именем файла в части.
    """
    upload_url, pre_token = _request_upload_slot(access_token, "audio")
    path = os.path.abspath(audio_path)
    filename = os.path.basename(path)

    with open(path, "rb") as f:
        r2 = requests.post(
            upload_url,
            files={"data": (filename, f)},
            timeout=timeout_upload,
        )
    logger.info("MAX audio CDN upload: %s | %s", r2.status_code, r2.text[:400])
    if not r2.ok:
        logger.warning("MAX audio upload to slot: %s %s", r2.status_code, r2.text[:500])
        r2.raise_for_status()
    try:
        body = r2.json()
    except json.JSONDecodeError as e:
        raise ValueError(f"MAX: не JSON после загрузки аудио: {r2.text[:500]}") from e

    try:
        return _extract_upload_token(body)
    except ValueError:
        if pre_token:
            logger.warning(
                "MAX audio: token не найден в ответе CDN %r, используем token из /uploads",
                body,
            )
            return pre_token
        raise


def send_message_with_attachments(
    access_token: str,
    chat_id: int,
    text: str,
    attachments: list,
    *,
    text_format: Optional[str] = "html",
    initial_delay_sec: float = 0.0,
    max_attempts: int = 8,
) -> None:
    auth = _authorization_value(access_token)
    if not auth:
        raise ValueError("Пустой токен MAX")

    url = f"{MAX_API}/messages"
    params = {"chat_id": int(chat_id)}
    headers = {"Authorization": auth, "Content-Type": "application/json"}
    payload: Dict[str, Any] = {"text": (text or "")[:4000]}
    if attachments:
        payload["attachments"] = attachments
    if text_format:
        payload["format"] = text_format

    delay = float(initial_delay_sec)
    last_err: Optional[str] = None

    for attempt in range(max_attempts):
        if attempt > 0:
            time.sleep(delay)
            delay = min(delay * 2.0, 30.0)

        r = requests.post(url, params=params, headers=headers, data=json.dumps(payload), timeout=120)
        if r.ok:
            return

        try:
            err = r.json()
        except Exception:
            err = {"raw": r.text[:500]}
        last_err = str(err)

        code = err.get("code") if isinstance(err, dict) else None
        if code == "attachment.not.ready":
            logger.info("MAX: вложение ещё не готово, попытка %s/%s", attempt + 1, max_attempts)
            continue

        logger.warning("MAX send message: %s %s", r.status_code, r.text)
        r.raise_for_status()

    raise RuntimeError(f"MAX: не удалось отправить сообщение после {max_attempts} попыток: {last_err}")


def send_max_text(access_token: str, chat_id_raw: str, text: str, *, text_format: str = "html") -> None:
    """Текст без вложений (аналог sendMessage)."""
    chat_id = int(str(chat_id_raw).strip())
    send_message_with_attachments(
        access_token,
        chat_id,
        text,
        [],
        text_format=text_format,
        initial_delay_sec=0.0,
        max_attempts=3,
    )


def send_max_text_chunked(
    access_token: str,
    chat_id_raw: str,
    text: str,
    *,
    text_format: str = "html",
    max_chunk: int = 3800,
) -> None:
    """
    Длинный текст несколькими сообщениями (лимит поля text в MAX ~4000 символов).
    Старается резать по переводу строки в хвосте чанка, чтобы реже рвать разметку.
    """
    t = text or ""
    if not t.strip():
        return
    if len(t) <= max_chunk:
        send_max_text(access_token, chat_id_raw, t, text_format=text_format)
        return
    i = 0
    n = len(t)
    while i < n:
        end = min(i + max_chunk, n)
        if end < n:
            nl = t.rfind("\n", i, end)
            if nl != -1 and nl > i + max_chunk // 2:
                end = nl + 1
        chunk = t[i:end]
        if chunk.strip():
            send_max_text(access_token, chat_id_raw, chunk, text_format=text_format)
        i = end


def send_message_with_file(
    access_token: str,
    chat_id: int,
    file_token: str,
    text: str,
    *,
    initial_delay_sec: float = 1.0,
    max_attempts: int = 8,
) -> None:
    attachments = [{"type": "file", "payload": {"token": file_token}}]
    send_message_with_attachments(
        access_token,
        chat_id,
        text,
        attachments,
        text_format="html",
        initial_delay_sec=initial_delay_sec,
        max_attempts=max_attempts,
    )


def send_message_with_audio(
    access_token: str,
    chat_id: int,
    audio_token: str,
    caption: str,
    *,
    initial_delay_sec: float = 1.0,
    max_attempts: int = 8,
) -> None:
    attachments = [{"type": "audio", "payload": {"token": audio_token}}]
    send_message_with_attachments(
        access_token,
        chat_id,
        caption,
        attachments,
        text_format="html",
        initial_delay_sec=initial_delay_sec,
        max_attempts=max_attempts,
    )


def send_excel_report_to_max(
    access_token: str,
    chat_id_raw: str,
    file_path: str,
    caption: str,
) -> None:
    chat_id = int(str(chat_id_raw).strip())
    file_token = upload_file_get_token(access_token, file_path)
    time.sleep(1.0)
    send_message_with_file(access_token, chat_id, file_token, caption)


def send_audio_file_to_max(
    access_token: str,
    chat_id_raw: str,
    audio_path: str,
    caption: str,
) -> bool:
    """Аудио как вложение (аналог sendAudio). При сбое audio — дубль как обычный file."""
    chat_id = int(str(chat_id_raw).strip())
    try:
        tok = upload_audio_get_token(access_token, audio_path)
        time.sleep(3.0)
        send_message_with_audio(access_token, chat_id, tok, caption)
        logger.info("MAX audio sent ok: chat=%s file=%s", chat_id, os.path.basename(audio_path))
        return True
    except Exception as e:
        logger.error("MAX send_audio_file_to_max FAILED: %s | file=%s", e, audio_path)
        try:
            send_excel_report_to_max(access_token, chat_id_raw, audio_path, caption)
            logger.info("MAX: запись отправлена как file (fallback после сбоя audio)")
            return True
        except Exception as e2:
            logger.error("MAX send_audio_file_to_max fallback file FAILED: %s", e2)
            return False
