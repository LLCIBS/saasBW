#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: добавление полей для ручного выбора периода в таблицу report_schedules
"""

import sys
import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

if sys.platform == 'win32':
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except AttributeError:
        pass

env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path, encoding='utf-8')
else:
    load_dotenv(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def get_db_url():
    try:
        from config.settings import get_config
        cfg = get_config()
        return cfg.SQLALCHEMY_DATABASE_URI
    except Exception as exc:
        logger.error("Ошибка получения конфигурации БД: %s", exc)
        raise

def run_migration():
    ddl = """
    ALTER TABLE report_schedules
        ADD COLUMN IF NOT EXISTS manual_start_date DATE,
        ADD COLUMN IF NOT EXISTS manual_end_date DATE;
    """

    db_url = get_db_url()
    engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600)

    logger.info("Подключение к БД: %s", db_url.split('@')[-1] if '@' in db_url else db_url)
    
    try:
        with engine.connect() as conn:
            with conn.begin():
                logger.info("Добавление полей manual_start_date и manual_end_date...")
                conn.execute(text(ddl))
                        
        logger.info("✅ Миграция успешно выполнена.")
        return True
        
    except Exception as exc:
        logger.error("❌ Ошибка при выполнении миграции: %s", exc, exc_info=True)
        raise
    finally:
        engine.dispose()

if __name__ == "__main__":
    print("=" * 60)
    print("Миграция: добавление полей для ручного выбора периода")
    print("=" * 60)
    
    try:
        run_migration()
        print("\n✅ Миграция завершена успешно!")
    except Exception as e:
        print(f"\n❌ Ошибка выполнения миграции: {e}")
        sys.exit(1)
