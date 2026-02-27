#!/usr/bin/env python3
"""
Менеджер правил классификации и промптов
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

class ClassificationRulesManager:
    """Менеджер для управления правилами классификации и промптами"""
    
    def __init__(self, db_path='classification_rules.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных для правил"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица для системных промптов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )
        ''')
        
        # Таблица для правил классификации
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS classification_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id TEXT NOT NULL,
                category_name TEXT NOT NULL,
                rule_text TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                examples TEXT,
                conditions TEXT
            )
        ''')
        
        # Таблица для критических правил
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS critical_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                rule_text TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )
        ''')
        
        # Таблица для настроек системы
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT NOT NULL UNIQUE,
                setting_value TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица для истории запусков классификации
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS classification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL UNIQUE,
                input_folder TEXT NOT NULL,
                output_file TEXT NOT NULL,
                context_days INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'running',
                total_files INTEGER DEFAULT 0,
                processed_files INTEGER DEFAULT 0,
                corrections_count INTEGER DEFAULT 0,
                start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP,
                duration TEXT,
                error_message TEXT,
                operator_name TEXT
            )
        ''')
        
        # Таблица для расписаний автоматического запуска
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS classification_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                input_folder TEXT NOT NULL,
                context_days INTEGER DEFAULT 7,
                schedule_type TEXT NOT NULL DEFAULT 'daily',
                schedule_config TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                last_run TIMESTAMP,
                next_run TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT,
                run_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0
            )
        ''')

        # Значения по умолчанию для Telegram настроек (если не заданы)
        try:
            cursor.execute("INSERT OR IGNORE INTO system_settings (setting_key, setting_value, description) VALUES ('telegram_enabled', '0', 'Включить отправку отчетов в Telegram')")
            cursor.execute("INSERT OR IGNORE INTO system_settings (setting_key, setting_value, description) VALUES ('telegram_bot_token', '', 'Токен Telegram-бота')")
            cursor.execute("INSERT OR IGNORE INTO system_settings (setting_key, setting_value, description) VALUES ('telegram_chat_id', '', 'ID чата или канала для отправки')")
        except Exception:
            pass
        
        conn.commit()
        conn.close()
        
        # Загружаем стандартные правила при первом запуске
        self._load_default_rules()
    
    def _load_default_rules(self):
        """Загрузка стандартных правил при первом запуске"""
        # Проверяем, есть ли уже данные
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM system_prompts')
        if cursor.fetchone()[0] > 0:
            conn.close()
            return
        
        # Загружаем усиленный системный промпт с приоритетами.
        # ВНИМАНИЕ: теперь используется символьная схема категорий IN./OUT.*,
        # а числовые коды (1–26) остаются только для обратной совместимости.
        default_prompt = """Ты - опытный аналитик автосервиса с глубоким пониманием бизнес-процессов. Проанализируй транскрипцию звонка и определи его тип с учетом контекста предыдущих звонков клиента.

ВАЖНО: Соблюдай СТРОГИЙ ПОРЯДОК ПРИОРИТЕТОВ! Правила расположены в порядке убывания приоритета - проверяй их последовательно.

ФОРМАТ ОТВЕТА:
Ответь строго в формате: КОД|ОБОСНОВАНИЕ
Где КОД - один из символьных кодов категорий (IN.* или OUT.*), а ОБОСНОВАНИЕ - детальное объяснение выбора с учетом контекста.

ПРИМЕРЫ КОДОВ КАТЕГОРИЙ:
- IN.NE, OUT.NE               — нецелевой звонок
- IN.BOOK, OUT.BOOK           — новая запись
- IN.FU.BOOK, OUT.FU.BOOK     — последующий контакт с записью
- IN.INFO.FU.NOBOOK, OUT.INFO.FU.NOBOOK — справочный последующий контакт без записи
- IN.CONS.*, OUT.CONS.*       — различные типы консультаций (ПЕРЕШЛИ В МЕССЕНДЖЕР, ПЕРЕАДРЕСАЦИЯ, СВОИ ЗАПЧАСТИ, ПОДУМАЕТ/ОТКАЗ и т.д.)
- OUT.OBZ.BOOK, OUT.OBZ.NOBOOK — обзвон с записью / без записи

Точный перечень кодов и их назначение дан в разделе ПРАВИЛ КЛАССИФИКАЦИИ ({CATEGORY_RULES}).

КОНТЕКСТ ЗВОНКА:
- Тип звонка: {CALL_TYPE}
- История звонков клиента: {CALL_HISTORY}

ОБУЧАЮЩИЕ ПРИМЕРЫ (изучи их для улучшения точности):
{TRAINING_EXAMPLES}

