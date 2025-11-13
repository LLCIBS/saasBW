#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Обертка для запуска инициализации БД"""

import sys
import os
from pathlib import Path

# Находим директорию скрипта
script_dir = Path(__file__).resolve().parent
os.chdir(str(script_dir))
sys.path.insert(0, str(script_dir))

# Запускаем инициализацию
if sys.platform == 'win32':
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

exec(open('scripts/init_db.py', encoding='utf-8').read())

