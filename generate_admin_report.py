#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для генерации отчета от пользователя admin
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:5000"
USERNAME = "admin"
PASSWORD = "admin"

def login():
    """Авторизация в системе"""
    print("🔐 Авторизация...")
    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={
            "username": USERNAME,
            "password": PASSWORD
        },
        allow_redirects=False
    )
    
    if response.status_code in [200, 302]:
        cookies = response.cookies
        print("✅ Авторизация успешна")
        return cookies
    else:
        print(f"❌ Ошибка авторизации: {response.status_code}")
        print(response.text)
        return None

def generate_report(cookies):
    """Генерация отчета за сегодня"""
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n📊 Генерация отчета за {today}...")
    
    response = requests.post(
        f"{BASE_URL}/api/reports/generate",
        json={
            "report_type": "day",
            "start_date": today,
            "end_date": today
        },
        cookies=cookies
    )
    
    if response.status_code == 200:
        result = response.json()
        print("✅ Отчет успешно сгенерирован!")
        print(f"📄 Результат: {json.dumps(result, indent=2, ensure_ascii=False)}")
        return result
    else:
        print(f"❌ Ошибка генерации отчета: {response.status_code}")
        print(response.text)
        return None

def check_service_status(cookies):
    """Проверка статуса сервиса"""
    print("\n🔍 Проверка статуса сервиса...")
    
    response = requests.get(
        f"{BASE_URL}/api/service/status",
        cookies=cookies
    )
    
    if response.status_code == 200:
        status = response.json()
        print(f"📊 Статус сервиса: {json.dumps(status, indent=2, ensure_ascii=False)}")
        return status
    else:
        print(f"❌ Ошибка получения статуса: {response.status_code}")
        return None

def main():
    print("=" * 60)
    print("ГЕНЕРАЦИЯ ОТЧЕТА ОТ ПОЛЬЗОВАТЕЛЯ ADMIN")
    print("=" * 60)
    
    # Авторизация
    cookies = login()
    if not cookies:
        return
    
    # Проверка статуса сервиса
    check_service_status(cookies)
    
    # Генерация отчета
    generate_report(cookies)
    
    print("\n" + "=" * 60)
    print("ГОТОВО!")
    print("=" * 60)

if __name__ == '__main__':
    main()
