#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: флаг отправки в MAX файла полного разбора чек-листа (*.txt).
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
    ddl = """
    ALTER TABLE user_config
    ADD COLUMN IF NOT EXISTS max_send_checklist_analysis_file BOOLEAN NOT NULL DEFAULT TRUE;
    """
    db_url = get_db_url()
    engine = create_engine(db_url)
    logger.info("Подключение к БД")
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text(ddl))
        logger.info("Миграция max_send_checklist_analysis_file выполнена.")
    except Exception as exc:
        logger.error("Ошибка миграции: %s", exc, exc_info=True)
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()
