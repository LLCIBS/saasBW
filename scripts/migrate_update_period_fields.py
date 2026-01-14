#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: обновление полей периода в таблице report_schedules
Заменяет auto_start_date, auto_end_date, date_offset_days, manual_start_date, manual_end_date
на period_type и period_n_days
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
    """Выполняет миграцию обновления полей периода"""
    db_url = get_db_url()
    engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600)

    logger.info("Подключение к БД: %s", db_url.split('@')[-1] if '@' in db_url else db_url)
    
    try:
        with engine.connect() as conn:
            with conn.begin():
                # Добавляем новые поля
                logger.info("Добавление новых полей period_type и period_n_days...")
                conn.execute(text("""
                    ALTER TABLE report_schedules
                        ADD COLUMN IF NOT EXISTS period_type VARCHAR(20) DEFAULT 'last_week',
                        ADD COLUMN IF NOT EXISTS period_n_days INTEGER;
                """))
                
                # Обновляем существующие записи: если есть manual_start_date или manual_end_date,
                # устанавливаем period_type = 'last_week' (по умолчанию)
                logger.info("Обновление существующих записей...")
                conn.execute(text("""
                    UPDATE report_schedules
                    SET period_type = 'last_week'
                    WHERE period_type IS NULL;
                """))
                
                # Удаляем старые поля (опционально, можно оставить для обратной совместимости)
                # Раскомментируйте, если хотите удалить старые поля:
                # logger.info("Удаление старых полей...")
                # conn.execute(text("""
                #     ALTER TABLE report_schedules
                #         DROP COLUMN IF EXISTS auto_start_date,
                #         DROP COLUMN IF EXISTS auto_end_date,
                #         DROP COLUMN IF EXISTS date_offset_days,
                #         DROP COLUMN IF EXISTS manual_start_date,
                #         DROP COLUMN IF EXISTS manual_end_date;
                # """))
                        
        logger.info("✅ Миграция успешно выполнена.")
        return True
        
    except Exception as exc:
        logger.error("❌ Ошибка при выполнении миграции: %s", exc, exc_info=True)
        raise
    finally:
        engine.dispose()

if __name__ == "__main__":
    print("=" * 60)
    print("Миграция: обновление полей периода в report_schedules")
    print("=" * 60)
    
    try:
        run_migration()
        print("\n✅ Миграция завершена успешно!")
    except Exception as e:
        print(f"\n❌ Ошибка выполнения миграции: {e}")
        sys.exit(1)
