#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для добавления полей start_from и last_sync в rostelecom_ats_connections
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from database.models import db
from web_interface.app import app

def main():
    with app.app_context():
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            if 'rostelecom_ats_connections' not in inspector.get_table_names():
                print("Таблица rostelecom_ats_connections не найдена")
                sys.exit(1)
            cols = [c['name'] for c in inspector.get_columns('rostelecom_ats_connections')]
            with db.engine.connect() as conn:
                if 'start_from' not in cols:
                    conn.execute(text("""
                        ALTER TABLE rostelecom_ats_connections
                        ADD COLUMN start_from TIMESTAMP NULL
                    """))
                    conn.commit()
                    print("✓ Поле start_from добавлено")
                else:
                    print("✓ Поле start_from уже существует")
                if 'last_sync' not in cols:
                    conn.execute(text("""
                        ALTER TABLE rostelecom_ats_connections
                        ADD COLUMN last_sync TIMESTAMP NULL
                    """))
                    conn.commit()
                    print("✓ Поле last_sync добавлено")
                else:
                    print("✓ Поле last_sync уже существует")
        except Exception as e:
            print(f"✗ Ошибка: {e}")
            sys.exit(1)

if __name__ == '__main__':
    main()
