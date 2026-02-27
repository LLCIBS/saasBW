#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ежедневный цикл самообучения системы классификации
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

try:
    from .self_learning_system import IntegratedLearningSystem
except ImportError:
    # Добавляем текущую директорию в путь для совместимости с прямым запуском файла.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from self_learning_system import IntegratedLearningSystem


def run_daily_learning_cycle():
    """Запуск ежедневного цикла самообучения"""
    print("=" * 60)
    print("ЕЖЕДНЕВНЫЙ ЦИКЛ САМООБУЧЕНИЯ СИСТЕМЫ КЛАССИФИКАЦИИ")
    print("=" * 60)
    print(f"Дата и время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    try:
        # Инициализируем систему самообучения
        print("Инициализация системы самообучения...")
        learning_system = IntegratedLearningSystem()
        print("Система инициализирована.")
        print()
        
        # Запускаем ежедневный цикл
        print("Запуск ежедневного цикла самообучения...")
        result = learning_system.daily_learning_cycle()
        print()
        
        # Выводим результаты
        print("РЕЗУЛЬТАТЫ ЕЖЕДНЕВНОГО ЦИКЛА:")
        print("-" * 60)
        
        # Правила обновлены
        rules_updated = result.get('rules_updated', 0)
        print(f"Правил автоматически обновлено: {rules_updated}")
        
        # Эффективность примеров
        effectiveness = result.get('effectiveness', {})
        effective_count = effectiveness.get('effective_count', 0)
        ineffective_count = effectiveness.get('ineffective_count', 0)
        print(f"Эффективных примеров: {effective_count}")
        print(f"Неэффективных примеров: {ineffective_count}")
        
        # Отчет о паттернах ошибок
        report = result.get('report', {})
        error_patterns = report.get('error_patterns', {})
        total_patterns = error_patterns.get('total', 0)
        print(f"Паттернов ошибок обнаружено: {total_patterns}")
        
        # Прогресс обучения
        learning_progress = report.get('learning_progress', {})
        if learning_progress:
            current_accuracy = learning_progress.get('current_accuracy', 0)
            improvement = learning_progress.get('accuracy_improvement', 0)
            confirmations = learning_progress.get('total_confirmations', 0)
            corrections = learning_progress.get('total_corrections', 0)
            
            print()
            print("ПРОГРЕСС ОБУЧЕНИЯ (за последние 30 дней):")
            print(f"  Текущая точность: {current_accuracy:.1f}%")
            if improvement > 0:
                print(f"  Улучшение: +{improvement:.1f}%")
            elif improvement < 0:
                print(f"  Изменение: {improvement:.1f}%")
            print(f"  Подтверждено правильных: {confirmations}")
            print(f"  Найдено ошибок: {corrections}")
        
        # Рекомендации
        recommendations = report.get('recommendations', [])
        if recommendations:
            print()
            print("РЕКОМЕНДАЦИИ СИСТЕМЫ:")
            for i, rec in enumerate(recommendations, 1):
                print(f"  {i}. {rec}")
        
        # Топ ошибок
        top_errors = error_patterns.get('top_5', [])
        if top_errors:
            print()
            print("ТОП-5 ЧАСТЫХ ОШИБОК:")
            for i, error in enumerate(top_errors[:5], 1):
                print(f"  {i}. {error['original_category']} → {error['corrected_category']} "
                      f"({error['frequency']} раз)")
        
        # Сохраняем отчет в файл
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        log_file = log_dir / f"daily_learning_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': result.get('timestamp'),
                'rules_updated': rules_updated,
                'effectiveness': effectiveness,
                'report': report
            }, f, ensure_ascii=False, indent=2, default=str)
        
        print()
        print(f"Отчет сохранен в: {log_file}")
        print()
        print("=" * 60)
        print("ЕЖЕДНЕВНЫЙ ЦИКЛ ЗАВЕРШЕН УСПЕШНО")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print()
        print("=" * 60)
        print("ОШИБКА ПРИ ВЫПОЛНЕНИИ ЕЖЕДНЕВНОГО ЦИКЛА")
        print("=" * 60)
        print(f"Ошибка: {str(e)}")
        import traceback
        print()
        print("Трассировка:")
        traceback.print_exc()
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = run_daily_learning_cycle()
    sys.exit(0 if success else 1)

