#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка существования таблицы report_schedules
"""

import sys
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path, encoding='utf-8')
else:
    load_dotenv(encoding='utf-8')

from config.settings import get_config

def check_table():
    cfg = get_config()
    db_url = cfg.SQLALCHEMY_DATABASE_URI
    engine = create_engine(db_url, pool_pre_ping=True)
    
    try:
        with engine.connect() as conn:
            # Проверяем существование таблицы
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'report_schedules'
                );
            """))
            exists = result.scalar()
            
            if exists:
                print("✅ Таблица report_schedules существует")
                
                # Проверяем структуру
                columns = conn.execute(text("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = 'report_schedules'
                    ORDER BY ordinal_position;
                """))
                
                print("\nСтруктура таблицы:")
                for col in columns:
                    print(f"  - {col[0]}: {col[1]}")
                
                # Проверяем количество записей
                count = conn.execute(text("SELECT COUNT(*) FROM report_schedules"))
                print(f"\nКоличество расписаний: {count.scalar()}")
                
            else:
                print("❌ Таблица report_schedules НЕ существует")
                print("Запустите миграцию: python scripts\\create_report_schedules_table.py")
                
    except Exception as e:
        print(f"❌ Ошибка при проверке: {e}")
    finally:
        engine.dispose()

if __name__ == "__main__":
    check_table()
