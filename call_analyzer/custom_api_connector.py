# -*- coding: utf-8 -*-
"""Скачивание записи и формирование имени файла для источника «Кастомный API»."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

logger = logging.getLogger(__name__)


def build_custom_api_filename(original_filename: str, station_code: str) -> str:
    """
    originalBase_<station>.ext — только цифры добавочного, без суффикса __sk_.
    """
    station_clean = re.sub(r'\D', '', str(station_code)) or '0'
    name = (original_filename or '').strip()
    if not name:
        name = 'recording.mp3'
    p = Path(name)
    stem = p.stem or 'recording'
    ext = p.suffix.lower() if p.suffix else '.mp3'
    if ext not in ('.mp3', '.wav', '.ogg'):
        ext = '.mp3'
    stem_safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', stem).strip() or 'recording'
    stem_safe = stem_safe[:180]
    return f"{stem_safe}_{station_clean}{ext}"


def download_recording(
    url: str,
    save_path: Path,
    timeout: int = 120,
    verify_ssl: bool = True,
) -> bool:
    """Скачивает файл по HTTP(S). Локальные пути не поддерживаются."""
    u = (url or '').strip()
    if not u.lower().startswith(('http://', 'https://')):
        logger.error('custom_api: URL записи должен начинаться с http:// или https://')
        return False
    try:
        if not verify_ssl:
            requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
        resp = requests.get(u, timeout=timeout, stream=True, verify=verify_ssl)
        resp.raise_for_status()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return save_path.exists() and save_path.stat().st_size > 0
    except Exception as e:
        logger.error('custom_api download error: %s', e, exc_info=True)
        return False
