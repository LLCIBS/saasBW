#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт миграции данных профиля пользователя из UserSettings.data в user_profile_data
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
from database.models import db, User, UserSettings, UserProfileData
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

def migrate_profile_data():
    """Мигрирует данные профиля из UserSettings.data в UserProfileData"""
    with app.app_context():
        logger.info("Начало миграции данных профиля пользователя...")
        
        # Получаем всех пользователей
        users = User.query.all()
        logger.info(f"Найдено пользователей: {len(users)}")
        
        migrated_count = 0
        skipped_count = 0
        error_count = 0
        
        for user in users:
            try:
                # Проверяем, есть ли уже запись в UserProfileData
                existing_profile = UserProfileData.query.filter_by(user_id=user.id).first()
                if existing_profile:
                    logger.info(f"Пользователь {user.username} (ID: {user.id}) уже имеет запись в user_profile_data, пропускаем")
                    skipped_count += 1
                    continue
                
                # Получаем данные из UserSettings
                settings = UserSettings.query.filter_by(user_id=user.id).first()
                if not settings:
                    logger.info(f"Пользователь {user.username} (ID: {user.id}) не имеет записи UserSettings, пропускаем")
                    skipped_count += 1
                    continue
                
                if not settings.data:
                    logger.info(f"Пользователь {user.username} (ID: {user.id}) имеет пустые данные в UserSettings, пропускаем")
                    skipped_count += 1
                    continue
                
                entity_data = settings.data.get('entity_data')
                if not entity_data:
                    logger.info(f"Пользователь {user.username} (ID: {user.id}) не имеет entity_data в UserSettings.data. Доступные ключи: {list(settings.data.keys()) if settings.data else 'нет данных'}")
                    skipped_count += 1
                    continue
                
                # Создаем новую запись в UserProfileData
                profile_data = UserProfileData(user_id=user.id)
                
                # Копируем общие данные
                profile_data.entity_type = entity_data.get('entity_type')
                
                # Копируем данные юридического лица
                legal_entity = entity_data.get('legal_entity', {})
                if legal_entity:
                    profile_data.legal_name = legal_entity.get('name') or None
                    profile_data.legal_inn = legal_entity.get('inn') or None
                    profile_data.legal_kpp = legal_entity.get('kpp') or None
                    profile_data.legal_ogrn = legal_entity.get('ogrn') or None
                    profile_data.legal_address = legal_entity.get('legal_address') or None
                    profile_data.actual_address = legal_entity.get('actual_address') or None
                
                # Копируем данные физического лица
                physical_entity = entity_data.get('physical_entity', {})
                if physical_entity:
                    profile_data.physical_full_name = physical_entity.get('full_name') or None
                    profile_data.physical_inn = physical_entity.get('inn') or None
                    profile_data.passport_series = physical_entity.get('passport_series') or None
                    profile_data.passport_number = physical_entity.get('passport_number') or None
                    profile_data.registration_address = physical_entity.get('registration_address') or None
                
                db.session.add(profile_data)
                db.session.commit()
                
                logger.info(f"✓ Мигрированы данные для пользователя {user.username} (ID: {user.id})")
                migrated_count += 1
                
            except Exception as e:
                logger.error(f"✗ Ошибка при миграции данных для пользователя {user.username} (ID: {user.id}): {e}")
                db.session.rollback()
                error_count += 1
        
        logger.info("\n" + "="*60)
        logger.info("Миграция завершена:")
        logger.info(f"  - Мигрировано: {migrated_count}")
        logger.info(f"  - Пропущено: {skipped_count}")
        logger.info(f"  - Ошибок: {error_count}")
        logger.info("="*60)

if __name__ == "__main__":
    migrate_profile_data()
