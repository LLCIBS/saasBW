#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: удаляет устаревшие колонки user_config.source_type и user_config.ftp_connection_id.

Ранее «источник файлов» выбирался на вкладке «Пути»; FTP/SFTP управляется только таблицей
ftp_connections (см. переход на модель интеграций).
"""

import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
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
    db_url = get_db_url()
    engine = create_engine(db_url)
    logger.info("Подключение к БД")
    try:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("user_config")}
        if "source_type" not in cols and "ftp_connection_id" not in cols:
            logger.info("Колонки source_type / ftp_connection_id отсутствуют, миграция не требуется.")
            return

        with engine.connect() as conn:
            with conn.begin():
                fks = insp.get_foreign_keys("user_config")
                for fk in fks:
                    if "ftp_connection_id" in (fk.get("constrained_columns") or []):
                        name = fk.get("name")
                        if name:
                            conn.execute(
                                text(f'ALTER TABLE user_config DROP CONSTRAINT IF EXISTS "{name}"')
                            )
                            logger.info("Снят внешний ключ: %s", name)
                if "ftp_connection_id" in cols:
                    conn.execute(text("ALTER TABLE user_config DROP COLUMN IF EXISTS ftp_connection_id"))
                    logger.info("Удалена колонка ftp_connection_id")
                if "source_type" in cols:
                    conn.execute(text("ALTER TABLE user_config DROP COLUMN IF EXISTS source_type"))
                    logger.info("Удалена колонка source_type")
        logger.info("Миграция migrate_drop_user_config_source_ftp выполнена.")
    except Exception as exc:
        logger.error("Ошибка миграции: %s", exc, exc_info=True)
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()
