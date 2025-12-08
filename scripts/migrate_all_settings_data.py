#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт миграции всех данных из UserSettings.data в отдельные таблицы
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
    UserConfig, UserStation, UserStationMapping, UserStationChatId,
    UserEmployeeExtension, UserPrompt, UserVocabulary, UserScriptPrompt
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

def migrate_all_settings_data():
    """Мигрирует все данные из UserSettings.data в отдельные таблицы"""
    with app.app_context():
        logger.info("="*60)
        logger.info("Начало миграции всех данных из UserSettings.data")
        logger.info("="*60)
        
        # Получаем всех пользователей
        users = User.query.all()
        logger.info(f"Найдено пользователей: {len(users)}")
        
        stats = {
            'config': 0,
            'stations': 0,
            'station_mappings': 0,
            'station_chat_ids': 0,
            'employee_extensions': 0,
            'prompts': 0,
            'vocabulary': 0,
            'script_prompts': 0,
            'skipped': 0,
            'errors': 0
        }
        
        for user in users:
            try:
                # Получаем данные из UserSettings
                settings = UserSettings.query.filter_by(user_id=user.id).first()
                if not settings or not settings.data:
                    logger.info(f"Пользователь {user.username} (ID: {user.id}) не имеет данных в UserSettings, пропускаем")
                    stats['skipped'] += 1
                    continue
                
                data = settings.data
                
                # 1. Миграция конфигурации (config)
                config_data = data.get('config', {})
                if config_data:
                    user_config = UserConfig.query.filter_by(user_id=user.id).first()
                    if not user_config:
                        user_config = UserConfig(user_id=user.id)
                        db.session.add(user_config)
                    
                    # Paths
                    paths = config_data.get('paths', {})
                    if paths:
                        user_config.source_type = paths.get('source_type')
                        user_config.prompts_file = paths.get('prompts_file')
                        user_config.base_records_path = paths.get('base_records_path')
                        user_config.ftp_connection_id = paths.get('ftp_connection_id')
                        user_config.script_prompt_file = paths.get('script_prompt_file')
                        user_config.additional_vocab_file = paths.get('additional_vocab_file')
                    
                    # API Keys
                    api_keys = config_data.get('api_keys', {})
                    if api_keys:
                        user_config.thebai_api_key = api_keys.get('thebai_api_key')
                        user_config.telegram_bot_token = api_keys.get('telegram_bot_token')
                        user_config.speechmatics_api_key = api_keys.get('speechmatics_api_key')
                    
                    # Telegram
                    telegram = config_data.get('telegram', {})
                    if telegram:
                        user_config.alert_chat_id = telegram.get('alert_chat_id')
                        user_config.tg_channel_nizh = telegram.get('tg_channel_nizh')
                        user_config.tg_channel_other = telegram.get('tg_channel_other')
                    
                    # Transcription
                    transcription = config_data.get('transcription', {})
                    if transcription:
                        user_config.tbank_stereo_enabled = transcription.get('tbank_stereo_enabled', False)
                        user_config.use_additional_vocab = transcription.get('use_additional_vocab', True)
                        user_config.auto_detect_operator_name = transcription.get('auto_detect_operator_name', False)
                    
                    # Arrays
                    user_config.allowed_stations = config_data.get('allowed_stations')
                    user_config.nizh_station_codes = config_data.get('nizh_station_codes')
                    user_config.legal_entity_keywords = config_data.get('legal_entity_keywords')
                    
                    stats['config'] += 1
                    logger.info(f"✓ Мигрирована конфигурация для пользователя {user.username} (ID: {user.id})")
                
                # 2. Миграция станций
                stations = config_data.get('stations', {})
                if stations:
                    # Удаляем старые станции пользователя
                    UserStation.query.filter_by(user_id=user.id).delete()
                    
                    for code, name in stations.items():
                        station = UserStation(user_id=user.id, code=str(code), name=str(name))
                        db.session.add(station)
                        stats['stations'] += 1
                    logger.info(f"✓ Мигрировано станций: {len(stations)} для пользователя {user.username} (ID: {user.id})")
                
                # 3. Миграция маппинга станций
                station_mapping = config_data.get('station_mapping', {})
                if station_mapping:
                    # Удаляем старые маппинги
                    UserStationMapping.query.filter_by(user_id=user.id).delete()
                    
                    for main_code, sub_codes in station_mapping.items():
                        if isinstance(sub_codes, list):
                            for sub_code in sub_codes:
                                mapping = UserStationMapping(
                                    user_id=user.id,
                                    main_station_code=str(main_code),
                                    sub_station_code=str(sub_code)
                                )
                                db.session.add(mapping)
                                stats['station_mappings'] += 1
                    logger.info(f"✓ Мигрировано маппингов станций для пользователя {user.username} (ID: {user.id})")
                
                # 4. Миграция chat_id станций
                station_chat_ids = config_data.get('station_chat_ids', {})
                if station_chat_ids:
                    # Удаляем старые chat_id
                    UserStationChatId.query.filter_by(user_id=user.id).delete()
                    
                    for station_code, chat_id_list in station_chat_ids.items():
                        if isinstance(chat_id_list, list):
                            for chat_id in chat_id_list:
                                chat = UserStationChatId(
                                    user_id=user.id,
                                    station_code=str(station_code),
                                    chat_id=str(chat_id)
                                )
                                db.session.add(chat)
                                stats['station_chat_ids'] += 1
                    logger.info(f"✓ Мигрировано chat_id станций для пользователя {user.username} (ID: {user.id})")
                
                # 5. Миграция маппинга расширений к сотрудникам
                employee_by_extension = config_data.get('employee_by_extension', {})
                if employee_by_extension:
                    # Удаляем старые маппинги
                    UserEmployeeExtension.query.filter_by(user_id=user.id).delete()
                    
                    for extension, employee in employee_by_extension.items():
                        emp_ext = UserEmployeeExtension(
                            user_id=user.id,
                            extension=str(extension),
                            employee=str(employee)
                        )
                        db.session.add(emp_ext)
                        stats['employee_extensions'] += 1
                    logger.info(f"✓ Мигрировано маппингов расширений для пользователя {user.username} (ID: {user.id})")
                
                # 6. Миграция промптов
                prompts_data = data.get('prompts', {})
                if prompts_data:
                    # Удаляем старые промпты
                    UserPrompt.query.filter_by(user_id=user.id).delete()
                    
                    # Anchors
                    anchors = prompts_data.get('anchors', {})
                    if anchors:
                        for key, text in anchors.items():
                            prompt = UserPrompt(
                                user_id=user.id,
                                prompt_type='anchor',
                                prompt_key=str(key),
                                prompt_text=str(text)
                            )
                            db.session.add(prompt)
                            stats['prompts'] += 1
                    
                    # Stations
                    stations_prompts = prompts_data.get('stations', {})
                    if stations_prompts:
                        for station_code, text in stations_prompts.items():
                            prompt = UserPrompt(
                                user_id=user.id,
                                prompt_type='station',
                                prompt_key=str(station_code),
                                prompt_text=str(text)
                            )
                            db.session.add(prompt)
                            stats['prompts'] += 1
                    
                    # Default
                    default_prompt = prompts_data.get('default')
                    if default_prompt:
                        prompt = UserPrompt(
                            user_id=user.id,
                            prompt_type='default',
                            prompt_key='default',
                            prompt_text=str(default_prompt)
                        )
                        db.session.add(prompt)
                        stats['prompts'] += 1
                    
                    logger.info(f"✓ Мигрировано промптов для пользователя {user.username} (ID: {user.id})")
                
                # 7. Миграция словаря
                vocabulary_data = data.get('vocabulary', {})
                if vocabulary_data:
                    user_vocab = UserVocabulary.query.filter_by(user_id=user.id).first()
                    if not user_vocab:
                        user_vocab = UserVocabulary(user_id=user.id)
                        db.session.add(user_vocab)
                    
                    user_vocab.enabled = vocabulary_data.get('enabled', True)
                    user_vocab.additional_vocab = vocabulary_data.get('additional_vocab')
                    
                    stats['vocabulary'] += 1
                    logger.info(f"✓ Мигрирован словарь для пользователя {user.username} (ID: {user.id})")
                
                # 8. Миграция промпта скрипта
                script_prompt_data = data.get('script_prompt', {})
                if script_prompt_data:
                    user_script = UserScriptPrompt.query.filter_by(user_id=user.id).first()
                    if not user_script:
                        user_script = UserScriptPrompt(user_id=user.id)
                        db.session.add(user_script)
                    
                    user_script.prompt_text = script_prompt_data.get('prompt', '')
                    user_script.checklist = script_prompt_data.get('checklist')
                    
                    stats['script_prompts'] += 1
                    logger.info(f"✓ Мигрирован промпт скрипта для пользователя {user.username} (ID: {user.id})")
                
                # Сохраняем изменения
                db.session.commit()
                logger.info(f"✓ Все данные мигрированы для пользователя {user.username} (ID: {user.id})")
                
            except Exception as e:
                logger.error(f"✗ Ошибка при миграции данных для пользователя {user.username} (ID: {user.id}): {e}")
                import traceback
                logger.error(traceback.format_exc())
                db.session.rollback()
                stats['errors'] += 1
        
        logger.info("\n" + "="*60)
        logger.info("Миграция завершена:")
        logger.info(f"  - Конфигураций: {stats['config']}")
        logger.info(f"  - Станций: {stats['stations']}")
        logger.info(f"  - Маппингов станций: {stats['station_mappings']}")
        logger.info(f"  - Chat ID станций: {stats['station_chat_ids']}")
        logger.info(f"  - Маппингов расширений: {stats['employee_extensions']}")
        logger.info(f"  - Промптов: {stats['prompts']}")
        logger.info(f"  - Словарей: {stats['vocabulary']}")
        logger.info(f"  - Промптов скриптов: {stats['script_prompts']}")
        logger.info(f"  - Пропущено: {stats['skipped']}")
        logger.info(f"  - Ошибок: {stats['errors']}")
        logger.info("="*60)

if __name__ == "__main__":
    migrate_all_settings_data()
