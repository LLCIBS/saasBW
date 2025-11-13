#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки и сброса пароля администратора
"""

import sys
import os
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Загружаем переменные окружения
from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path, encoding='utf-8')
else:
    load_dotenv(encoding='utf-8')

from flask import Flask
from config.settings import get_config
from database.models import db, User
from urllib.parse import quote_plus

app = Flask(__name__)
config = get_config()
app.config.from_object(config)

# Переопределяем DATABASE_URL после загрузки .env
db_user = os.getenv('DB_USER', os.getenv('DATABASE_USER', 'postgres'))
db_pass = os.getenv('DB_PASSWORD', os.getenv('DATABASE_PASSWORD', 'postgres'))
db_host = os.getenv('DB_HOST', 'localhost')
db_port = os.getenv('DB_PORT', '5432')
db_name = os.getenv('DB_NAME', os.getenv('DATABASE_NAME', 'saas'))

db_url = os.getenv('DATABASE_URL')
if not db_url:
    db_url = f"postgresql://{quote_plus(db_user)}:{quote_plus(db_pass)}@{db_host}:{db_port}/{db_name}"
app.config['SQLALCHEMY_DATABASE_URI'] = db_url

db.init_app(app)

with app.app_context():
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    
    # Проверяем, существует ли администратор
    admin = User.query.filter_by(username=admin_username).first()
    
    if not admin:
        print(f"❌ Администратор '{admin_username}' не найден в базе данных!")
        print("\nСоздайте администратора, запустив:")
        print("  python3 scripts/init_db.py")
    else:
        print(f"✓ Администратор '{admin_username}' найден")
        print(f"  ID: {admin.id}")
        print(f"  Роль: {admin.role}")
        print(f"  Активен: {admin.is_active}")
        print(f"  Создан: {admin.created_at}")
        print(f"  Password hash: {admin.password_hash[:50]}...")
        
        # Проверяем пароль
        test_password = os.getenv('ADMIN_PASSWORD', 'admin')
        if admin.check_password(test_password):
            print(f"\n✓ Пароль '{test_password}' правильный!")
        else:
            print(f"\n❌ Пароль '{test_password}' НЕ правильный!")
            print("\nСброс пароля на 'admin'...")
            admin.set_password('admin')
            db.session.commit()
            print("✓ Пароль сброшен на 'admin'")
            print("\nТеперь вы можете войти с:")
            print(f"  Логин: {admin_username}")
            print(f"  Пароль: admin")
            print("\n⚠ ВАЖНО: Смените пароль после первого входа!")

