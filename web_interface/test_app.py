#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Простой тестовый веб-интерфейс для Call Analyzer
"""

from flask import Flask, render_template, request, jsonify
import os
import sys
import json
import yaml
from pathlib import Path

app = Flask(__name__)
app.config['SECRET_KEY'] = 'test_secret_key'

def get_project_root():
    """Возвращает корневую папку проекта"""
    return Path(__file__).parent.parent

@app.route('/')
def index():
    """Главная страница"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Call Analyzer - Веб-интерфейс</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .header { background: #2c3e50; color: white; padding: 20px; border-radius: 5px; }
            .content { margin: 20px 0; }
            .section { background: #ecf0f1; padding: 15px; margin: 10px 0; border-radius: 5px; }
            .status { padding: 10px; border-radius: 5px; margin: 10px 0; }
            .success { background: #d5f4e6; border: 1px solid #27ae60; }
            .info { background: #d6eaf8; border: 1px solid #3498db; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🎯 Call Analyzer - Веб-интерфейс</h1>
            <p>Система анализа телефонных звонков</p>
        </div>
        
        <div class="content">
            <div class="section">
                <h2>📊 Статус системы</h2>
                <div class="status success">
                    ✅ Веб-интерфейс работает корректно
                </div>
                <div class="status info">
                    ℹ️ Версия: 1.0.0 | Python: ''' + sys.version.split()[0] + '''
                </div>
            </div>
            
            <div class="section">
                <h2>🔧 Доступные функции</h2>
                <ul>
                    <li><strong>Конфигурация</strong> - Управление API ключами и настройками</li>
                    <li><strong>Станции</strong> - Добавление и редактирование станций</li>
                    <li><strong>Промпты</strong> - Управление AI промптами</li>
                    <li><strong>Словари</strong> - Дополнительная лексика</li>
                    <li><strong>Отчеты</strong> - Генерация отчетов</li>
                    <li><strong>Переводы</strong> - Управление переводами клиентов</li>
                    <li><strong>Отзывы</strong> - Управление отзывами</li>
                    <li><strong>Логи</strong> - Просмотр системных логов</li>
                </ul>
            </div>
            
            <div class="section">
                <h2>📁 Структура проекта</h2>
                <p><strong>Корневая папка:</strong> ''' + str(get_project_root()) + '''</p>
                <p><strong>Конфигурационные файлы:</strong></p>
                <ul>
                    <li>config.txt - Основная конфигурация</li>
                    <li>prompts.yaml - AI промпты</li>
                    <li>additional_vocab.yaml - Дополнительная лексика</li>
                    <li>transfer_cases.json - Данные переводов</li>
                    <li>recall_cases.json - Данные отзывов</li>
                </ul>
            </div>
            
            <div class="section">
                <h2>🚀 Быстрый старт</h2>
                <ol>
                    <li>Перейдите в раздел "Конфигурация" для настройки API ключей</li>
                    <li>Настройте станции в соответствующем разделе</li>
                    <li>Проверьте и отредактируйте промпты для AI анализа</li>
                    <li>Запустите основную систему через bat файлы</li>
                </ol>
            </div>
        </div>
        
        <div class="section">
            <h2>📞 API эндпоинты</h2>
            <ul>
                <li><code>GET /api/status</code> - Статус системы</li>
                <li><code>GET /api/config/load</code> - Загрузка конфигурации</li>
                <li><code>POST /api/config/save</code> - Сохранение конфигурации</li>
                <li><code>GET /api/stations</code> - Список станций</li>
                <li><code>GET /api/prompts</code> - Промпты</li>
                <li><code>GET /api/vocabulary</code> - Словарь</li>
                <li><code>GET /api/transfers</code> - Переводы</li>
                <li><code>GET /api/recalls</code> - Отзывы</li>
            </ul>
        </div>
    </body>
    </html>
    '''

@app.route('/api/status')
def api_status():
    """API для получения статуса системы"""
    return jsonify({
        'status': 'running',
        'version': '1.0.0',
        'python_version': sys.version.split()[0],
        'project_root': str(get_project_root()),
        'timestamp': str(Path(__file__).stat().st_mtime)
    })

@app.route('/api/config/load')
def api_config_load():
    """API для загрузки конфигурации"""
    config_file = get_project_root() / 'config.txt'
    config_data = {}
    
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # Простое парсирование config.txt
                for line in content.split('\n'):
                    if '=' in line and not line.strip().startswith('#'):
                        key, value = line.split('=', 1)
                        config_data[key.strip()] = value.strip().strip('"\'')
        except Exception as e:
            config_data['error'] = str(e)
    
    return jsonify(config_data)

@app.route('/api/prompts')
def api_prompts():
    """API для получения промптов"""
    prompts_file = get_project_root() / 'prompts.yaml'
    prompts_data = {}
    
    if prompts_file.exists():
        try:
            with open(prompts_file, 'r', encoding='utf-8') as f:
                prompts_data = yaml.safe_load(f)
        except Exception as e:
            prompts_data['error'] = str(e)
    
    return jsonify(prompts_data)

@app.route('/api/vocabulary')
def api_vocabulary():
    """API для получения словаря"""
    vocab_file = get_project_root() / 'additional_vocab.yaml'
    vocab_data = {}
    
    if vocab_file.exists():
        try:
            with open(vocab_file, 'r', encoding='utf-8') as f:
                vocab_data = yaml.safe_load(f)
        except Exception as e:
            vocab_data['error'] = str(e)
    
    return jsonify(vocab_data)

@app.route('/api/transfers')
def api_transfers():
    """API для получения переводов"""
    transfers_file = get_project_root() / 'transfer_cases.json'
    transfers_data = []
    
    if transfers_file.exists():
        try:
            with open(transfers_file, 'r', encoding='utf-8') as f:
                transfers_data = json.load(f)
        except Exception as e:
            transfers_data = [{'error': str(e)}]
    
    return jsonify(transfers_data)

@app.route('/api/recalls')
def api_recalls():
    """API для получения отзывов"""
    recalls_file = get_project_root() / 'recall_cases.json'
    recalls_data = []
    
    if recalls_file.exists():
        try:
            with open(recalls_file, 'r', encoding='utf-8') as f:
                recalls_data = json.load(f)
        except Exception as e:
            recalls_data = [{'error': str(e)}]
    
    return jsonify(recalls_data)

if __name__ == '__main__':
    print("🚀 Запуск тестового веб-интерфейса Call Analyzer...")
    print("📱 Откройте браузер и перейдите по адресу: http://localhost:5000")
    print("🔧 API доступен по адресу: http://localhost:5000/api/status")
    print("⏹️  Для остановки нажмите Ctrl+C")
    
    app.run(host='0.0.0.0', port=5000, debug=True)


