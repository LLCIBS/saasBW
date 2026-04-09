#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: user_stations.report_name, user_stations.sort_order (название и порядок для отчётов).
"""

import sys
import logging
from pathlib import Path

from sqlalchemy import create_engine, text

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_db_url():
    from config.settings import get_config
    return get_config().SQLALCHEMY_DATABASE_URI


def run_migration():
    db_url = get_db_url()
    engine = create_engine(db_url)
    logger.info("Подключение к БД")
    ddls = [
        "ALTER TABLE user_stations ADD COLUMN IF NOT EXISTS report_name VARCHAR(200);",
        "ALTER TABLE user_stations ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;",
    ]
    try:
        with engine.connect() as conn:
            with conn.begin():
                for ddl in ddls:
                    try:
                        conn.execute(text(ddl))
                    except Exception as e:
                        # SQLite старых версий без IF NOT EXISTS
                        if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                            logger.info("Колонка уже есть: %s", e)
                        else:
                            raise
        logger.info("Миграция user_stations (report_name, sort_order) выполнена.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()
