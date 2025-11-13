#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Добавляет поля user_id и необходимые ограничения/индексы
для мультиарендной схемы (calls, transfer_cases, recall_cases, system_logs).
Запускать после обновления моделей перед переносом данных из JSON.
"""

import os
import sys
from pathlib import Path

from flask import Flask
from sqlalchemy import text
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import get_config  # noqa: E402
from database.models import db  # noqa: E402

load_dotenv()

app = Flask(__name__)
app.config.from_object(get_config())
db.init_app(app)

DEFAULT_USER_ID = int(os.getenv('DEFAULT_TENANT_USER_ID', '1'))


def ensure_fk(conn, table: str):
    constraint = f"{table}_user_id_fkey"
    conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE constraint_name = :constraint
                ) THEN
                    EXECUTE format(
                        'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE',
                        :table_name,
                        :constraint
                    );
                END IF;
            END$$;
            """
        ),
        {"constraint": constraint, "table_name": table},
    )


def ensure_indexes(conn, statements):
    for stmt in statements:
        conn.execute(text(stmt))


def migrate_table(conn, table: str, index_statements):
    print(f"\n--> Обработка таблицы {table}")
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id INTEGER"))
    conn.execute(
        text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
        {"uid": DEFAULT_USER_ID},
    )
    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL"))
    ensure_fk(conn, table)
    ensure_indexes(conn, index_statements)


def main():
    with app.app_context():
        engine = db.engine
        with engine.begin() as conn:
            migrate_table(
                conn,
                "calls",
                [
                    "CREATE INDEX IF NOT EXISTS idx_calls_station_time ON calls (user_id, station_code, call_time)",
                    "CREATE INDEX IF NOT EXISTS idx_calls_phone_time ON calls (user_id, phone_number, call_time)",
                ],
            )
            migrate_table(
                conn,
                "transfer_cases",
                [
                    "CREATE INDEX IF NOT EXISTS idx_transfers_status_deadline ON transfer_cases (user_id, status, deadline)",
                    "CREATE INDEX IF NOT EXISTS idx_transfers_remind ON transfer_cases (user_id, remind_at, notified)",
                ],
            )
            migrate_table(
                conn,
                "recall_cases",
                [
                    "CREATE INDEX IF NOT EXISTS idx_recalls_status_deadline ON recall_cases (user_id, status, deadline)",
                    "CREATE INDEX IF NOT EXISTS idx_recalls_remind ON recall_cases (user_id, remind_at, notified)",
                ],
            )
            migrate_table(
                conn,
                "system_logs",
                [
                    "CREATE INDEX IF NOT EXISTS idx_logs_level_time ON system_logs (user_id, level, created_at)",
                ],
            )
    print("\nГотово: схема обновлена для мультиарендности.")


if __name__ == "__main__":
    main()
