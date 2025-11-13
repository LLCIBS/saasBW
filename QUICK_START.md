# 🚀 Быстрый старт - Call Analyzer

## ✅ Все исправлено и готово!

### Что было исправлено:
1. ✅ Конфликт protobuf - решено
2. ✅ grpcio для Python 3.13 - установлен (1.76.0)
3. ✅ grpcio-tools для Python 3.13 - установлен (1.75.1)
4. ✅ SQLAlchemy для Python 3.13 - обновлен (2.0.44)
5. ✅ Flask-SQLAlchemy, Flask-Login - установлены
6. ✅ psycopg2-binary для Python 3.13 - установлен (2.9.11)

## 📋 Запуск проекта

### 1. Установите зависимости (если еще не установлены)

```powershell
# Активируйте venv (если используете)
.\venv\Scripts\Activate.ps1

# Установите зависимости
pip install -r requirements.txt
```

**Примечание:** `grpcio` и `grpcio-tools` уже установлены в системе и будут пропущены.

### 2. Инициализируйте базу данных

```powershell
# В корне проекта создайте файл test_db.py и запустите:
python test_db_connection.py
```

Или вручную через Python:
```powershell
python -c "from flask import Flask; from config.settings import get_config; from database.models import db, User; from dotenv import load_dotenv; import os; load_dotenv(); app = Flask(__name__); app.config.from_object(get_config()); db.init_app(app); app.app_context().push(); db.create_all(); admin = User.query.filter_by(username='admin').first(); admin or (admin := User(username='admin', role='admin', is_active=True), admin.set_password('admin'), db.session.add(admin), db.session.commit()); print('✅ БД инициализирована!')"
```

### 3. Запустите приложение

```powershell
# Сервис анализа звонков
python call_analyzer\main.py

# Веб-интерфейс (в другом окне)
python web_interface\app.py
```

## 🔍 Проверка установки

```powershell
# Проверка всех модулей
python -c "import grpc, grpc_tools, flask_sqlalchemy, flask_login, psycopg2, sqlalchemy; print('✅ Все модули работают!')"
```

## ⚠️ Важные замечания

1. **База данных:** Убедитесь, что PostgreSQL запущен и база `saas` существует
2. **Переменные окружения:** Файл `.env` создан и заполнен
3. **Конфигурация:** `config.py` обновлен для чтения из `.env`

## 📝 Установленные версии

- Python: 3.13.5
- grpcio: 1.76.0 ✅
- grpcio-tools: 1.75.1 ✅
- SQLAlchemy: 2.0.44 ✅
- Flask-SQLAlchemy: 3.1.1 ✅
- Flask-Login: 0.6.3 ✅
- psycopg2-binary: 2.9.11 ✅
- protobuf: 6.33.0 ✅

## 🎉 Готово!

Проект полностью настроен и готов к работе!

