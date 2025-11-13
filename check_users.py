#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки пользователей в базе данных
"""

from sqlalchemy import create_engine, text
from config.settings import get_config

def main():
    uri = get_config().SQLALCHEMY_DATABASE_URI
    engine = create_engine(uri)
    
    print("\n=== ПРОВЕРКА ПОЛЬЗОВАТЕЛЕЙ В БД ===\n")
    
    # Проверяем пользователей
    sql = text("""
        SELECT u.id, u.username, u.is_active, us.data
        FROM users u
        LEFT JOIN user_settings us ON us.user_id = u.id
        ORDER BY u.id
    """)
    
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
        
        if not rows:
            print("❌ Пользователи не найдены в базе данных!")
            return
        
        print(f"Найдено пользователей: {len(rows)}\n")
        
        for row in rows:
            status = "✅ АКТИВЕН" if row.is_active else "❌ НЕАКТИВЕН"
            has_settings = "✅ Есть" if row.data else "❌ Нет"
            
            print(f"ID: {row.id}")
            print(f"  Имя: {row.username or '(не указано)'}")
            print(f"  Статус: {status}")
            print(f"  Настройки: {has_settings}")
            
            # Если есть настройки, показываем путь к звонкам
            if row.data:
                import json
                try:
                    data = json.loads(row.data) if isinstance(row.data, str) else row.data
                    if isinstance(data, dict):
                        config = data.get('config', {})
                        paths = config.get('paths', {})
                        base_path = paths.get('base_records_path', 'НЕ УКАЗАН')
                        print(f"  Путь к звонкам: {base_path}")
                except:
                    print(f"  Путь к звонкам: ОШИБКА ЧТЕНИЯ")
            
            print()

if __name__ == '__main__':
    main()
