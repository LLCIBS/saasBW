# -*- coding: utf-8 -*-
"""Обратная совместимость: реализация в common.max_messenger."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from common.max_messenger import (  # noqa: E402
    MAX_API,
    send_audio_file_to_max,
    send_excel_report_to_max,
    send_max_text,
    send_message_with_file,
    upload_audio_get_token,
    upload_file_get_token,
)
