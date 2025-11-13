#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки статуса генерации отчета
"""

import os
import time
from datetime import datetime

def check_report_folder():
    """Проверка папки с отчетом"""
    today = datetime.now()
    report_folder = f"D:\\3\\{today.year}\\{today.month:02d}\\{today.day:02d}\\transcriptions\\{today.day:02d}-{today.day:02d}_script"
    
    print(f"📁 Проверка папки: {report_folder}")
    
    if not os.path.exists(report_folder):
        print("❌ Папка не существует")
        return
    
    print("✅ Папка существует")
    print("\n📄 Содержимое папки:")
    
    for item in os.listdir(report_folder):
        item_path = os.path.join(report_folder, item)
        if os.path.isfile(item_path):
            size = os.path.getsize(item_path)
            mtime = datetime.fromtimestamp(os.path.getmtime(item_path))
            print(f"  - {item} ({size} байт, изменен: {mtime.strftime('%H:%M:%S')})")
    
    # Проверяем наличие Excel файла
    excel_files = [f for f in os.listdir(report_folder) if f.endswith('.xlsx')]
    
    if excel_files:
        print(f"\n✅ Найдены Excel файлы: {', '.join(excel_files)}")
    else:
        print("\n⏳ Excel файл еще не создан")
        
        # Проверяем tg_bw_calls.txt
        tg_file = os.path.join(report_folder, "tg_bw_calls.txt")
        if os.path.exists(tg_file):
            with open(tg_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            print(f"\n📋 В tg_bw_calls.txt найдено звонков: {len(lines)}")
            for line in lines[:5]:  # Показываем первые 5
                print(f"  - {line.strip()}")

if __name__ == '__main__':
    print("=" * 60)
    print("ПРОВЕРКА СТАТУСА ГЕНЕРАЦИИ ОТЧЕТА")
    print("=" * 60)
    check_report_folder()
