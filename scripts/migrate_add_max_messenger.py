#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: MAX как дубль Telegram — колонки в user_config и таблица user_station_max_chat_ids.
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
    from config.settings import get_config
    return get_config().SQLALCHEMY_DATABASE_URI


def run_migration():
    ddls = [
        "ALTER TABLE user_config ADD COLUMN IF NOT EXISTS telegram_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE;",
        "ALTER TABLE user_config ADD COLUMN IF NOT EXISTS max_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE;",
        "ALTER TABLE user_config ADD COLUMN IF NOT EXISTS max_access_token VARCHAR(255);",
        "ALTER TABLE user_config ADD COLUMN IF NOT EXISTS max_alert_chat_id VARCHAR(100);",
        "ALTER TABLE user_config ADD COLUMN IF NOT EXISTS max_tg_channel_nizh VARCHAR(100);",
        "ALTER TABLE user_config ADD COLUMN IF NOT EXISTS max_tg_channel_other VARCHAR(100);",
        "ALTER TABLE user_config ADD COLUMN IF NOT EXISTS max_reports_chat_id VARCHAR(100);",
        """
        CREATE TABLE IF NOT EXISTS user_station_max_chat_ids (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            station_code VARCHAR(20) NOT NULL,
            chat_id VARCHAR(100) NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_user_station_max_chat UNIQUE (user_id, station_code, chat_id)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_maxchat_user_station ON user_station_max_chat_ids (user_id, station_code);",
    ]
    db_url = get_db_url()
    engine = create_engine(db_url)
    logger.info("Подключение к БД")
    try:
        with engine.connect() as conn:
            with conn.begin():
                for ddl in ddls:
                    conn.execute(text(ddl))
        logger.info("Миграция MAX / флаги Telegram выполнена.")
    except Exception as exc:
        logger.error("Ошибка миграции: %s", exc, exc_info=True)
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()
