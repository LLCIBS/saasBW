#!/usr/bin/env python3
"""
Удаляет устаревшие per-user файлы classification_rules.db и training_examples.db
в каталогах .../classification/ (логика путей как в веб-приложении), после переноса в PostgreSQL.

По умолчанию только список (dry-run). Реальное удаление:
    python scripts/remove_legacy_classification_sqlite_files.py --execute
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web_interface.app import app  # noqa: E402
from database import models as M  # noqa: E402

LEGACY_NAMES = ("classification_rules.db", "training_examples.db")


def _classification_dir_for_user(user: M.User) -> Path:
    cfg = M.UserConfig.query.filter_by(user_id=user.id).first()
    if cfg and cfg.base_records_path:
        return Path(cfg.base_records_path) / "classification"
    base_root = Path(str(app.config.get("BASE_RECORDS_PATH", Path.cwd())))
    return base_root / "users" / str(user.id) / "classification"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--execute",
        action="store_true",
        help="Удалить файлы; без флага — только список (dry-run)",
    )
    args = p.parse_args()
    found: list[Path] = []
    with app.app_context():
        users = M.User.query.all()
        for u in users:
            for name in LEGACY_NAMES:
                f = _classification_dir_for_user(u) / name
                if f.is_file():
                    found.append(f)
                    print(f"  {f}")
                    if args.execute:
                        f.unlink()
    if not found:
        print("Старые .db (classification_rules.db / training_examples.db) не найдены.")
    elif args.execute:
        print(f"Удалено файлов: {len(found)}")
    else:
        print("Dry-run. Для удаления:")
        print("  python scripts/remove_legacy_classification_sqlite_files.py --execute")


if __name__ == "__main__":
    main()
