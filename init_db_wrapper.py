# -*- coding: utf-8 -*-
"""Обертка для инициализации БД - находит путь автоматически"""
import sys
import os
from pathlib import Path

# Находим директорию этого скрипта
script_dir = Path(__file__).resolve().parent
os.chdir(str(script_dir))

# Добавляем в путь
sys.path.insert(0, str(script_dir))

# Устанавливаем UTF-8 для Windows
if sys.platform == 'win32':
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

print(f"Рабочая директория: {script_dir}")
print(f"Python: {sys.executable}")

# Импортируем и запускаем
try:
    from scripts.init_db import *
except SystemExit:
    raise
except Exception as e:
    print(f"Ошибка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

