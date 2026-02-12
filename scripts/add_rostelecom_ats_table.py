#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для добавления таблицы rostelecom_ats_connections и поля rostelecom_ats_connection_id в user_config
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from database.models import db, RostelecomAtsConnection
from web_interface.app import app

def main():
    with app.app_context():
        try:
            db.create_all()
            print("✓ Таблица rostelecom_ats_connections создана или уже существует")
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            if 'rostelecom_ats_connections' in inspector.get_table_names():
                print("✓ Таблица rostelecom_ats_connections успешно создана")
                rcols = [c['name'] for c in inspector.get_columns('rostelecom_ats_connections')]
                if 'allowed_directions' not in rcols:
                    with db.engine.connect() as conn:
                        conn.execute(text("""
                            ALTER TABLE rostelecom_ats_connections
                            ADD COLUMN allowed_directions JSONB
                        """))
                        conn.commit()
                    print("✓ Поле allowed_directions добавлено в rostelecom_ats_connections")
            if 'user_config' in inspector.get_table_names():
                cols = [c['name'] for c in inspector.get_columns('user_config')]
                if 'rostelecom_ats_connection_id' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text("""
                            ALTER TABLE user_config
                            ADD COLUMN rostelecom_ats_connection_id INTEGER
                            REFERENCES rostelecom_ats_connections(id)
                        """))
                        conn.commit()
                    print("✓ Поле rostelecom_ats_connection_id добавлено в user_config")
                else:
                    print("✓ Поле rostelecom_ats_connection_id уже существует")
        except Exception as e:
            print(f"✗ Ошибка: {e}")
            sys.exit(1)

if __name__ == '__main__':
    main()
