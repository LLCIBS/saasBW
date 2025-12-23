#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: добавляет колонки для пользовательских форматов имен файлов в user_config.

Добавляются поля:
- use_custom_filename_patterns (BOOLEAN NOT NULL DEFAULT FALSE)
- filename_patterns (JSONB)
- filename_extensions (JSONB)
"""

import sys
import logging
from pathlib import Path

from sqlalchemy import create_engine, text

# Подготовка путей
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_db_url():
    """Получаем URL базы из config.settings."""
    try:
        from config.settings import get_config
        cfg = get_config()
        return cfg.SQLALCHEMY_DATABASE_URI
    except Exception as exc:  # pragma: no cover - защитный код
        logger.error("Не удалось получить SQLALCHEMY_DATABASE_URI: %s", exc)
        raise


def run_migration():
    ddl = """
    ALTER TABLE user_config
      ADD COLUMN IF NOT EXISTS use_custom_filename_patterns BOOLEAN NOT NULL DEFAULT FALSE,
      ADD COLUMN IF NOT EXISTS filename_patterns JSONB,
      ADD COLUMN IF NOT EXISTS filename_extensions JSONB;
    """

    db_url = get_db_url()
    engine = create_engine(db_url)

    logger.info("Подключение к БД: %s", db_url)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text(ddl))
        logger.info("Миграция успешно выполнена.")
    except Exception as exc:
        logger.error("Ошибка при выполнении миграции: %s", exc, exc_info=True)
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()

