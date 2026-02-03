# -*- coding: utf-8 -*-
"""
Миграция: добавление колонки business_profile в user_config.
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('FLASK_APP', 'web_interface.app')

def run():
    from web_interface.app import app
    from database.models import db
    from sqlalchemy import text

    with app.app_context():
        try:
            db.session.execute(text("""
                ALTER TABLE user_config
                ADD COLUMN IF NOT EXISTS business_profile VARCHAR(50) NOT NULL DEFAULT 'autoservice'
            """))
            db.session.commit()
            print("Колонка business_profile добавлена в user_config.")
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка: {e}")
            raise

if __name__ == '__main__':
    run()
