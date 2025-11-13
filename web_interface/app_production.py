#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Веб-интерфейс для настройки Call Analyzer (Production версия)
С интеграцией базы данных и авторизации
"""

import os
import sys
import json
import shutil
import yaml
import logging
import re
import importlib
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import threading
import subprocess
import time
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Добавляем путь к модулям проекта
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Импортируем конфигурацию и базу данных
from config.settings import get_config
from database.models import db, User, Call, TransferCase, RecallCase, SystemLog
from auth import login_manager
from auth.routes import auth_bp
from auth.decorators import admin_required

# Импортируем конфигурацию проекта (legacy)
try:
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'call_analyzer'))
    import config as project_config
except ImportError:
    print("Ошибка: Не удалось импортировать config.py из call_analyzer")
    class MockConfig:
        SPEECHMATICS_API_KEY = ''
        THEBAI_API_KEY = ''
        TELEGRAM_BOT_TOKEN = ''
        ALERT_CHAT_ID = ''
        LEGAL_ENTITY_CHAT_ID = ''
        TG_CHANNEL_NIZH = ''
        TG_CHANNEL_OTHER = ''
        BASE_RECORDS_PATH = ''
        PROMPTS_FILE = ''
        ADDITIONAL_VOCAB_FILE = ''
        STATION_NAMES = {}
        STATION_CHAT_IDS = {}
        STATION_MAPPING = {}
        NIZH_STATION_CODES = []
        LEGAL_ENTITY_KEYWORDS = []
    project_config = MockConfig()

def reload_project_config():
    """Перезагружает конфигурацию проекта"""
    global project_config
    try:
        importlib.reload(project_config)
        logging.info("Конфигурация проекта перезагружена")
    except Exception as e:
        logging.error(f"Ошибка перезагрузки конфигурации: {e}")

# Создаем приложение Flask
app = Flask(__name__)
app.config.from_object(get_config())

# Инициализация расширений
db.init_app(app)
login_manager.init_app(app)

# Регистрация Blueprint для авторизации
app.register_blueprint(auth_bp)

# Автоматическая синхронизация при запуске
def initialize_app():
    """Инициализация приложения"""
    try:
        if app.debug:
            if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
                return
        
        # Создаем таблицы, если их нет
        with app.app_context():
            db.create_all()
        
        sync_prompts_from_config()
        app.logger.info("Автоматическая синхронизация промптов выполнена")
        
        # Автозапуск сервиса анализа (только на Windows)
        if sys.platform == 'win32':
            ensure_service_running()
    except Exception as e:
        app.logger.error(f"Ошибка автоматической синхронизации: {e}")

# Глобальные переменные для статуса сервиса
service_status = {
    'running': False,
    'pid': None,
    'last_start': None,
    'last_stop': None
}

def get_project_root():
    """Возвращает корневую папку проекта"""
    return Path(__file__).parent.parent

# ========== МАРШРУТЫ ==========

@app.route('/')
@login_required
def index():
    """Главная страница (требует авторизации)"""
    status = get_service_status()
    return render_template('index.html', status=status, user=current_user)

@app.route('/api/status')
@login_required
def api_status():
    """API для получения статуса системы"""
    status = get_service_status()
    return jsonify({
        'service': status,
        'timestamp': datetime.now().isoformat()
    })

# ========== API для переводов (использует БД) ==========

@app.route('/transfers')
@login_required
def transfers_page():
    """Страница управления переводами"""
    return render_template('transfers.html')

@app.route('/api/transfers')
@login_required
def api_transfers():
    """API для получения списка переводов из БД"""
    try:
        # Получаем параметры фильтрации
        status_filter = request.args.get('status', None)
        limit = request.args.get('limit', 100, type=int)
        
        query = TransferCase.query
        
        if status_filter:
            query = query.filter_by(status=status_filter)
        
        transfers = query.order_by(TransferCase.created_at.desc()).limit(limit).all()
        
        result = []
        for transfer in transfers:
            result.append({
                'id': transfer.id,
                'phone_number': transfer.phone_number,
                'station_code': transfer.station_code,
                'call_time': transfer.call_time.isoformat() if transfer.call_time else None,
                'deadline': transfer.deadline.isoformat() if transfer.deadline else None,
                'status': transfer.status,
                'target_station': transfer.target_station,
                'analysis': transfer.analysis,
                'tg_msg_id': transfer.tg_msg_id,
                'remind_at': transfer.remind_at.isoformat() if transfer.remind_at else None,
                'notified': transfer.notified,
                'created_at': transfer.created_at.isoformat() if transfer.created_at else None
            })
        
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Ошибка получения переводов: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/transfers/<int:transfer_id>', methods=['PUT'])
@login_required
def api_transfer_update(transfer_id):
    """Обновление перевода"""
    try:
        transfer = TransferCase.query.get_or_404(transfer_id)
        data = request.get_json()
        
        if 'status' in data:
            transfer.status = data['status']
        if 'target_station' in data:
            transfer.target_station = data['target_station']
        if 'analysis' in data:
            transfer.analysis = data['analysis']
        if 'notified' in data:
            transfer.notified = data['notified']
        
        transfer.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Перевод обновлен'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Ошибка обновления перевода: {e}")
        return jsonify({'error': str(e)}), 500

# ========== API для перезвонов (использует БД) ==========

@app.route('/recalls')
@login_required
def recalls_page():
    """Страница управления перезвонами"""
    return render_template('recalls.html')

@app.route('/api/recalls')
@login_required
def api_recalls():
    """API для получения списка перезвонов из БД"""
    try:
        # Получаем параметры фильтрации
        status_filter = request.args.get('status', None)
        limit = request.args.get('limit', 100, type=int)
        
        query = RecallCase.query
        
        if status_filter:
            query = query.filter_by(status=status_filter)
        
        recalls = query.order_by(RecallCase.created_at.desc()).limit(limit).all()
        
        result = []
        for recall in recalls:
            result.append({
                'id': recall.id,
                'phone_number': recall.phone_number,
                'station_code': recall.station_code,
                'call_time': recall.call_time.isoformat() if recall.call_time else None,
                'deadline': recall.deadline.isoformat() if recall.deadline else None,
                'status': recall.status,
                'recall_station': recall.recall_station,
                'recall_when': recall.recall_when,
                'analysis': recall.analysis,
                'tg_msg_id': recall.tg_msg_id,
                'remind_at': recall.remind_at.isoformat() if recall.remind_at else None,
                'notified': recall.notified,
                'created_at': recall.created_at.isoformat() if recall.created_at else None
            })
        
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Ошибка получения перезвонов: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/recalls/<int:recall_id>', methods=['PUT'])
@login_required
def api_recall_update(recall_id):
    """Обновление перезвона"""
    try:
        recall = RecallCase.query.get_or_404(recall_id)
        data = request.get_json()
        
        if 'status' in data:
            recall.status = data['status']
        if 'recall_station' in data:
            recall.recall_station = data['recall_station']
        if 'recall_when' in data:
            recall.recall_when = data['recall_when']
        if 'analysis' in data:
            recall.analysis = data['analysis']
        if 'notified' in data:
            recall.notified = data['notified']
        
        recall.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Перезвон обновлен'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Ошибка обновления перезвона: {e}")
        return jsonify({'error': str(e)}), 500

# ========== Остальные функции (из оригинального app.py) ==========
# Здесь нужно добавить остальные маршруты из оригинального app.py
# с добавлением @login_required для защищенных страниц
# и @admin_required для страниц администратора

def sync_prompts_from_config():
    """Синхронизирует промпты из config.py с prompts.yaml"""
    # ... (код из оригинального app.py)
    pass

def get_service_status():
    """Проверяет статус сервиса Call Analyzer"""
    # ... (код из оригинального app.py, адаптированный для Linux)
    if sys.platform == 'win32':
        # Windows код
        pass
    else:
        # Linux код - проверка через systemd
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', 'call-analyzer-service'],
                capture_output=True,
                text=True
            )
            service_status['running'] = (result.returncode == 0)
        except Exception as e:
            app.logger.error(f"Ошибка проверки статуса сервиса: {e}")
            service_status['running'] = False
    return service_status

def ensure_service_running():
    """Проверяет и запускает сервис, если он не запущен (только Windows)"""
    if sys.platform != 'win32':
        return
    # ... (код из оригинального app.py)
    pass

if __name__ == '__main__':
    # Настраиваем логирование
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        handlers=[
            logging.FileHandler('web_interface.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    print("Запуск веб-интерфейса Call Analyzer...")
    print("Откройте браузер и перейдите по адресу: http://localhost:5000")
    
    # Выполняем инициализацию перед запуском
    initialize_app()
    
    # Определяем хост и порт из переменных окружения
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_ENV', 'development') == 'development'
    
    app.run(host=host, port=port, debug=debug, use_reloader=False)

