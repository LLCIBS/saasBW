#!/usr/bin/env python3
"""
Создаёт схему таблиц классификации в PostgreSQL (db.create_all) и
напоминает о переносе из SQLite (если старые файлы ещё есть).

Старые per-user SQLite-файлы (classification_rules.db, training_examples.db) больше
не заполняются рантаймом — данные в PostgreSQL.

Перенос данных:
    .\\venv\\Scripts\\python scripts\\migrate_sqlite_classification_to_postgres.py

Или вручную: создать таблицы через init_db / db.create_all, затем скрипт переноса.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web_interface.app import app
from database.models import db


def main() -> None:
    with app.app_context():
        db.create_all()
    print("OK: database.models (включая таблицы классификации) применены через create_all().")
    print("Если у пользователей остались старые SQLite, запустите:")
    print("  python scripts/migrate_sqlite_classification_to_postgres.py")


if __name__ == "__main__":
    main()
