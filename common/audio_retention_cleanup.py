# common/audio_retention_cleanup.py
"""
Удаление просроченных аудиофайлов из каталога записей пользователя.
Транскрипции, разборы (папки transcriptions, transcript и т.п.) не трогаются.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional, Set

logger = logging.getLogger(__name__)

# Подкаталоги, где не удаляем аудио (только записи из «дневных» папок YYYY/MM/DD).
_PROTECTED_DIR_NAMES = frozenset(
    name.lower()
    for name in (
        "transcriptions",
        "transcript",
        "config",
        "runtime",
        "testscalls",
        "__pycache__",
    )
)

_DEFAULT_AUDIO_EXT = frozenset({".mp3", ".wav", ".ogg", ".flac", ".m4a"})


def _normalize_extensions(extra: Optional[Iterable[str]]) -> Set[str]:
    exts = set(_DEFAULT_AUDIO_EXT)
    if not extra:
        return exts
    for e in extra:
        if not e:
            continue
        s = str(e).strip().lower()
        if not s.startswith("."):
            s = "." + s
        exts.add(s)
    return exts


def _path_has_protected_dir(path: Path) -> bool:
    return any(p.lower() in _PROTECTED_DIR_NAMES for p in path.parts)


def extract_call_date_from_path(path: Path) -> Optional[date]:
    """
    Ищет в пути последовательность YYYY/MM/DD (последнее вхождение — дата папки дня).
    """
    parts = path.parts
    last: Optional[date] = None
    for i in range(len(parts) - 2):
        y, m, d = parts[i], parts[i + 1], parts[i + 2]
        if (
            len(y) == 4
            and y.isdigit()
            and len(m) == 2
            and m.isdigit()
            and len(d) == 2
            and d.isdigit()
        ):
            try:
                yi, mi, di = int(y), int(m), int(d)
                last = date(yi, mi, di)
            except ValueError:
                continue
    return last


def cleanup_expired_audio_files(
    base_path: Path,
    retention_days: int,
    *,
    extra_extensions: Optional[Iterable[str]] = None,
) -> int:
    """
    Удаляет аудиофайлы не моложе retention_days по возрасту (по дате из пути YYYY/MM/DD,
    иначе по дате модификации файла). Возраст в днях >= retention_days — файл удаляется.

    Returns:
        Число удалённых файлов.
    """
    if retention_days <= 0:
        return 0

    base = Path(base_path)
    if not base.is_dir():
        logger.warning("audio retention: каталог не найден: %s", base)
        return 0

    today = date.today()
    exts = _normalize_extensions(extra_extensions)
    deleted = 0

    for root, _dirs, files in os.walk(base, topdown=True, followlinks=False):
        root_path = Path(root)
        if _path_has_protected_dir(root_path):
            continue

        for name in files:
            fp = root_path / name
            try:
                if not fp.is_file():
                    continue
            except OSError:
                continue

            suf = fp.suffix.lower()
            if suf not in exts:
                continue

            call_date = extract_call_date_from_path(fp)
            if call_date is None:
                try:
                    mtime = fp.stat().st_mtime
                    call_date = datetime.fromtimestamp(mtime).date()
                except OSError:
                    continue

            age_days = (today - call_date).days
            if age_days < retention_days:
                continue

            try:
                fp.unlink()
                deleted += 1
                logger.info("audio retention: удалён %s (возраст %s дн., порог %s)", fp, age_days, retention_days)
            except OSError as e:
                logger.warning("audio retention: не удалось удалить %s: %s", fp, e)

    return deleted
