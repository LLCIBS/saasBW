#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: добавляет колонку reports_chat_id в user_config.

Чат для отправки сгенерированных отчётов (отдельно от Alert Chat ID).
"""

import sys
import logging
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_db_url():
    try:
        from config.settings import get_config
        return get_config().SQLALCHEMY_DATABASE_URI
    except Exception as exc:
        logger.error("Не удалось получить SQLALCHEMY_DATABASE_URI: %s", exc)
        raise


def run_migration():
    ddl = """
    ALTER TABLE user_config
      ADD COLUMN IF NOT EXISTS reports_chat_id VARCHAR(100);
    """
    db_url = get_db_url()
    engine = create_engine(db_url)
    logger.info("Подключение к БД: %s", db_url)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text(ddl))
        logger.info("Миграция reports_chat_id выполнена.")
    except Exception as exc:
        logger.error("Ошибка при выполнении миграции: %s", exc, exc_info=True)
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()
