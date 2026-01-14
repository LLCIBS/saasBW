#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: создание таблицы report_schedules для автоматической генерации отчетов по расписанию.

Создается таблица:
- report_schedules - хранит настройки расписаний для каждого пользователя и типа отчета
"""

import sys
import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Подготовка путей
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Настройка UTF-8 для Windows
if sys.platform == 'win32':
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except AttributeError:
        pass  # В некоторых средах вывода buffer может не быть

# Загружаем переменные окружения из .env
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path, encoding='utf-8')
else:
    load_dotenv(encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_db_url():
    """Получаем URL базы из config.settings."""
    try:
        from config.settings import get_config
        cfg = get_config()
        return cfg.SQLALCHEMY_DATABASE_URI
    except Exception as exc:
        logger.error("Ошибка получения конфигурации БД: %s", exc)
        raise


def read_sql_file():
    """Читает SQL из файла миграции."""
    sql_file = project_root / 'scripts' / 'create_report_schedules_table.sql'
    if not sql_file.exists():
        raise FileNotFoundError(f"Файл миграции не найден: {sql_file}")
    
    with sql_file.open('r', encoding='utf-8') as f:
        return f.read()


def run_migration():
    """Выполняет миграцию создания таблицы report_schedules."""
    db_url = get_db_url()
    # Добавляем pool_pre_ping для проверки соединения перед использованием
    # и pool_recycle для переподключения при долгих простоях
    engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600)

    logger.info("Подключение к БД: %s", db_url.split('@')[-1] if '@' in db_url else db_url)
    
    # SQL команды напрямую (более надежно, чем парсинг файла)
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS report_schedules (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        report_type VARCHAR(50) NOT NULL,
        schedule_type VARCHAR(20) NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,

        daily_time VARCHAR(5),
        interval_value INTEGER,
        interval_unit VARCHAR(10),
        weekly_day INTEGER,
        weekly_time VARCHAR(5),
        cron_expression VARCHAR(100),

        period_type VARCHAR(20) NOT NULL DEFAULT 'last_week',
        period_n_days INTEGER,

        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_run_at TIMESTAMP,
        next_run_at TIMESTAMP,

        CONSTRAINT uq_report_schedule_user_report UNIQUE (user_id, report_type)
    );
    """
    
    create_index_sql = """
    CREATE INDEX IF NOT EXISTS idx_report_schedule_user ON report_schedules(user_id);
    """
    
    try:
        with engine.connect() as conn:
            with conn.begin():
                # Сначала создаем таблицу
                logger.info("Выполнение команды 1/2: CREATE TABLE...")
                conn.execute(text(create_table_sql))
                logger.info("Таблица report_schedules создана успешно")
                
                # Затем создаем индекс
                logger.info("Выполнение команды 2/2: CREATE INDEX...")
                conn.execute(text(create_index_sql))
                logger.info("Индекс idx_report_schedule_user создан успешно")
                        
        logger.info("✅ Миграция успешно выполнена. Таблица report_schedules создана.")
        return True
        
    except Exception as exc:
        logger.error("❌ Ошибка при выполнении миграции: %s", exc, exc_info=True)
        raise
    finally:
        engine.dispose()


def check_table_exists():
    """Проверяет, существует ли уже таблица."""
    db_url = get_db_url()
    engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'report_schedules'
                );
            """))
            exists = result.scalar()
            return exists
    except Exception as exc:
        logger.warning("Не удалось проверить существование таблицы: %s", exc)
        return None  # None означает, что не удалось проверить
    finally:
        engine.dispose()


if __name__ == "__main__":
    print("=" * 60)
    print("Миграция: создание таблицы report_schedules")
    print("=" * 60)
    
    # Проверяем, существует ли уже таблица
    table_exists = check_table_exists()
    
    if table_exists is True:
        logger.warning("⚠️  Таблица report_schedules уже существует.")
        response = input("Продолжить выполнение миграции? (y/n): ")
        if response.lower() != 'y':
            print("Миграция отменена.")
            sys.exit(0)
    elif table_exists is None:
        logger.warning("⚠️  Не удалось проверить существование таблицы (возможны проблемы с БД).")
        response = input("Продолжить выполнение миграции? (y/n): ")
        if response.lower() != 'y':
            print("Миграция отменена.")
            sys.exit(0)
    
    try:
        run_migration()
        print("\n✅ Миграция завершена успешно!")
        print("Теперь можно использовать функционал автоматической генерации отчетов.")
        
        # Проверяем результат
        if check_table_exists():
            print("✅ Таблица report_schedules успешно создана и доступна.")
        else:
            print("⚠️  Предупреждение: не удалось подтвердить создание таблицы.")
            
    except Exception as e:
        print(f"\n❌ Ошибка выполнения миграции: {e}")
        print("\nВозможные причины:")
        print("1. PostgreSQL сервер не запущен или недоступен")
        print("2. Неверные учетные данные в .env файле")
        print("3. Проблемы с сетью или файрволом")
        print("4. База данных не существует")
        print("\nПроверьте:")
        print("- Запущен ли PostgreSQL сервер")
        print("- Правильность настроек в .env (DATABASE_URL или SQLALCHEMY_DATABASE_URI)")
        print("- Доступность базы данных")
        sys.exit(1)
