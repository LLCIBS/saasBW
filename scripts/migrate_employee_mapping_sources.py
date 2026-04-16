#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Применяет миграцию scripts/migration_employee_mapping_sources.sql к PostgreSQL.

Запуск из корня проекта (с активированным venv):
    python scripts/migrate_employee_mapping_sources.py

Не используйте: python scripts/migration_employee_mapping_sources.sql
(это SQL-файл, не Python).
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


def _sql_without_line_comments(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines)


def run_migration():
    sql_path = Path(__file__).resolve().parent / "migration_employee_mapping_sources.sql"
    if not sql_path.is_file():
        logger.error("Не найден файл: %s", sql_path)
        sys.exit(1)

    raw = sql_path.read_text(encoding="utf-8")
    cleaned = _sql_without_line_comments(raw)
    parts = [p.strip() for p in cleaned.split(";")]
    parts = [p for p in parts if p]

    db_url = get_db_url()
    engine = create_engine(db_url)
    logger.info("Подключение к БД, выполнение %s оператор(ов)", len(parts))
    try:
        with engine.connect() as conn:
            with conn.begin():
                for i, stmt in enumerate(parts, 1):
                    logger.debug("Выполнение #%s", i)
                    conn.execute(text(stmt))
        logger.info("Миграция employee_mapping_sources выполнена успешно.")
    except Exception as exc:
        logger.error("Ошибка миграции: %s", exc, exc_info=True)
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    run_migration()
