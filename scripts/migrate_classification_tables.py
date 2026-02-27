#!/usr/bin/env python3
"""
Миграция таблиц модуля классификации для всех пользователей.

Создает/обновляет:
- classification_rules.db (в т.ч. auto_extracted_rules)
- training_examples.db

Запуск:
    .\\venv\\Scripts\\python scripts\\migrate_classification_tables.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web_interface.app import app
from database.models import User, UserConfig
from classification_module.classification_rules import ClassificationRulesManager
from classification_module.training_examples import TrainingExamplesManager
from classification_module.self_learning_system import SelfLearningSystem


def _user_base_records_path(user_id: int) -> Path:
    cfg = UserConfig.query.filter_by(user_id=user_id).first()
    if cfg and cfg.base_records_path:
        return Path(cfg.base_records_path)
    base_root = Path(str(app.config.get("BASE_RECORDS_PATH", Path.cwd())))
    return base_root / "users" / str(user_id)


def _has_table(db_path: Path, table_name: str) -> bool:
    if not db_path.exists():
        return False
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def migrate_user(user: User) -> dict:
    base = _user_base_records_path(int(user.id))
    root = base / "classification"
    uploads = root / "uploads"
    rules_db = root / "classification_rules.db"
    training_db = root / "training_examples.db"

    root.mkdir(parents=True, exist_ok=True)
    uploads.mkdir(parents=True, exist_ok=True)

    # Инициализация таблиц в rules/training
    ClassificationRulesManager(db_path=str(rules_db))
    TrainingExamplesManager(db_path=str(training_db))
    SelfLearningSystem(training_db_path=str(training_db), rules_db_path=str(rules_db))

    return {
        "user_id": int(user.id),
        "username": str(getattr(user, "username", "") or ""),
        "rules_db": str(rules_db),
        "training_db": str(training_db),
        "auto_extracted_rules": _has_table(rules_db, "auto_extracted_rules"),
    }


def main():
    with app.app_context():
        users = User.query.all()
        if not users:
            print("Пользователи не найдены.")
            return

        ok = 0
        failed = 0
        for user in users:
            try:
                result = migrate_user(user)
                if result["auto_extracted_rules"]:
                    ok += 1
                    print(
                        f"[OK] user={result['user_id']} ({result['username']}), "
                        f"auto_extracted_rules=YES"
                    )
                else:
                    failed += 1
                    print(
                        f"[FAIL] user={result['user_id']} ({result['username']}), "
                        f"auto_extracted_rules=NO"
                    )
            except Exception as exc:
                failed += 1
                print(
                    f"[ERROR] user={getattr(user, 'id', '?')} "
                    f"({getattr(user, 'username', '?')}): {exc}"
                )

        print(f"\nГотово. Успешно: {ok}, ошибок: {failed}")
        if failed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
