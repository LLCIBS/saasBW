#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый модуль для проверки генерации отчетов
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Добавляем путь к модулям проекта
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'call_analyzer'))

def test_report_generation():
    """Тестирование генерации отчетов"""
    print("🧪 Тестирование генерации отчетов...")
    
    # Проверяем доступность модулей
    modules_to_test = [
        'reports.week_full',
        'reports.rr_3', 
        'reports.rr_bad',
    ]
    
    results = {}
    
    for module_name in modules_to_test:
        try:
            module = __import__(module_name, fromlist=['run_week_full', 'run_rr_3', 'run_rr_bad'])
            results[module_name] = {
                'status': 'available',
                'message': 'Модуль доступен'
            }
            print(f"✅ {module_name} - доступен")
        except ImportError as e:
            results[module_name] = {
                'status': 'error',
                'message': f'Модуль недоступен: {str(e)}'
            }
            print(f"❌ {module_name} - недоступен: {str(e)}")
        except Exception as e:
            results[module_name] = {
                'status': 'error',
                'message': f'Ошибка загрузки: {str(e)}'
            }
            print(f"⚠️ {module_name} - ошибка: {str(e)}")
    
    # Проверяем зависимости
    dependencies = [
        'pandas',
        'openpyxl',
        'requests',
        'yaml',
        'watchdog',
        'APScheduler'
    ]
    
    print("\n📦 Проверка зависимостей:")
    for dep in dependencies:
        try:
            __import__(dep)
            print(f"✅ {dep} - установлен")
        except ImportError:
            print(f"❌ {dep} - не установлен")
    
    # Проверяем конфигурационные файлы
    project_root = Path(__file__).parent.parent
    config_files = [
        'config.txt',
        'prompts.yaml',
        'additional_vocab.yaml',
        'transfer_cases.json',
        'recall_cases.json'
    ]
    
    print("\n📁 Проверка конфигурационных файлов:")
    for config_file in config_files:
        file_path = project_root / config_file
        if file_path.exists():
            print(f"✅ {config_file} - существует")
        else:
            print(f"❌ {config_file} - не найден")
    
    return results

def create_test_report():
    """Создание тестового отчета"""
    print("\n📊 Создание тестового отчета...")
    
    try:
        import pandas as pd
        
        # Создаем тестовые данные
        data = {
            'Дата': ['2024-01-01', '2024-01-02', '2024-01-03'],
            'Станция': ['NN01', 'NN02', 'NN01'],
            'Звонков': [10, 15, 12],
            'Качество': [8.5, 7.8, 9.2]
        }
        
        df = pd.DataFrame(data)
        
        # Сохраняем в Excel
        output_file = Path(__file__).parent.parent / 'test_report.xlsx'
        df.to_excel(output_file, index=False)
        
        print(f"✅ Тестовый отчет создан: {output_file}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка создания тестового отчета: {e}")
        return False

if __name__ == '__main__':
    print("🚀 Запуск тестирования системы отчетов Call Analyzer")
    print("=" * 60)
    
    # Тестируем генерацию отчетов
    results = test_report_generation()
    
    # Создаем тестовый отчет
    test_report_created = create_test_report()
    
    print("\n" + "=" * 60)
    print("📋 Результаты тестирования:")
    
    for module, result in results.items():
        status_icon = "✅" if result['status'] == 'available' else "❌"
        print(f"{status_icon} {module}: {result['message']}")
    
    if test_report_created:
        print("✅ Тестовый отчет: успешно создан")
    else:
        print("❌ Тестовый отчет: ошибка создания")
    
    print("\n🎯 Рекомендации:")
    if any(result['status'] == 'error' for result in results.values()):
        print("- Установите недостающие зависимости: pip install pandas openpyxl")
        print("- Проверьте наличие модулей отчетов в папке reports/")
    else:
        print("- Все модули отчетов доступны")
        print("- Система готова к генерации отчетов")
    
    print("\n✨ Тестирование завершено!")


