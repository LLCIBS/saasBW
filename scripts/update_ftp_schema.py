#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper script that adds start_from / last_processed_* columns to ftp_connections.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # type: ignore

load_dotenv(PROJECT_ROOT / '.env')

from sqlalchemy import inspect, text  # type: ignore

from web_interface.app import app  # type: ignore
from database.models import db  # type: ignore


def column_exists(inspector, table_name: str, column_name: str) -> bool:
    """Return True if a column is already present in the table."""
    return any(col['name'] == column_name for col in inspector.get_columns(table_name))


def main():
    with app.app_context():
        inspector = inspect(db.engine)

        if 'ftp_connections' not in inspector.get_table_names():
            print('[-] Table ftp_connections not found. Run scripts/add_ftp_table.py first.')
            sys.exit(1)

        statements = []
        if not column_exists(inspector, 'ftp_connections', 'start_from'):
            statements.append("ALTER TABLE ftp_connections ADD COLUMN start_from TIMESTAMP NULL")
        if not column_exists(inspector, 'ftp_connections', 'last_processed_mtime'):
            statements.append("ALTER TABLE ftp_connections ADD COLUMN last_processed_mtime TIMESTAMP NULL")
        if not column_exists(inspector, 'ftp_connections', 'last_processed_filename'):
            statements.append("ALTER TABLE ftp_connections ADD COLUMN last_processed_filename VARCHAR(500)")

        if not statements:
            print('[=] Columns already exist. Nothing to do.')
            return

        with db.engine.begin() as connection:  # type: ignore
            for stmt in statements:
                connection.execute(text(stmt))
                print(f'[+] Executed: {stmt}')

        print('[+] ftp_connections schema updated')


if __name__ == '__main__':
    main()
