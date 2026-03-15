#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для создания таблицы stocrm_connections и добавления поля
stocrm_connection_id в user_config.

Запуск:
    python scripts/add_stocrm_table.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from database.models import db, StocrmConnection
from web_interface.app import app


def main():
    with app.app_context():
        try:
            db.create_all()
            print("✓ Таблица stocrm_connections создана или уже существует")

            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)

            if 'stocrm_connections' in inspector.get_table_names():
                print("✓ Таблица stocrm_connections доступна")
            else:
                print("✗ Таблица stocrm_connections не найдена после create_all!")
                sys.exit(1)

            if 'user_config' in inspector.get_table_names():
                cols = [c['name'] for c in inspector.get_columns('user_config')]
                if 'stocrm_connection_id' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text("""
                            ALTER TABLE user_config
                            ADD COLUMN stocrm_connection_id INTEGER
                            REFERENCES stocrm_connections(id)
                        """))
                        conn.commit()
                    print("✓ Поле stocrm_connection_id добавлено в user_config")
                else:
                    print("✓ Поле stocrm_connection_id уже существует в user_config")

            print("\nМиграция StoCRM завершена успешно.")

        except Exception as e:
            print(f"✗ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == '__main__':
    main()
