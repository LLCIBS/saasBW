"""
Система управления обучающими примерами для классификации звонков
"""

import sqlite3
import json
import hashlib
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import os


class TrainingExamplesManager:
    """Менеджер обучающих примеров для улучшения классификации"""
    
    def __init__(self, db_path: str = "training_examples.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных для хранения примеров"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица обучающих примеров
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS training_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcription_hash TEXT UNIQUE NOT NULL,
                transcription TEXT NOT NULL,
                correct_category TEXT NOT NULL,
                correct_reasoning TEXT NOT NULL,
                original_category TEXT,
                original_reasoning TEXT,
                operator_comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        
        # Таблица метрик качества классификации
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS classification_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                total_calls INTEGER DEFAULT 0,
                correct_classifications INTEGER DEFAULT 0,
                corrections_made INTEGER DEFAULT 0,
                accuracy_rate REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица истории корректировок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS correction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT,
                call_date TEXT,
                call_time TEXT,
                station TEXT,
                original_category TEXT NOT NULL,
                corrected_category TEXT NOT NULL,
                original_reasoning TEXT,
                corrected_reasoning TEXT,
                operator_name TEXT,
                correction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_training_example(self, transcription: str, correct_category: str, 
                           correct_reasoning: str, original_category: str = None,
                           original_reasoning: str = None, operator_comment: str = None) -> bool:
        """Добавление нового обучающего примера"""
        try:
            # Создаем хеш транскрипции для уникальности
            transcription_hash = hashlib.md5(transcription.encode('utf-8')).hexdigest()
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Проверяем, существует ли уже такой пример
            cursor.execute('SELECT id FROM training_examples WHERE transcription_hash = ?', 
                         (transcription_hash,))
            existing = cursor.fetchone()
            
            if existing:
                # Обновляем существующий пример
                cursor.execute('''
                    UPDATE training_examples 
                    SET correct_category = ?, correct_reasoning = ?, 
                        original_category = ?, original_reasoning = ?,
                        operator_comment = ?, created_at = CURRENT_TIMESTAMP
                    WHERE transcription_hash = ?
                ''', (correct_category, correct_reasoning, original_category, 
                      original_reasoning, operator_comment, transcription_hash))
            else:
                # Добавляем новый пример
                cursor.execute('''
                    INSERT INTO training_examples 
                    (transcription_hash, transcription, correct_category, correct_reasoning,
                     original_category, original_reasoning, operator_comment)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (transcription_hash, transcription, correct_category, correct_reasoning,
                      original_category, original_reasoning, operator_comment))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"Ошибка при добавлении обучающего примера: {e}")
            return False
    
    def get_training_examples(self, category: str = None, limit: int = 10) -> List[Dict]:
        """Получение обучающих примеров для указанной категории"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if category:
            cursor.execute('''
                SELECT transcription, correct_category, correct_reasoning, used_count
                FROM training_examples 
                WHERE correct_category = ? AND is_active = 1
                ORDER BY used_count ASC, created_at DESC
                LIMIT ?
            ''', (category, limit))
        else:
            cursor.execute('''
                SELECT transcription, correct_category, correct_reasoning, used_count
                FROM training_examples 
                WHERE is_active = 1
                ORDER BY used_count ASC, created_at DESC
                LIMIT ?
            ''', (limit,))
        
        examples = []
        for row in cursor.fetchall():
            examples.append({
                'transcription': row[0],
                'category': row[1],
                'reasoning': row[2],
                'used_count': row[3]
            })
        
        # Обновляем счетчик использования
        if examples:
            transcriptions = [ex['transcription'] for ex in examples]
            placeholders = ','.join(['?' for _ in transcriptions])
            cursor.execute(f'''
                UPDATE training_examples 
                SET used_count = used_count + 1
                WHERE transcription IN ({placeholders})
            ''', transcriptions)
            conn.commit()
        
        conn.close()
        return examples
    
    def get_similar_examples(self, transcription: str, limit: int = 3) -> List[Dict]:
        """Получение похожих примеров на основе ключевых слов"""
        # Простая реализация поиска по ключевым словам
        keywords = self._extract_keywords(transcription)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Ищем примеры, содержащие хотя бы одно ключевое слово
        examples = []
        for keyword in keywords[:5]:  # Берем первые 5 ключевых слов
            cursor.execute('''
                SELECT transcription, correct_category, correct_reasoning
                FROM training_examples 
                WHERE transcription LIKE ? AND is_active = 1
                LIMIT ?
            ''', (f'%{keyword}%', limit))
            
            for row in cursor.fetchall():
                if len(examples) < limit:
                    example = {
                        'transcription': row[0],
                        'category': row[1],
                        'reasoning': row[2]
                    }
                    if example not in examples:
                        examples.append(example)
        
        conn.close()
        return examples
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Извлечение ключевых слов из текста"""
        # Список важных слов для классификации
        important_words = [
            'запись', 'записать', 'записывайте', 'согласен', 'подходит',
            'отказ', 'не нужно', 'не интересно', 'подумаю', 'перезвоню',
            'дорого', 'не по карману', 'занято', 'нет времени', 'не выполняем',
            'свои запчасти', 'мессенджер', 'whatsapp', 'telegram',
            'обзвон', 'акция', 'предложение', 'то', 'техобслуживание',
            'переадресация', 'другой сервис', 'другой адрес'
        ]
        
        text_lower = text.lower()
        found_keywords = []
        
        for word in important_words:
            if word in text_lower:
                found_keywords.append(word)
        
        return found_keywords
    
    def add_correction(self, phone_number: str, call_date: str, call_time: str,
                      station: str, original_category: str, corrected_category: str,
                      original_reasoning: str, corrected_reasoning: str,
                      operator_name: str = None) -> bool:
        """Добавление записи о корректировке"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO correction_history 
                (phone_number, call_date, call_time, station, original_category,
                 corrected_category, original_reasoning, corrected_reasoning, operator_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (phone_number, call_date, call_time, station, original_category,
                  corrected_category, original_reasoning, corrected_reasoning, operator_name))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"Ошибка при добавлении корректировки: {e}")
            return False
    
    def update_daily_metrics(self, date: str, total_calls: int, 
                           correct_classifications: int, corrections_made: int):
        """Обновление ежедневных метрик"""
        accuracy_rate = (correct_classifications / total_calls * 100) if total_calls > 0 else 0
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Проверяем, есть ли уже запись за эту дату
        cursor.execute('SELECT id FROM classification_metrics WHERE date = ?', (date,))
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute('''
                UPDATE classification_metrics 
                SET total_calls = ?, correct_classifications = ?, 
                    corrections_made = ?, accuracy_rate = ?
                WHERE date = ?
            ''', (total_calls, correct_classifications, corrections_made, accuracy_rate, date))
        else:
            cursor.execute('''
                INSERT INTO classification_metrics 
                (date, total_calls, correct_classifications, corrections_made, accuracy_rate)
                VALUES (?, ?, ?, ?, ?)
            ''', (date, total_calls, correct_classifications, corrections_made, accuracy_rate))
        
        conn.commit()
        conn.close()
    
    def get_metrics_summary(self, days: int = 30) -> Dict:
        """Получение сводки метрик за указанное количество дней"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Общие метрики
        cursor.execute('''
            SELECT 
                COUNT(*) as total_examples,
                AVG(used_count) as avg_usage
            FROM training_examples 
            WHERE is_active = 1
        ''')
        training_stats = cursor.fetchone()
        
        # Метрики классификации за период
        cursor.execute('''
            SELECT 
                SUM(total_calls) as total_calls,
                SUM(correct_classifications) as correct_classifications,
                SUM(corrections_made) as corrections_made,
                AVG(accuracy_rate) as avg_accuracy
            FROM classification_metrics 
            WHERE date >= date('now', '-{} days')
        '''.format(days))
        classification_stats = cursor.fetchone()
        
        # Топ ошибок по категориям
        cursor.execute('''
            SELECT 
                original_category,
                corrected_category,
                COUNT(*) as count
            FROM correction_history 
            WHERE correction_date >= datetime('now', '-{} days')
            GROUP BY original_category, corrected_category
            ORDER BY count DESC
            LIMIT 10
        '''.format(days))
        top_errors = cursor.fetchall()
        
        conn.close()
        
        return {
            'training_examples': training_stats[0] if training_stats[0] else 0,
            'avg_example_usage': round(training_stats[1] or 0, 2),
            'total_calls': classification_stats[0] or 0,
            'correct_classifications': classification_stats[1] or 0,
            'corrections_made': classification_stats[2] or 0,
            'accuracy_rate': round(classification_stats[3] or 0, 2),
            'top_errors': [
                {
                    'original': error[0],
                    'corrected': error[1],
                    'count': error[2]
                }
                for error in top_errors
            ]
        }
    
    def get_all_examples(self) -> List[Dict]:
        """Получение всех обучающих примеров для управления"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, transcription, correct_category, correct_reasoning,
                   original_category, original_reasoning, operator_comment,
                   created_at, used_count, is_active
            FROM training_examples 
            ORDER BY created_at DESC
        ''')
        
        examples = []
        for row in cursor.fetchall():
            examples.append({
                'id': row[0],
                'transcription': row[1],
                'correct_category': row[2],
                'correct_reasoning': row[3],
                'original_category': row[4],
                'original_reasoning': row[5],
                'operator_comment': row[6],
                'created_at': row[7],
                'used_count': row[8],
                'is_active': bool(row[9])
            })
        
        conn.close()
        return examples
    
    def toggle_example_status(self, example_id: int) -> bool:
        """Переключение статуса активности примера"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE training_examples 
                SET is_active = NOT is_active
                WHERE id = ?
            ''', (example_id,))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"Ошибка при изменении статуса примера: {e}")
            return False
    
    def delete_example(self, example_id: int) -> bool:
        """Удаление обучающего примера"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM training_examples WHERE id = ?', (example_id,))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"Ошибка при удалении примера: {e}")
            return False


# Глобальный экземпляр менеджера
training_manager = TrainingExamplesManager()
