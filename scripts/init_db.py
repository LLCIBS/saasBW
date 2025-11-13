#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт инициализации базы данных
Создает таблицы и начального администратора
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
    pass  # Игнорируем ошибки смены директории

from flask import Flask
from config.settings import get_config
from database.models import db, User
from dotenv import load_dotenv
import sys

# Загружаем переменные окружения с правильной кодировкой
# Устанавливаем UTF-8 для вывода
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

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
# Это нужно потому что config/settings.py читает переменные при импорте,
# до того как load_dotenv() загрузит .env файл
from urllib.parse import quote_plus

# Используем переменные из .env (они уже загружены)
db_user = os.getenv('DB_USER', os.getenv('DATABASE_USER', 'postgres'))
db_pass = os.getenv('DB_PASSWORD', os.getenv('DATABASE_PASSWORD', 'postgres'))
db_host = os.getenv('DB_HOST', 'localhost')
db_port = os.getenv('DB_PORT', '5432')
db_name = os.getenv('DB_NAME', os.getenv('DATABASE_NAME', 'saas'))

# Если есть DATABASE_URL, проверяем его, иначе формируем из параметров
db_url = os.getenv('DATABASE_URL')
if db_url:
    # Проверяем валидность DATABASE_URL
    try:
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Invalid URL")
        # URL валидный, используем его
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        print(f"✓ Используется DATABASE_URL из .env")
    except Exception:
        # URL невалидный, формируем из параметров
        db_url = f"postgresql://{quote_plus(db_user)}:{quote_plus(db_pass)}@{db_host}:{db_port}/{db_name}"
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        print(f"✓ DATABASE_URL сформирован из параметров: postgresql://{db_user}:***@{db_host}:{db_port}/{db_name}")
else:
    # Формируем URL из отдельных параметров
    db_url = f"postgresql://{quote_plus(db_user)}:{quote_plus(db_pass)}@{db_host}:{db_port}/{db_name}"
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    print(f"✓ DATABASE_URL сформирован: postgresql://{db_user}:***@{db_host}:{db_port}/{db_name}")

# Инициализируем расширения
db.init_app(app)

with app.app_context():
    print("Создание таблиц базы данных...")
    db.create_all()
    print("✓ Таблицы созданы")
    
    # Создаем администратора, если его нет
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    admin_password = os.getenv('ADMIN_PASSWORD', 'admin')
    
    admin = User.query.filter_by(username=admin_username).first()
    if not admin:
        print(f"Создание администратора: {admin_username}")
        admin = User(
            username=admin_username,
            role='admin',
            is_active=True
        )
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()
        print(f"✓ Администратор создан: {admin_username} / {admin_password}")
        print("⚠ ВАЖНО: Смените пароль после первого входа!")
    else:
        print(f"✓ Администратор уже существует: {admin_username}")
    
    print("\nБаза данных инициализирована успешно!")

