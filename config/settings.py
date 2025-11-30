# config/settings.py
"""
Конфигурация для разных окружений (development/production)
Использует переменные окружения для настройки
"""

import os
from pathlib import Path
from urllib.parse import quote_plus, urlparse


class Config:
    """Базовая конфигурация"""
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # База данных
    # Используем отдельные параметры или DATABASE_URL
    # Это позволяет избежать проблем с кодировкой в путях Windows
    _db_host = os.getenv('DB_HOST', 'localhost')
    _db_port = os.getenv('DB_PORT', '5432')
    _db_user = os.getenv('DB_USER', os.getenv('DATABASE_USER', 'postgres'))
    _db_password = os.getenv('DB_PASSWORD', os.getenv('DATABASE_PASSWORD', 'postgres'))
    _db_name = os.getenv('DB_NAME', os.getenv('DATABASE_NAME', 'saas'))
    
    # Если есть DATABASE_URL, используем его, иначе формируем из параметров
    _db_url = os.getenv('DATABASE_URL')
    if _db_url:
        # Убеждаемся, что строка в правильной кодировке
        if isinstance(_db_url, bytes):
            _db_url = _db_url.decode('utf-8', errors='replace')
        # Проверяем, что это валидный URL
        try:
            parsed = urlparse(_db_url)
            if parsed.scheme and parsed.netloc:
                SQLALCHEMY_DATABASE_URI = _db_url
            else:
                raise ValueError("Invalid DATABASE_URL format")
        except Exception:
            # Если парсинг не удался, формируем из параметров
            _db_url = f"postgresql://{quote_plus(_db_user)}:{quote_plus(_db_password)}@{_db_host}:{_db_port}/{_db_name}"
            SQLALCHEMY_DATABASE_URI = _db_url
    else:
        # Формируем URL из отдельных параметров
        _db_url = f"postgresql://{quote_plus(_db_user)}:{quote_plus(_db_password)}@{_db_host}:{_db_port}/{_db_name}"
        SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
        'connect_args': {
            'client_encoding': 'utf8'
        }
    }
    
    # Пути
    BASE_DIR = Path(__file__).parent.parent
    BASE_RECORDS_PATH = Path(os.getenv('BASE_RECORDS_PATH', '/var/calls'))
    PROMPTS_FILE = Path(os.getenv('PROMPTS_FILE', str(BASE_DIR / 'prompts.yaml')))
    ADDITIONAL_VOCAB_FILE = Path(os.getenv('ADDITIONAL_VOCAB_FILE', str(BASE_DIR / 'additional_vocab.yaml')))
    
    # API ключи
    SPEECHMATICS_API_KEY = os.getenv('SPEECHMATICS_API_KEY', '')
    TBANK_API_KEY = os.getenv('TBANK_API_KEY', '')
    TBANK_SECRET_KEY = os.getenv('TBANK_SECRET_KEY', '')
    TBANK_STEREO_ENABLED = os.getenv('TBANK_STEREO_ENABLED', 'True').lower() == 'true'
    
    INTERNAL_TRANSCRIPTION_URL = os.getenv("INTERNAL_TRANSCRIPTION_URL", "http://192.168.101.59:8000/transcribe")
    
    THEBAI_API_KEY = os.getenv('THEBAI_API_KEY', '')
    THEBAI_URL = os.getenv('THEBAI_URL', 'https://api.deepseek.com/v1/chat/completions')
    THEBAI_MODEL = os.getenv('THEBAI_MODEL', 'deepseek-reasoner')
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    ALERT_CHAT_ID = os.getenv('ALERT_CHAT_ID', '')
    LEGAL_ENTITY_CHAT_ID = os.getenv('LEGAL_ENTITY_CHAT_ID', '')
    TG_CHANNEL_NIZH = os.getenv('TG_CHANNEL_NIZH', '')
    TG_CHANNEL_OTHER = os.getenv('TG_CHANNEL_OTHER', '')
    
    # Логирование
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', str(BASE_DIR / 'logs' / 'app.log'))
    
    # Безопасность
    SESSION_COOKIE_SECURE = False  # True для HTTPS в продакшн
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Flask-Login
    REMEMBER_COOKIE_DURATION = 86400  # 24 часа
    REMEMBER_COOKIE_SECURE = False  # True для HTTPS
    REMEMBER_COOKIE_HTTPONLY = True


class DevelopmentConfig(Config):
    """Конфигурация для разработки"""
    DEBUG = True
    TESTING = False
    # Используем родительскую логику для DATABASE_URL


class ProductionConfig(Config):
    """Конфигурация для продакшн"""
    DEBUG = False
    TESTING = False
    
    # Безопасность для продакшн
    SESSION_COOKIE_SECURE = True  # Требует HTTPS
    REMEMBER_COOKIE_SECURE = True
    
    # База данных из переменной окружения
    # Используем родительскую логику для DATABASE_URL
    
    # Логирование в файл
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'WARNING')


# Выбор конфигурации на основе переменной окружения
config_map = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

def get_config():
    """Получить конфигурацию на основе FLASK_ENV"""
    env = os.getenv('FLASK_ENV', 'development')
    return config_map.get(env, DevelopmentConfig)