ПРАВИЛА КЛАССИФИКАЦИИ (СТРОГО соблюдай порядок приоритетов):

{CATEGORY_RULES}

КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА (ОБЯЗАТЕЛЬНО к выполнению):
{CRITICAL_RULES}

АЛГОРИТМ КЛАССИФИКАЦИИ:
1. СНАЧАЛА определи тип звонка (Входящий/Исходящий).
2. Определи, целевой ли звонок (иномарка 2007+ г.в., автомобиль целиком).
3. Если звонок не целевой — используй коды IN.NE или OUT.NE.
4. Если звонок целевой — проверяй правила по порядку приоритета и выбирай подходящий символьный код (IN.* или OUT.*) с учетом направления звонка.
5. Для записей (IN.BOOK/OUT.BOOK/IN.FU.BOOK/OUT.FU.BOOK) ОБЯЗАТЕЛЬНО должна быть конкретная договоренность о визите (дата/время или явное \"приезжайте сейчас\").
6. Любые фразы сомнения (\"подумаю\", \"перезвоню\", \"если надумаю\") — это консультации (IN.CONS.THINK/OUT.CONS.THINK), а не запись.
7. Для последующих контактов по уже существующей записи используй коды IN.FU.BOOK/OUT.FU.BOOK или IN.INFO.FU.NOBOOK/OUT.INFO.FU.NOBOOK в зависимости от того, есть ли новая запись.
8. Учитывай историю звонков: первый звонок не может быть последующим контактом, а подтверждение существующей записи не является новой записью.

ПОМНИ: Приоритеты работают! Правила с высоким приоритетом проверяются первыми!"""
        
        cursor.execute('''
            INSERT INTO system_prompts (name, content, description)
            VALUES (?, ?, ?)
        ''', ('default_prompt', default_prompt, 'Основной промпт для классификации звонков'))
        
        # Загружаем стандартные правила классификации с усиленными критериями
        default_rules = [
            ("1", "НЕ ЦЕЛЕВОЙ", "СТРОГО НЕ ЦЕЛЕВОЙ: Отечественный авто (Lada, UAZ, ГАЗ, ВАЗ), авто 2006 г.в. или старше, запрос по отдельной снятой запчасти, не клиент (поставщик, реклама, банк, страховка), грузовик/спецтехника, тестовый звонок, звонок не по автомобилю. КРИТЕРИИ: Если НЕ иномарка 2007+ г.в. ИЛИ НЕ автомобиль целиком - ОБЯЗАТЕЛЬНО категория 1.", 15),
            ("2", "ЗАПИСЬ НА СЕРВИС", "СТРОГО ЗАПИСЬ: Целевой звонок (иномарка 2007+ г.в., автомобиль целиком) с КОНКРЕТНОЙ записью на время/дату. ОБЯЗАТЕЛЬНЫЕ КРИТЕРИИ: 1) Четкое время визита (дата + время), 2) НЕ фразы \"подумаю\", \"перезвоню\", \"найду решение\", 3) Конкретная договоренность о визите. КОНТЕКСТ: Первый контакт клиента или повторный после долгого перерыва. ИСКЛЮЧЕНИЯ: Если есть фразы сомнения - это категория 3.", 12),
            ("3", "КОНСУЛЬТАЦИЯ", "СТРОГО КОНСУЛЬТАЦИЯ: Целевой звонок, уточнение деталей для будущего визита (работы, цены, условия), но записи нет. ВКЛЮЧАЕТ: \"подумаю\", \"перезвоню\", \"уже нашел решение\", \"уточню детали\", \"сравню цены\", \"посмотрю варианты\". КОНТЕКСТ: Первый звонок по новой проблеме или уточнение деталей. ПРИОРИТЕТ: Если есть сомнения клиента - это категория 3, НЕ 2.", 11),
            ("4", "ПОДУМАЕТ/ОТКАЗ", "СТРОГО ОТКАЗ: Целевой звонок с прямым отказом или четкими фразами отказа: \"не буду\", \"не нужно\", \"отказываюсь\", \"не подходит\", \"не интересно\", \"не буду ремонтировать\". НЕ включает \"подумаю\" - это категория 3. КОНТЕКСТ: Учитывай предыдущие звонки - если был отказ, это может быть повторная попытка.", 10),
            ("5", "НЕТ ВРЕМЕНИ/ЗАНЯТО", "СТРОГО НЕТ ВРЕМЕНИ: Целевой звонок, но нет свободных окон в ближайшее время. КРИТЕРИИ: Конкретные фразы \"нет времени\", \"занято\", \"нет свободных окон\", \"очередь большая\", \"запись на месяц вперед\". КОНТЕКСТ: Учитывай загруженность сервиса и предыдущие записи клиента.", 9),
            ("6", "ВЫСОКАЯ СТОИМОСТЬ", "СТРОГО ДОРОГО: Целевой звонок, отказ исключительно из-за цены. КРИТЕРИИ: Четкие фразы \"дорого\", \"много денег\", \"не потяну\", \"слишком дорого\", \"не по карману\", \"ценник высокий\". КОНТЕКСТ: Сравни с предыдущими звонками по стоимости.", 8),
            ("7", "СВОИ ЗАПЧАСТИ", "СТРОГО СВОИ ЗАПЧАСТИ: Целевой звонок, клиент настаивает на своих запчастях или хочет ремонт с использованием своих деталей. КРИТЕРИИ: \"у меня есть запчасти\", \"привезу свои детали\", \"хочу со своими запчастями\", \"у меня уже куплено\".", 7),
            ("8", "НЕ ВЫПОЛНЯЕМ РАБОТЫ", "СТРОГО НЕ ВЫПОЛНЯЕМ: Целевой звонок, техническая невозможность выполнения. КРИТЕРИИ: \"не работаем с этой маркой\", \"нет специалиста\", \"нет оборудования\", \"не берем такие работы\", \"не наша специализация\".", 6),
            ("9", "ПЕРЕШЛИ В МЕССЕНДЖЕР", "СТРОГО МЕССЕНДЖЕР: Целевой звонок с договоренностью обсудить детали в мессенджере. КРИТЕРИИ: Конкретные фразы \"напишу в WhatsApp\", \"отправлю в Telegram\", \"свяжемся в мессенджере\", \"перейдем в чат\".", 5),
            ("10", "ЗАПЛАНИРОВАН ПЕРЕЗВОН", "СТРОГО ПЕРЕЗВОН: Целевой звонок с договоренностью созвониться позже в конкретное время. КРИТЕРИИ: Конкретное время перезвона \"перезвоню завтра\", \"созвонимся в пятницу\", \"перезвоню в 15:00\". КОНТЕКСТ: Проверь, состоялся ли обещанный перезвон.", 4),
            ("11", "ПЕРЕАДРЕСАЦИЯ", "СТРОГО ПЕРЕАДРЕСАЦИЯ: Целевой звонок с перенаправлением в другой филиал/сервис по географическому принципу. КРИТЕРИИ: \"обратитесь в другой филиал\", \"мы не работаем в вашем районе\", \"ближе к вам другой сервис\".", 3),
            ("12", "ОБЗВОН", "СТРОГО ОБЗВОН: Исходящий звонок ОТ СЕРВИСА клиенту с предложением услуг, акций, планового ТО, напоминаний о записи. КРИТЕРИИ: Звонок ИНИЦИИРОВАН сервисом, предложение услуг, напоминание о ТО, акции.", 2),
            ("13", "ПОСЛЕДУЮЩИЙ КОНТАКТ", "СТРОГО ПОСЛЕДУЮЩИЙ: Звонок по УЖЕ СУЩЕСТВУЮЩЕЙ записи или автомобилю в ремонте. КРИТЕРИИ: ОБЯЗАТЕЛЬНО проверь историю - должен быть предыдущий звонок с записью (категория 2) или уже существующий автомобиль в сервисе. ВКЛЮЧАЕТ: подтверждение записи, уточнение времени записи, перенос времени записи, статус ремонта. ЗАПРЕТ: НИКОГДА не классифицируй первый звонок клиента как \"Последующий контакт\"!", 1),
            ("14", "ДРУГОЕ", "СТРОГО ДРУГОЕ: Иные причины нецелевого звонка, которые не подходят под другие категории. КРИТЕРИИ: Неопределенные случаи, технические проблемы, неясные ситуации.", 0)
        ]
        
        for category_id, category_name, rule_text, priority in default_rules:
            cursor.execute('''
                INSERT INTO classification_rules (category_id, category_name, rule_text, priority)
                VALUES (?, ?, ?, ?)
            ''', (category_id, category_name, rule_text, priority))
        
        # Загружаем критические правила с усиленными критериями
        critical_rules = [
            ("СТРОГО: Первый звонок клиента", "КРИТИЧЕСКОЕ ПРАВИЛО: Если это ПЕРВЫЙ звонок клиента - НЕЛЬЗЯ классифицировать как \"Последующий контакт\" (13). ОБЯЗАТЕЛЬНО проверь историю звонков клиента перед классификацией категории 13.", "Защита от неправильной классификации первого звонка"),
            ("СТРОГО: Последующий контакт", "КРИТИЧЕСКОЕ ПРАВИЛО: \"Последующий контакт\" (13) ТОЛЬКО если есть предыдущая запись (категория 2) или автомобиль уже в сервисе. БЕЗ предыдущей записи - это категория 3.", "Проверка наличия предыдущих записей"),
            ("СТРОГО: Подтверждение записи", "КРИТИЧЕСКОЕ ПРАВИЛО: \"Подтверждение записи\" = ПОСЛЕДУЮЩИЙ КОНТАКТ (13), НЕ запись на сервис (2). Если клиент подтверждает уже существующую запись - это категория 13.", "Различение подтверждения и новой записи"),
            ("СТРОГО: Уточнение времени", "КРИТИЧЕСКОЕ ПРАВИЛО: \"Уточнение времени записи\" = ПОСЛЕДУЮЩИЙ КОНТАКТ (13). Если клиент уточняет время уже существующей записи - это категория 13.", "Уточнение времени - это не новая запись"),
            ("СТРОГО: Подумаю/перезвоню", "КРИТИЧЕСКОЕ ПРАВИЛО: \"Подумаю\", \"перезвоню\", \"найду решение\" = КОНСУЛЬТАЦИЯ (3), НЕ запись на сервис (2). Любые фразы сомнения - это категория 3.", "Различение размышлений и записи"),
            ("СТРОГО: Уже нашел решение", "КРИТИЧЕСКОЕ ПРАВИЛО: \"Уже нашел решение\", \"уже решил проблему\" = КОНСУЛЬТАЦИЯ (3). Клиент уже решил проблему самостоятельно.", "Клиент уже решил проблему самостоятельно"),
            ("СТРОГО: Временные интервалы", "КРИТИЧЕСКОЕ ПРАВИЛО: Учитывай временные интервалы между звонками. Если прошло много времени с последнего звонка - это может быть новый контакт.", "Анализ временных промежутков"),
            ("СТРОГО: Последовательность", "КРИТИЧЕСКОЕ ПРАВИЛО: Анализируй последовательность: Запись (2) → Последующий контакт (13). Без записи не может быть последующего контакта.", "Логическая последовательность звонков"),
            ("СТРОГО: Целевой звонок", "КРИТИЧЕСКОЕ ПРАВИЛО: Сначала определи целевой ли звонок (иномарка 2007+ г.в., автомобиль целиком). Если НЕ целевой - категория 1.", "Определение целевого звонка"),
            ("СТРОГО: Конкретная запись", "КРИТИЧЕСКОЕ ПРАВИЛО: Для категории 2 (Запись на сервис) ОБЯЗАТЕЛЬНО должно быть конкретное время визита или в словах присудствуют приезжайте сейчас, или скоро буду и подобные. Без конкретного времени - это категория 3.", "Критерии записи на сервис"),
            ("СТРОГО: Отказ vs Сомнение", "КРИТИЧЕСКОЕ ПРАВИЛО: Четко различай отказ (категория 4) и сомнение (категория 3). \"Не буду\" = отказ, \"подумаю\" = сомнение.", "Различение отказа и сомнения"),
            ("СТРОГО: Приоритет правил", "КРИТИЧЕСКОЕ ПРАВИЛО: Соблюдай приоритет правил. Правила с высоким приоритетом проверяются первыми. Нецелевые звонки (категория 1) имеют наивысший приоритет.", "Соблюдение приоритетов")
        ]
        
        for name, rule_text, description in critical_rules:
            cursor.execute('''
                INSERT INTO critical_rules (name, rule_text, description)
                VALUES (?, ?, ?)
            ''', (name, rule_text, description))
        
        conn.commit()
        conn.close()
    
    # Методы для работы с системными промптами
    def get_system_prompts(self) -> List[Dict]:
        """Получить все системные промпты"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM system_prompts ORDER BY created_at DESC')
        prompts = []
        for row in cursor.fetchall():
            prompts.append({
                'id': row[0],
                'name': row[1],
                'content': row[2],
                'is_active': bool(row[3]),
                'created_at': row[4],
                'updated_at': row[5],
                'description': row[6]
            })
        conn.close()
        return prompts
    
    def get_active_system_prompt(self) -> Optional[Dict]:
        """Получить активный системный промпт"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM system_prompts WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1')
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row[0],
                'name': row[1],
                'content': row[2],
                'is_active': bool(row[3]),
                'created_at': row[4],
                'updated_at': row[5],
                'description': row[6]
            }
        return None
    
    def add_system_prompt(self, name: str, content: str, description: str = "") -> bool:
        """Добавить новый системный промпт"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO system_prompts (name, content, description)
                VALUES (?, ?, ?)
            ''', (name, content, description))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка добавления промпта: {e}")
            return False
    
    def update_system_prompt(self, prompt_id: int, name: str, content: str, description: str = "") -> bool:
        """Обновить системный промпт"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE system_prompts 
                SET name = ?, content = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (name, content, description, prompt_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка обновления промпта: {e}")
            return False
    
    def toggle_system_prompt_active(self, prompt_id: int) -> bool:
        """Переключить активность промпта"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Сначала деактивируем все промпты
            cursor.execute('UPDATE system_prompts SET is_active = 0')
            
            # Затем активируем выбранный
            cursor.execute('UPDATE system_prompts SET is_active = 1 WHERE id = ?', (prompt_id,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка переключения промпта: {e}")
            return False
    
    def delete_system_prompt(self, prompt_id: int) -> bool:
        """Удалить системный промпт"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM system_prompts WHERE id = ?', (prompt_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка удаления промпта: {e}")
            return False
    
    # Методы для работы с правилами классификации
    def get_classification_rules(self) -> List[Dict]:
        """Получить все правила классификации"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM classification_rules ORDER BY priority DESC, category_id')
        rules = []
        for row in cursor.fetchall():
            rules.append({
                'id': row[0],
                'category_id': row[1],
                'category_name': row[2],
                'rule_text': row[3],
                'priority': row[4],
                'is_active': bool(row[5]),
                'created_at': row[6],
                'updated_at': row[7],
                'examples': row[8],
                'conditions': row[9]
            })
        conn.close()
        return rules
    
    def get_active_classification_rules(self) -> List[Dict]:
        """Получить активные правила классификации"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM classification_rules WHERE is_active = 1 ORDER BY priority DESC, category_id')
        rules = []
        for row in cursor.fetchall():
            rules.append({
                'id': row[0],
                'category_id': row[1],
                'category_name': row[2],
                'rule_text': row[3],
                'priority': row[4],
                'is_active': bool(row[5]),
                'created_at': row[6],
                'updated_at': row[7],
                'examples': row[8],
                'conditions': row[9]
            })
        conn.close()
        return rules
    
    def add_classification_rule(self, category_id: str, category_name: str, rule_text: str, 
                              priority: int = 0, examples: str = "", conditions: str = "") -> bool:
        """Добавить новое правило классификации"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO classification_rules (category_id, category_name, rule_text, priority, examples, conditions)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (category_id, category_name, rule_text, priority, examples, conditions))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка добавления правила: {e}")
            return False
    
    def update_classification_rule(self, rule_id: int, category_id: str, category_name: str, 
                                 rule_text: str, priority: int = 0, examples: str = "", conditions: str = "") -> bool:
        """Обновить правило классификации"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE classification_rules 
                SET category_id = ?, category_name = ?, rule_text = ?, priority = ?, 
                    examples = ?, conditions = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (category_id, category_name, rule_text, priority, examples, conditions, rule_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка обновления правила: {e}")
            return False
    
    def toggle_classification_rule_active(self, rule_id: int) -> bool:
        """Переключить активность правила классификации"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE classification_rules 
                SET is_active = NOT is_active, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (rule_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка переключения правила: {e}")
            return False
    
    def delete_classification_rule(self, rule_id: int) -> bool:
        """Удалить правило классификации"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM classification_rules WHERE id = ?', (rule_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка удаления правила: {e}")
            return False
    
    # Методы для работы с критическими правилами
    def get_critical_rules(self) -> List[Dict]:
        """Получить все критические правила"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM critical_rules ORDER BY created_at DESC')
        rules = []
        for row in cursor.fetchall():
            rules.append({
                'id': row[0],
                'name': row[1],
                'rule_text': row[2],
                'is_active': bool(row[3]),
                'created_at': row[4],
                'updated_at': row[5],
                'description': row[6]
            })
        conn.close()
        return rules
    
    def get_active_critical_rules(self) -> List[Dict]:
        """Получить активные критические правила"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM critical_rules WHERE is_active = 1 ORDER BY created_at DESC')
        rules = []
        for row in cursor.fetchall():
            rules.append({
                'id': row[0],
                'name': row[1],
                'rule_text': row[2],
                'is_active': bool(row[3]),
                'created_at': row[4],
                'updated_at': row[5],
                'description': row[6]
            })
        conn.close()
        return rules
    
    def add_critical_rule(self, name: str, rule_text: str, description: str = "") -> bool:
        """Добавить новое критическое правило"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO critical_rules (name, rule_text, description)
                VALUES (?, ?, ?)
            ''', (name, rule_text, description))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка добавления критического правила: {e}")
            return False
    
    def update_critical_rule(self, rule_id: int, name: str, rule_text: str, description: str = "") -> bool:
        """Обновить критическое правило"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE critical_rules 
                SET name = ?, rule_text = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (name, rule_text, description, rule_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка обновления критического правила: {e}")
            return False
    
    def toggle_critical_rule_active(self, rule_id: int) -> bool:
        """Переключить активность критического правила"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE critical_rules 
                SET is_active = NOT is_active, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (rule_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка переключения критического правила: {e}")
            return False
    
    def delete_critical_rule(self, rule_id: int) -> bool:
        """Удалить критическое правило"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM critical_rules WHERE id = ?', (rule_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка удаления критического правила: {e}")
            return False
    
    def get_auto_extracted_rules(self) -> List[Dict]:
        """Получить активные автоматически извлеченные правила"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, rule_text, category_id, confidence, source_type, example_count
            FROM auto_extracted_rules
            WHERE is_active = 1
            ORDER BY confidence DESC, example_count DESC
        ''')
        
        rules = []
        for row in cursor.fetchall():
            rules.append({
                'id': row[0],
                'rule_text': row[1],
                'category_id': row[2],
                'confidence': row[3],
                'source_type': row[4],
                'example_count': row[5]
            })
        
        conn.close()
        return rules
    
    def generate_system_prompt(self, call_history: str = "", training_examples: str = "", call_type: str = "Не определен") -> str:
        """Генерация системного промпта с актуальными правилами"""
        active_prompt = self.get_active_system_prompt()
        if not active_prompt:
            return "Ошибка: нет активного системного промпта"
        
        # Получаем активные правила
        classification_rules = self.get_active_classification_rules()
        critical_rules = self.get_active_critical_rules()
        auto_extracted_rules = self.get_auto_extracted_rules()
        
        # Формируем текст правил классификации
        category_rules_text = ""
        for rule in classification_rules:
            category_rules_text += f"{rule['category_id']}. {rule['category_name']}: {rule['rule_text']}\n"
            if rule['examples']:
                category_rules_text += f"   Примеры: {rule['examples']}\n"
            if rule['conditions']:
                category_rules_text += f"   Условия: {rule['conditions']}\n"
            category_rules_text += "\n"
        
        # Формируем текст автоматически извлеченных правил
        auto_rules_text = ""
        if auto_extracted_rules:
            auto_rules_text = "АВТОМАТИЧЕСКИ ИЗВЛЕЧЁННЫЕ ПРАВИЛА (на основе частых ошибок):\n"
            for rule in auto_extracted_rules:
                confidence_stars = "⚠️" if rule['confidence'] >= 0.8 else "ℹ️"
                auto_rules_text += f"{confidence_stars} {rule['rule_text']} "
                auto_rules_text += f"(уверенность: {rule['confidence']:.0%}, примеров: {rule['example_count']})\n"
            auto_rules_text += "\n"
        
        # Формируем текст критических правил
        critical_rules_text = ""
        for rule in critical_rules:
            critical_rules_text += f"- {rule['rule_text']}\n"
        
        # Заменяем плейсхолдеры в промпте
        prompt_content = active_prompt['content']
        prompt_content = prompt_content.replace('{CALL_TYPE}', call_type)
        prompt_content = prompt_content.replace('{CALL_HISTORY}', call_history or 'Нет истории звонков')
        prompt_content = prompt_content.replace('{TRAINING_EXAMPLES}', training_examples or 'Нет обучающих примеров')
        prompt_content = prompt_content.replace('{CATEGORY_RULES}', category_rules_text)
        
        # Добавляем автоправила перед критическими правилами
        if auto_rules_text and '{AUTO_RULES}' not in prompt_content:
            # Если нет специального плейсхолдера, вставляем перед критическими правилами
            if '{CRITICAL_RULES}' in prompt_content:
                prompt_content = prompt_content.replace('{CRITICAL_RULES}', auto_rules_text + '{CRITICAL_RULES}')
            else:
                # Если нет плейсхолдера критических правил, добавляем перед ними
                prompt_content += "\n\n" + auto_rules_text
        elif '{AUTO_RULES}' in prompt_content:
            prompt_content = prompt_content.replace('{AUTO_RULES}', auto_rules_text)
        
        prompt_content = prompt_content.replace('{CRITICAL_RULES}', critical_rules_text)
        
        return prompt_content
    
    def get_setting(self, key, default_value=None):
        """Получить значение настройки"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT setting_value FROM system_settings WHERE setting_key = ?', (key,))
        result = cursor.fetchone()
        
        conn.close()
        
        return result[0] if result else default_value
    
    def set_setting(self, key, value, description=None):
        """Установить значение настройки"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO system_settings (setting_key, setting_value, description, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (key, value, description))
        
        conn.commit()
        conn.close()
    
    def get_all_settings(self):
        """Получить все настройки"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT setting_key, setting_value, description FROM system_settings ORDER BY setting_key')
        results = cursor.fetchall()
        
        conn.close()
        
        return [{'key': row[0], 'value': row[1], 'description': row[2]} for row in results]
    
    def add_classification_task(self, task_id, input_folder, output_file, context_days=0, operator_name=None):
        """Добавить задачу классификации в историю"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO classification_history 
            (task_id, input_folder, output_file, context_days, operator_name)
            VALUES (?, ?, ?, ?, ?)
        ''', (task_id, input_folder, output_file, context_days, operator_name))
        
        conn.commit()
        conn.close()
    
    def update_classification_task(self, task_id, **kwargs):
        """Обновить задачу классификации"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Формируем динамический запрос
        set_clauses = []
        values = []
        
        for key, value in kwargs.items():
            if key in ['status', 'total_files', 'processed_files', 'corrections_count', 
                      'duration', 'error_message', 'end_time']:
                set_clauses.append(f"{key} = ?")
                values.append(value)
        
        if set_clauses:
            values.append(task_id)
            query = f"UPDATE classification_history SET {', '.join(set_clauses)} WHERE task_id = ?"
            cursor.execute(query, values)
        
        conn.commit()
        conn.close()
    
    def get_classification_history(self, limit=10):
        """Получить историю запусков классификации"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT task_id, input_folder, output_file, context_days, status,
                   total_files, processed_files, corrections_count,
                   start_time, end_time, duration, error_message, operator_name
            FROM classification_history
            ORDER BY start_time DESC
            LIMIT ?
        ''', (limit,))
        
        results = cursor.fetchall()
        conn.close()
        
        history = []
        for row in results:
            history.append({
                'task_id': row[0],
                'input_folder': row[1],
                'output_file': row[2],
                'context_days': row[3],
                'status': row[4],
                'total_files': row[5],
                'processed_files': row[6],
                'corrections_count': row[7],
                'start_time': row[8],
                'end_time': row[9],
                'duration': row[10],
                'error_message': row[11],
                'operator_name': row[12]
            })
        
        return history
    
    def get_classification_task(self, task_id):
        """Получить информацию о конкретной задаче"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT task_id, input_folder, output_file, context_days, status,
                   total_files, processed_files, corrections_count,
                   start_time, end_time, duration, error_message, operator_name
            FROM classification_history
            WHERE task_id = ?
        ''', (task_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'task_id': result[0],
                'input_folder': result[1],
                'output_file': result[2],
                'context_days': result[3],
                'status': result[4],
                'total_files': result[5],
                'processed_files': result[6],
                'corrections_count': result[7],
                'start_time': result[8],
                'end_time': result[9],
                'duration': result[10],
                'error_message': result[11],
                'operator_name': result[12]
            }
        return None
    
    def add_schedule(self, name, description, input_folder, context_days, schedule_type, schedule_config, created_by=None):
        """Добавить расписание автоматического запуска"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Вычисляем время следующего запуска
        next_run = self._calculate_next_run(schedule_type, schedule_config)
        
        cursor.execute('''
            INSERT INTO classification_schedules 
            (name, description, input_folder, context_days, schedule_type, schedule_config, created_by, next_run)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, description, input_folder, context_days, schedule_type, schedule_config, created_by, next_run))
        
        conn.commit()
        conn.close()
        
        return cursor.lastrowid
    
    def update_schedule(self, schedule_id, **kwargs):
        """Обновить расписание"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Формируем динамический запрос
        set_clauses = []
        values = []
        
        allowed_fields = ['name', 'description', 'input_folder', 'context_days', 
                         'schedule_type', 'schedule_config', 'is_active', 'next_run']
        
        for key, value in kwargs.items():
            if key in allowed_fields:
                set_clauses.append(f"{key} = ?")
                values.append(value)
        
        if set_clauses:
            values.append(schedule_id)
            query = f"UPDATE classification_schedules SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
            cursor.execute(query, values)
        
        conn.commit()
        conn.close()
    
    def get_schedules(self, active_only=True):
        """Получить список расписаний"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = '''
            SELECT id, name, description, input_folder, context_days, schedule_type, 
                   schedule_config, is_active, last_run, next_run, created_at, 
                   created_by, run_count, success_count, error_count
            FROM classification_schedules
        '''
        
        if active_only:
            query += ' WHERE is_active = 1'
        
        query += ' ORDER BY next_run ASC'
        
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        
        schedules = []
        for row in results:
            schedules.append({
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'input_folder': row[3],
                'context_days': row[4],
                'schedule_type': row[5],
                'schedule_config': row[6],
                'is_active': bool(row[7]),
                'last_run': row[8],
                'next_run': row[9],
                'created_at': row[10],
                'created_by': row[11],
                'run_count': row[12],
                'success_count': row[13],
                'error_count': row[14]
            })
        
        return schedules
    
    def get_schedule(self, schedule_id):
        """Получить конкретное расписание"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, name, description, input_folder, context_days, schedule_type, 
                   schedule_config, is_active, last_run, next_run, created_at, 
                   created_by, run_count, success_count, error_count
            FROM classification_schedules
            WHERE id = ?
        ''', (schedule_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'id': result[0],
                'name': result[1],
                'description': result[2],
                'input_folder': result[3],
                'context_days': result[4],
                'schedule_type': result[5],
                'schedule_config': result[6],
                'is_active': bool(result[7]),
                'last_run': result[8],
                'next_run': result[9],
                'created_at': result[10],
                'created_by': result[11],
                'run_count': result[12],
                'success_count': result[13],
                'error_count': result[14]
            }
        return None
    
    def delete_schedule(self, schedule_id):
        """Удалить расписание"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM classification_schedules WHERE id = ?', (schedule_id,))
        
        conn.commit()
        conn.close()
    
    def update_schedule_run_stats(self, schedule_id, success=True):
        """Обновить статистику запусков расписания"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if success:
            cursor.execute('''
                UPDATE classification_schedules 
                SET run_count = run_count + 1, success_count = success_count + 1, 
                    last_run = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (schedule_id,))
        else:
            cursor.execute('''
                UPDATE classification_schedules 
                SET run_count = run_count + 1, error_count = error_count + 1, 
                    last_run = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (schedule_id,))
        
        conn.commit()
        conn.close()
    
    def get_due_schedules(self):
        """Получить расписания, которые должны быть выполнены"""
        from datetime import datetime
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Используем локальное время вместо UTC
        current_time = datetime.now().isoformat()
        
        cursor.execute('''
            SELECT id, name, input_folder, context_days, schedule_type, schedule_config, next_run
            FROM classification_schedules
            WHERE is_active = 1 AND next_run <= ?
            ORDER BY next_run ASC
        ''', (current_time,))
        
        results = cursor.fetchall()
        conn.close()
        
        schedules = []
        for row in results:
            schedules.append({
                'id': row[0],
                'name': row[1],
                'input_folder': row[2],
                'context_days': row[3],
                'schedule_type': row[4],
                'schedule_config': row[5],
                'next_run': row[6]
            })
        
        return schedules
    
    def update_next_run(self, schedule_id):
        """Обновить время следующего запуска"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Получаем конфигурацию расписания
        cursor.execute('SELECT schedule_type, schedule_config FROM classification_schedules WHERE id = ?', (schedule_id,))
        result = cursor.fetchone()
        
        if result:
            schedule_type, schedule_config = result
            next_run = self._calculate_next_run(schedule_type, schedule_config)
            
            cursor.execute('''
                UPDATE classification_schedules 
                SET next_run = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (next_run, schedule_id))
        
        conn.commit()
        conn.close()
    
    def _calculate_next_run(self, schedule_type, schedule_config):
        """Вычислить время следующего запуска"""
        import json
        from datetime import datetime, timedelta
        
        try:
            config = json.loads(schedule_config)
        except:
            config = {}
        
        now = datetime.now()
        
        if schedule_type == 'daily':
            # Ежедневно в определенное время
            hour = config.get('hour', 9)
            minute = config.get('minute', 0)
            
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            
        elif schedule_type == 'weekly':
            # Еженедельно в определенные дни
            days = config.get('days', [1])  # 1 = понедельник
            hour = config.get('hour', 9)
            minute = config.get('minute', 0)
            
            # Находим ближайший день недели
            current_weekday = now.weekday() + 1  # Понедельник = 1
            next_weekday = None
            
            for day in sorted(days):
                if day > current_weekday:
                    next_weekday = day
                    break
            
            if next_weekday is None:
                next_weekday = min(days)
                days_ahead = 7 - current_weekday + next_weekday
            else:
                days_ahead = next_weekday - current_weekday
            
            next_run = now + timedelta(days=days_ahead)
            next_run = next_run.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
        elif schedule_type == 'monthly':
            # Ежемесячно в определенный день
            day = config.get('day', 1)
            hour = config.get('hour', 9)
            minute = config.get('minute', 0)
            
            if now.day < day:
                next_run = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
            else:
                # Следующий месяц
                if now.month == 12:
                    next_run = now.replace(year=now.year + 1, month=1, day=day, hour=hour, minute=minute, second=0, microsecond=0)
                else:
                    next_run = now.replace(month=now.month + 1, day=day, hour=hour, minute=minute, second=0, microsecond=0)
        
        else:
            # По умолчанию - завтра в 9:00
            next_run = now + timedelta(days=1)
            next_run = next_run.replace(hour=9, minute=0, second=0, microsecond=0)
        
        return next_run.isoformat()
