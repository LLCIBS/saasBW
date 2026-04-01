#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: способ транскрибации (Gemini) — поля user_config.transcription_engine,
gemini_model, gemini_api_key.
"""

import sys
import logging
from pathlib import Path

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

if sys.platform == "win32":
    import io

    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except AttributeError:
        pass

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path, encoding="utf-8")
else:
    load_dotenv(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_db_url():
    from config.settings import get_config

    return get_config().SQLALCHEMY_DATABASE_URI


def run_migration():
    statements = [
        """
        ALTER TABLE user_config
        ADD COLUMN IF NOT EXISTS transcription_engine VARCHAR(20) NOT NULL DEFAULT 'internal';
        """,
        """
        ALTER TABLE user_config
        ADD COLUMN IF NOT EXISTS gemini_model VARCHAR(120);
        """,
        """
        ALTER TABLE user_config
        ADD COLUMN IF NOT EXISTS gemini_api_key VARCHAR(255);
        """,
    ]
    db_url = get_db_url()
    engine = create_engine(db_url)
    logger.info("Подключение к БД")
    try:
        with engine.connect() as conn:
            with conn.begin():
                for ddl in statements:
                    conn.execute(text(ddl))
        logger.info("Миграция gemini/transcription_engine выполнена.")
    except Exception as exc:
        logger.error("Ошибка миграции: %s", exc, exc_info=True)
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()
