#!/usr/bin/env python3
"""
Создаёт в PostgreSQL таблицы подсистемы классификации (через db.create_all).

Данные хранятся только в PostgreSQL. Удаление старых per-user *.db с диска (после бэкапа):
    python scripts/remove_legacy_classification_sqlite_files.py
    python scripts/remove_legacy_classification_sqlite_files.py --execute
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
    print("OK: таблицы из database.models (в т.ч. классификация) применены через create_all().")


if __name__ == "__main__":
    main()
