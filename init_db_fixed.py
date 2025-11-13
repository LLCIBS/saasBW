#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт инициализации базы данных с исправленной обработкой кодировки
"""

import sys
import os
from pathlib import Path

# Устанавливаем UTF-8 для Windows
if sys.platform == 'win32':
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Находим корень проекта
script_dir = Path(__file__).resolve().parent
project_root = script_dir
sys.path.insert(0, str(project_root))

# Устанавливаем рабочую директорию
os.chdir(str(project_root))

print(f"Рабочая директория: {project_root}")
print(f"Python: {sys.executable}")

try:
    from flask import Flask
    from config.settings import get_config
    from database.models import db, User
    from dotenv import load_dotenv
    from urllib.parse import quote_plus
    
    # Загружаем .env с правильной кодировкой
    env_path = project_root / '.env'
    if env_path.exists():
        load_dotenv(env_path, encoding='utf-8')
        print(f"✓ Загружен .env из {env_path}")
    else:
        load_dotenv(encoding='utf-8')
        print("⚠ .env файл не найден")
    
    app = Flask(__name__)
    config = get_config()
    app.config.from_object(config)
    
    # Проверяем DATABASE_URL
    db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    print(f"\nDATABASE_URL: {db_url[:50]}...")
    print(f"Type: {type(db_url)}")
    
    # Если есть проблема с кодировкой, формируем URL заново
    if isinstance(db_url, bytes):
        print("⚠ DATABASE_URL в bytes, конвертируем...")
        db_url = db_url.decode('utf-8', errors='replace')
    
    # Если DATABASE_URL содержит невалидные символы, используем отдельные параметры
    try:
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Invalid URL")
    except Exception as e:
        print(f"⚠ Проблема с DATABASE_URL, формируем из параметров: {e}")
        db_user = os.getenv('DB_USER', 'postgres')
        db_pass = os.getenv('DB_PASSWORD', 'postgres')
        db_host = os.getenv('DB_HOST', 'localhost')
        db_port = os.getenv('DB_PORT', '5432')
        db_name = os.getenv('DB_NAME', 'saas')
        db_url = f"postgresql://{quote_plus(db_user)}:{quote_plus(db_pass)}@{db_host}:{db_port}/{db_name}"
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        print(f"✓ Сформирован новый DATABASE_URL: postgresql://{db_user}:***@{db_host}:{db_port}/{db_name}")
    
    # Инициализируем расширения
    db.init_app(app)
    
    print("\nПопытка создания таблиц...")
    with app.app_context():
        try:
            db.create_all()
            print("✓ Таблицы созданы")
        except Exception as e:
            print(f"❌ Ошибка при создании таблиц: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        
        # Создаем администратора, если его нет
        admin_username = os.getenv('ADMIN_USERNAME', 'admin')
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin')
        
        admin = User.query.filter_by(username=admin_username).first()
        if not admin:
            print(f"\nСоздание администратора: {admin_username}")
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
        
        print("\n✅ База данных инициализирована успешно!")
        
except Exception as e:
    print(f"❌ Критическая ошибка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

