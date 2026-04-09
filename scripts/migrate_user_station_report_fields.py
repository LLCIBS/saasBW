#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: user_stations.report_name, user_stations.sort_order (название и порядок для отчётов).

Подключение к БД — как у веб-приложения: импорт app подгружает .env (DATABASE_URL / DB_*),
в отличие от «голого» get_config(), который без .env даёт postgres/postgres по умолчанию.
"""

import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("FLASK_APP", "web_interface.app")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def run_migration():
    from sqlalchemy import text

    from web_interface.app import app
    from database.models import db

    ddls = [
        "ALTER TABLE user_stations ADD COLUMN IF NOT EXISTS report_name VARCHAR(200);",
        "ALTER TABLE user_stations ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;",
    ]
    logger.info("Подключение к БД (как у Flask-приложения, с учётом .env)")
    with app.app_context():
        for ddl in ddls:
            try:
                db.session.execute(text(ddl))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                err = str(e).lower()
                if "duplicate column" in err or "already exists" in err:
                    logger.info("Колонка уже есть: %s", e)
                else:
                    raise
    logger.info("Миграция user_stations (report_name, sort_order) выполнена.")


if __name__ == "__main__":
    run_migration()
