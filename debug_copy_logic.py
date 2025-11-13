#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Отладка логики копирования файлов анализа
"""

import os
import re
from datetime import datetime, timedelta

# Тестовые данные
tg_bw_calls_content = "fs-bw-+79012870546-303-2-13-11-2025 09-57.mp3"
analysis_file = "external-303-+79012870546-20251113-095744-1759471064.56107_analysis.txt"

# Парсим tg_bw_calls
line = tg_bw_calls_content.strip()
match = re.match(r'^(?:[^-]+-){2}(\+?\d+)-(.+?)-(.+?)-(\d{2}-\d{2}-\d{4}) (\d{2}-\d{2})\.mp3$', line)

if match:
    phone_number = match.group(1).lstrip('+')
    date_str = match.group(4)
    time_str = match.group(5)
    date_time_str = f"{date_str} {time_str.replace('-', ':')}"
    date_time_obj = datetime.strptime(date_time_str, '%d-%m-%Y %H:%M')
    
    print(f"Parsed from tg_bw_calls:")
    print(f"  Phone: {phone_number}")
    print(f"  DateTime: {date_time_obj}")
    print(f"  Key: ({phone_number}, {date_time_obj.strftime('%Y-%m-%d %H:%M')})")
    
    call_records_dict = {(phone_number, date_time_obj.strftime('%Y-%m-%d %H:%M')): True}
    print(f"\ncall_records_dict: {call_records_dict}")

# Парсим файл анализа
base_name = analysis_file.replace('_analysis.txt', '')
print(f"\nParsing analysis file: {base_name}")

if base_name.lower().startswith('external-'):
    try:
        parts = base_name.split('-')
        pre_phone = parts[2].lstrip('+')
        yyyymmdd = parts[3]
        hhmmss = parts[4]
        pre_dt = datetime.strptime(f"{yyyymmdd} {hhmmss}", '%Y%m%d %H%M%S')
        
        print(f"  Phone: {pre_phone}")
        print(f"  DateTime: {pre_dt}")
        print(f"  Key: ({pre_phone}, {pre_dt.strftime('%Y-%m-%d %H:%M')})")
        
        # Проверка точного совпадения
        key_exact = (pre_phone, pre_dt.strftime('%Y-%m-%d %H:%M'))
        in_calls = key_exact in call_records_dict
        print(f"\nExact match: {in_calls}")
        
        # Проверка с допуском ±5 минут
        if not in_calls:
            print("\nChecking with ±5 minutes tolerance:")
            for minutes_diff in range(-5, 6):
                adjusted_time = pre_dt + timedelta(minutes=minutes_diff)
                key = (pre_phone, adjusted_time.strftime('%Y-%m-%d %H:%M'))
                print(f"  {minutes_diff:+3d} min: {key} -> {key in call_records_dict}")
                if key in call_records_dict:
                    in_calls = True
                    break
        
        print(f"\nFinal result: File should be copied = {in_calls}")
        
    except Exception as e:
        print(f"Error parsing: {e}")
