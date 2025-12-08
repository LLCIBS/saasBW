#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для создания таблиц для нормализации данных из user_settings.data
"""

import sys
import os
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Устанавливаем рабочую директорию
try:
    os.chdir(str(project_root))
except Exception:
    pass

# Загружаем переменные окружения с правильной кодировкой
# Устанавливаем UTF-8 для вывода
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from flask import Flask
from config.settings import get_config
from database.models import db
from dotenv import load_dotenv
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загружаем .env файл ПЕРЕД импортом config
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path, encoding='utf-8')
else:
    load_dotenv(encoding='utf-8')

app = Flask(__name__)
config = get_config()
app.config.from_object(config)

# ВАЖНО: Переопределяем DATABASE_URL после загрузки .env
from urllib.parse import quote_plus

db_user = os.getenv('DB_USER', os.getenv('DATABASE_USER', 'postgres'))
db_pass = os.getenv('DB_PASSWORD', os.getenv('DATABASE_PASSWORD', 'postgres'))
db_host = os.getenv('DB_HOST', 'localhost')
db_port = os.getenv('DB_PORT', '5432')
db_name = os.getenv('DB_NAME', os.getenv('DATABASE_NAME', 'saas'))

db_url = os.getenv('DATABASE_URL')
if db_url:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Invalid URL")
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        logger.info("✓ Используется DATABASE_URL из .env")
    except Exception:
        db_url = f"postgresql://{quote_plus(db_user)}:{quote_plus(db_pass)}@{db_host}:{db_port}/{db_name}"
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        logger.info(f"✓ DATABASE_URL сформирован из параметров")
else:
    db_url = f"postgresql://{quote_plus(db_user)}:{quote_plus(db_pass)}@{db_host}:{db_port}/{db_name}"
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    logger.info(f"✓ DATABASE_URL сформирован")

# Инициализируем расширения
db.init_app(app)

def create_tables():
    """Создает все таблицы для нормализации данных"""
    with app.app_context():
        logger.info("="*60)
        logger.info("Создание таблиц для нормализации данных из user_settings.data")
        logger.info("="*60)
        
        try:
            # Создаем все таблицы
            db.create_all()
            logger.info("✓ Все таблицы успешно созданы!")
            logger.info("\nСозданные таблицы:")
            logger.info("  - user_config")
            logger.info("  - user_stations")
            logger.info("  - user_station_mappings")
            logger.info("  - user_station_chat_ids")
            logger.info("  - user_employee_extensions")
            logger.info("  - user_prompts")
            logger.info("  - user_vocabulary")
            logger.info("  - user_script_prompts")
            logger.info("="*60)
        except Exception as e:
            logger.error(f"✗ Ошибка при создании таблиц: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

if __name__ == "__main__":
    create_tables()
