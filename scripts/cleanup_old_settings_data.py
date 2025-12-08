#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для очистки старых данных из user_settings.data после миграции
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
from database.models import (
    db, User, UserSettings,
    UserConfig, UserStation, UserPrompt, UserVocabulary, UserScriptPrompt
)
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

def check_migration_status():
    """Проверяет, что миграция выполнена успешно"""
    with app.app_context():
        users = User.query.all()
        migrated_count = 0
        not_migrated_count = 0
        
        for user in users:
            # Проверяем наличие данных в новых таблицах
            has_config = UserConfig.query.filter_by(user_id=user.id).first() is not None
            has_stations = UserStation.query.filter_by(user_id=user.id).first() is not None
            
            if has_config or has_stations:
                migrated_count += 1
            else:
                not_migrated_count += 1
        
        return migrated_count, not_migrated_count

def cleanup_old_data():
    """Очищает старые данные из user_settings.data"""
    with app.app_context():
        logger.info("="*60)
        logger.info("Проверка статуса миграции...")
        logger.info("="*60)
        
        # Проверяем миграцию
        migrated, not_migrated = check_migration_status()
        logger.info(f"Пользователей с мигрированными данными: {migrated}")
        logger.info(f"Пользователей без мигрированных данных: {not_migrated}")
        
        if not_migrated > 0:
            logger.warning("⚠️  Обнаружены пользователи без мигрированных данных!")
            logger.warning("⚠️  Рекомендуется сначала выполнить миграцию: python scripts/migrate_all_settings_data.py")
            response = input("\nПродолжить очистку? (yes/no): ")
            if response.lower() != 'yes':
                logger.info("Очистка отменена")
                return
        
        logger.info("\n" + "="*60)
        logger.info("Начало очистки старых данных из user_settings.data")
        logger.info("="*60)
        
        # Получаем все записи UserSettings
        settings_list = UserSettings.query.all()
        logger.info(f"Найдено записей в user_settings: {len(settings_list)}")
        
        cleaned_count = 0
        empty_count = 0
        error_count = 0
        
        for settings in settings_list:
            try:
                if not settings.data:
                    empty_count += 1
                    continue
                
                # Проверяем, что данные действительно мигрированы
                user = User.query.get(settings.user_id)
                if not user:
                    continue
                
                # Очищаем только секции, которые были мигрированы
                data = settings.data.copy() if settings.data else {}
                original_keys = set(data.keys())
                
                # Удаляем мигрированные секции
                keys_to_remove = []
                
                # Проверяем наличие в новых таблицах
                if UserConfig.query.filter_by(user_id=user.id).first():
                    if 'config' in data:
                        keys_to_remove.append('config')
                
                if UserPrompt.query.filter_by(user_id=user.id).first():
                    if 'prompts' in data:
                        keys_to_remove.append('prompts')
                
                if UserVocabulary.query.filter_by(user_id=user.id).first():
                    if 'vocabulary' in data:
                        keys_to_remove.append('vocabulary')
                
                if UserScriptPrompt.query.filter_by(user_id=user.id).first():
                    if 'script_prompt' in data:
                        keys_to_remove.append('script_prompt')
                
                # Удаляем ключи
                for key in keys_to_remove:
                    del data[key]
                
                # Обновляем данные
                if len(data) < len(original_keys):
                    settings.data = data if data else {}
                    cleaned_count += 1
                    logger.info(f"✓ Очищены данные для пользователя {user.username} (ID: {user.id}). Удалены ключи: {', '.join(keys_to_remove)}")
                else:
                    empty_count += 1
                
            except Exception as e:
                logger.error(f"✗ Ошибка при очистке данных для settings ID {settings.id}: {e}")
                error_count += 1
        
        # Сохраняем изменения
        if cleaned_count > 0:
            db.session.commit()
            logger.info(f"\n✓ Очищено записей: {cleaned_count}")
        
        logger.info(f"  - Уже пустых: {empty_count}")
        logger.info(f"  - Ошибок: {error_count}")
        logger.info("="*60)
        
        # Предложение полностью очистить колонку data
        if cleaned_count > 0:
            logger.info("\n💡 Совет: Если все данные успешно мигрированы и код обновлен,")
            logger.info("   можно полностью очистить колонку data командой:")
            logger.info("   UPDATE user_settings SET data = '{}'::jsonb;")

def cleanup_data_column_completely():
    """Полностью очищает колонку data в user_settings"""
    with app.app_context():
        logger.info("="*60)
        logger.info("Полная очистка колонки data в user_settings")
        logger.info("="*60)
        logger.warning("⚠️  ВНИМАНИЕ: Это действие удалит ВСЕ данные из колонки data!")
        logger.warning("⚠️  Убедитесь, что:")
        logger.warning("    1. Все данные мигрированы в новые таблицы")
        logger.warning("    2. Код приложения обновлен для работы с новыми таблицами")
        
        response = input("\nПродолжить полную очистку? (yes/no): ")
        if response.lower() != 'yes':
            logger.info("Очистка отменена")
            return
        
        try:
            from sqlalchemy import text
            result = db.session.execute(
                text("UPDATE user_settings SET data = '{}'::jsonb WHERE data IS NOT NULL")
            )
            db.session.commit()
            logger.info(f"✓ Очищено записей: {result.rowcount}")
            logger.info("="*60)
        except Exception as e:
            logger.error(f"✗ Ошибка при полной очистке: {e}")
            db.session.rollback()
            raise

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Очистка старых данных из user_settings.data')
    parser.add_argument('--full', action='store_true', 
                       help='Полная очистка колонки data (удаляет все данные)')
    
    args = parser.parse_args()
    
    if args.full:
        cleanup_data_column_completely()
    else:
        cleanup_old_data()
