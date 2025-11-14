#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для добавления таблицы ftp_connections в базу данных
"""

import sys
from pathlib import Path

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from database.models import db, FtpConnection
from web_interface.app import app

def main():
    """Создает таблицу ftp_connections в базе данных"""
    with app.app_context():
        try:
            # Создаем таблицу
            db.create_all()
            print("✓ Таблица ftp_connections создана или уже существует")
            
            # Проверяем, что таблица существует
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'ftp_connections' in tables:
                print("✓ Таблица ftp_connections успешно создана в базе данных")
            else:
                print("⚠ Предупреждение: таблица ftp_connections не найдена")
                
        except Exception as e:
            print(f"✗ Ошибка создания таблицы: {e}")
            sys.exit(1)

if __name__ == '__main__':
    main()

