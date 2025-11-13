#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Простой скрипт инициализации БД - работает из любой директории"""

import sys
import os
from pathlib import Path

# Находим корень проекта
script_dir = Path(__file__).resolve().parent
project_root = script_dir

# Проверяем, что мы в правильной директории
if not (project_root / 'database').exists():
    # Пробуем найти проект выше
    for parent in project_root.parents:
        if (parent / 'database').exists() and (parent / 'config').exists():
            project_root = parent
            break

os.chdir(project_root)
sys.path.insert(0, str(project_root))

print(f"Рабочая директория: {project_root}")
print(f"Python: {sys.executable}")

try:
    from flask import Flask
    from config.settings import get_config
    from database.models import db, User
    from dotenv import load_dotenv
    
    # Загружаем переменные окружения
    env_path = project_root / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✓ Загружен .env из {env_path}")
    else:
        load_dotenv()
        print("⚠ .env файл не найден, используются значения по умолчанию")
    
    app = Flask(__name__)
    app.config.from_object(get_config())
    
    print(f"✓ DATABASE_URL: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # Инициализируем расширения
    db.init_app(app)
    
    with app.app_context():
        print("\nСоздание таблиц базы данных...")
        try:
            db.create_all()
            print("✓ Таблицы созданы")
        except Exception as e:
            print(f"❌ Ошибка создания таблиц: {e}")
            import traceback
            traceback.print_exc()
            raise
        
        # Создаем администратора
        admin_username = os.getenv('ADMIN_USERNAME', 'admin')
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin')
        
        admin = User.query.filter_by(username=admin_username).first()
        if admin:
            print(f"✓ Администратор уже существует: {admin_username}")
        else:
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
        
        print("\n✅ База данных инициализирована успешно!")
        
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("\nУстановите зависимости:")
    print("  pip install Flask-SQLAlchemy Flask-Login psycopg2-binary python-dotenv")
    sys.exit(1)
except Exception as e:
    print(f"❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
