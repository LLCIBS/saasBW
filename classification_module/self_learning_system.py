#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Система автоматического самообучения с поддержкой подтверждений правильных классификаций
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from collections import Counter, defaultdict
import re
import hashlib


class SelfLearningSystem:
    """Система автоматического самообучения с подтверждениями"""
    
    def __init__(self, training_db_path="training_examples.db", rules_db_path="classification_rules.db"):
        self.training_db_path = training_db_path
        self.rules_db_path = rules_db_path
        self.init_learning_tables()
    
    def init_learning_tables(self):
        """Инициализация таблиц для самообучения"""
        conn = sqlite3.connect(self.training_db_path)
        cursor = conn.cursor()
        
        # Таблица подтверждений правильных классификаций
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS correct_classifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT,
                call_date TEXT,
                call_time TEXT,
                category TEXT NOT NULL,
                reasoning TEXT,
                transcription_hash TEXT,
                confirmed_by TEXT,
                confirmed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confidence_level INTEGER DEFAULT 5,
                comment TEXT
            )
        ''')
        
        # Таблица статистики успешности классификаций
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS classification_success_stats (
                category TEXT PRIMARY KEY,
                total_classified INTEGER DEFAULT 0,
                confirmed_correct INTEGER DEFAULT 0,
                corrections_count INTEGER DEFAULT 0,
                success_rate REAL DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица для анализа паттернов ошибок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS error_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_text TEXT NOT NULL,
                original_category TEXT NOT NULL,
                corrected_category TEXT NOT NULL,
                frequency INTEGER DEFAULT 1,
                confidence_score REAL DEFAULT 0.0,
                is_active BOOLEAN DEFAULT 1,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                examples TEXT
            )
        ''')
        
        # Таблица для эффективности примеров
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS example_effectiveness (
                example_id INTEGER PRIMARY KEY,
                times_used INTEGER DEFAULT 0,
                times_helped INTEGER DEFAULT 0,
                times_misled INTEGER DEFAULT 0,
                times_confirmed INTEGER DEFAULT 0,
                success_rate REAL DEFAULT 0.0,
                last_used TIMESTAMP
            )
        ''')
        
        # Таблица для успешных паттернов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS success_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                common_keywords TEXT,
                transcription_samples TEXT,
                confirmation_count INTEGER DEFAULT 0,
                success_rate REAL DEFAULT 1.0,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_confirmed TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        
        # Инициализация таблиц в базе правил
        self.init_rules_tables()
    
    def init_rules_tables(self):
        """Инициализация таблиц для автоправил в базе правил"""
        conn = sqlite3.connect(self.rules_db_path)
        cursor = conn.cursor()
        
        # Таблица для автоматически извлеченных правил
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auto_extracted_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_text TEXT NOT NULL,
                category_id TEXT NOT NULL,
                confidence REAL DEFAULT 0.0,
                source_type TEXT DEFAULT 'pattern_analysis',
                example_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_verified TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def mark_as_correct(self, phone_number: str, call_date: str, call_time: str,
                       category: str, reasoning: str, transcription: str,
                       confirmed_by: str, confidence_level: int = 5, comment: str = "") -> bool:
        """Отметить классификацию как правильную"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С‚Р°Р±Р»РёС†С‹, РµСЃР»Рё РЅСѓР¶РЅРѕ
            self.init_learning_tables()
            transcription_hash = hashlib.md5(transcription.encode('utf-8')).hexdigest()
            logger.info(f"mark_as_correct: phone={phone_number}, date={call_date}, time={call_time}, category={category}")
            
            conn = sqlite3.connect(self.training_db_path, timeout=10.0)
            cursor = conn.cursor()
            
            # Проверяем, не была ли уже отмечена
            try:
                cursor.execute('''
                    SELECT id FROM correct_classifications
                    WHERE phone_number = ? AND call_date = ? AND call_time = ?
                ''', (phone_number, call_date, call_time))
            except sqlite3.OperationalError as e:
                logger.error(f"Ошибка при проверке существующей отметки: {e}")
                conn.close()
                # Попробуем пересоздать таблицы
                self.init_learning_tables()
                conn = sqlite3.connect(self.training_db_path)
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id FROM correct_classifications
                    WHERE phone_number = ? AND call_date = ? AND call_time = ?
                ''', (phone_number, call_date, call_time))
            
            existing = cursor.fetchone()
            logger.info(f"Существующая отметка: {existing}")
            
            if existing:
                # Обновляем существующую отметку
                cursor.execute('''
                    UPDATE correct_classifications
                    SET category = ?, reasoning = ?, confidence_level = ?,
                        comment = ?, confirmed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (category, reasoning, confidence_level, comment, existing[0]))
                logger.info(f"Обновлена существующая отметка ID: {existing[0]}")
            else:
                # Добавляем новую отметку
                cursor.execute('''
                    INSERT INTO correct_classifications
                    (phone_number, call_date, call_time, category, reasoning,
                     transcription_hash, confirmed_by, confidence_level, comment)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (phone_number, call_date, call_time, category, reasoning,
                      transcription_hash, confirmed_by, confidence_level, comment))
                logger.info("Добавлена новая отметка правильности")
            
            # Обновляем статистику успешности категории
            try:
                self._update_category_success_stats(category, is_correct=True)
            except Exception as stats_error:
                logger.warning(f"Ошибка при обновлении статистики: {stats_error}")
            
            # Обновляем паттерны успеха
            try:
                self._update_success_patterns(transcription, category, reasoning)
            except Exception as pattern_error:
                logger.warning(f"Ошибка при обновлении паттернов: {pattern_error}")
            
            # Улучшаем эффективность примеров, которые могли помочь
            try:
                self._improve_example_effectiveness(transcription, category)
            except Exception as effect_error:
                logger.warning(f"Ошибка при обновлении эффективности: {effect_error}")
            
            conn.commit()
            conn.close()
            logger.info("mark_as_correct: успешно завершено")
            return True
            
        except Exception as e:
            import logging
            import traceback
            logger = logging.getLogger(__name__)
            error_details = traceback.format_exc()
            logger.error(f"Ошибка при отметке как правильной: {e}")
            logger.error(f"Детали ошибки: {error_details}")
            try:
                conn.close()
            except:
                pass
            return False
    
    def _update_category_success_stats(self, category: str, is_correct: bool = True):
        """Обновление статистики успешности категории"""
        conn = sqlite3.connect(self.training_db_path, timeout=10.0)
        cursor = conn.cursor()
        
        # Получаем текущую статистику
        cursor.execute('''
            SELECT total_classified, confirmed_correct, corrections_count
            FROM classification_success_stats
            WHERE category = ?
        ''', (category,))
        
        result = cursor.fetchone()
        
        if result:
            total, confirmed, corrections = result
            new_total = total + 1
            new_confirmed = confirmed + 1 if is_correct else confirmed
            new_corrections = corrections if is_correct else corrections + 1
            success_rate = (new_confirmed / new_total) * 100 if new_total > 0 else 0
            
            cursor.execute('''
                UPDATE classification_success_stats
                SET total_classified = ?, confirmed_correct = ?,
                    corrections_count = ?, success_rate = ?, last_updated = CURRENT_TIMESTAMP
                WHERE category = ?
            ''', (new_total, new_confirmed, new_corrections, success_rate, category))
        else:
            # Создаем новую запись
            if is_correct:
                cursor.execute('''
                    INSERT INTO classification_success_stats
                    (category, total_classified, confirmed_correct, corrections_count, success_rate)
                    VALUES (?, 1, 1, 0, 100.0)
                ''', (category,))
            else:
                cursor.execute('''
                    INSERT INTO classification_success_stats
                    (category, total_classified, confirmed_correct, corrections_count, success_rate)
                    VALUES (?, 1, 0, 1, 0.0)
                ''', (category,))
        
        conn.commit()
        conn.close()
    
    def _update_success_patterns(self, transcription: str, category: str, reasoning: str):
        """Обновление паттернов успешных классификаций"""
        conn = sqlite3.connect(self.training_db_path, timeout=10.0)
        cursor = conn.cursor()
        
        # Извлекаем ключевые слова
        keywords = self._extract_keywords_from_text(transcription)
        
        # Ищем существующий паттерн для этой категории
        cursor.execute('''
            SELECT id, common_keywords, transcription_samples, confirmation_count
            FROM success_patterns
            WHERE category = ? AND is_active = 1
            ORDER BY confirmation_count DESC
            LIMIT 1
        ''', (category,))
        
        result = cursor.fetchone()
        
        if result:
            pattern_id, existing_keywords_json, samples_json, count = result
            
            # Объединяем ключевые слова
            existing_keywords = json.loads(existing_keywords_json) if existing_keywords_json else []
            combined_keywords = list(set(existing_keywords + keywords))[:20]
            
            # Добавляем пример (максимум 10 примеров)
            samples = json.loads(samples_json) if samples_json else []
            sample_text = transcription[:200]
            if sample_text not in samples:
                samples.append(sample_text)
                if len(samples) > 10:
                    samples = samples[-10:]
            
            cursor.execute('''
                UPDATE success_patterns
                SET common_keywords = ?, transcription_samples = ?,
                    confirmation_count = confirmation_count + 1,
                    last_confirmed = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (json.dumps(combined_keywords, ensure_ascii=False),
                  json.dumps(samples, ensure_ascii=False),
                  pattern_id))
        else:
            # Создаем новый паттерн успеха
            samples = [transcription[:200]]
            cursor.execute('''
                INSERT INTO success_patterns
                (category, common_keywords, transcription_samples, confirmation_count)
                VALUES (?, ?, ?, 1)
            ''', (category,
                  json.dumps(keywords, ensure_ascii=False),
                  json.dumps(samples, ensure_ascii=False)))
        
        conn.commit()
        conn.close()
    
    def _improve_example_effectiveness(self, transcription: str, category: str):
        """Улучшение оценки эффективности примеров при подтверждении правильности"""
        conn = sqlite3.connect(self.training_db_path)
        cursor = conn.cursor()
        
        # Находим примеры для этой категории
        cursor.execute('''
            SELECT id FROM training_examples
            WHERE correct_category = ? AND is_active = 1
        ''', (category,))
        
        example_ids = [row[0] for row in cursor.fetchall()]
        
        # Проверяем, какие примеры похожи на подтвержденную транскрипцию
        transcription_keywords = set(self._extract_keywords_from_text(transcription))
        
        for ex_id in example_ids:
            cursor.execute('SELECT transcription FROM training_examples WHERE id = ?', (ex_id,))
            ex_result = cursor.fetchone()
            if not ex_result:
                continue
                
            ex_keywords = set(self._extract_keywords_from_text(ex_result[0]))
            
            # Вычисляем пересечение ключевых слов
            similarity = len(transcription_keywords & ex_keywords) / max(len(transcription_keywords | ex_keywords), 1)
            
            if similarity > 0.3:
                # Обновляем эффективность примера
                cursor.execute('''
                    SELECT times_used, times_confirmed FROM example_effectiveness
                    WHERE example_id = ?
                ''', (ex_id,))
                
                existing = cursor.fetchone()
                
                if existing:
                    times_used, times_confirmed = existing
                    new_confirmed = times_confirmed + 1
                    new_rate = new_confirmed / max(times_used, 1)
                    cursor.execute('''
                        UPDATE example_effectiveness
                        SET times_confirmed = ?, success_rate = ?, last_used = CURRENT_TIMESTAMP
                        WHERE example_id = ?
                    ''', (new_confirmed, new_rate, ex_id))
                else:
                    cursor.execute('''
                        INSERT INTO example_effectiveness 
                        (example_id, times_confirmed, success_rate, last_used)
                        VALUES (?, 1, 1.0, CURRENT_TIMESTAMP)
                    ''', (ex_id,))
        
        conn.commit()
        conn.close()
    
    def _extract_keywords_from_text(self, text: str) -> List[str]:
        """Извлечение ключевых слов из текста"""
        stop_words = {'это', 'что', 'как', 'так', 'для', 'или', 'если', 'но', 'да', 'нет',
                     'он', 'она', 'они', 'мы', 'вы', 'меня', 'тебя', 'его', 'её', 'быть',
                     'был', 'была', 'было', 'были', 'в', 'на', 'с', 'по', 'от', 'до',
                     'из', 'за', 'под', 'над', 'к', 'о', 'об', 'со', 'во', 'при'}
        
        words = re.findall(r'\b[а-яё]{4,}\b', text.lower())
        keywords = [w for w in words if w not in stop_words]
        
        word_counts = Counter(keywords)
        return [word for word, count in word_counts.most_common(15)]
    
    def get_category_success_stats(self) -> Dict[str, Dict]:
        """Получение статистики успешности по категориям"""
        conn = sqlite3.connect(self.training_db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT category, total_classified, confirmed_correct, 
                   corrections_count, success_rate
            FROM classification_success_stats
            ORDER BY total_classified DESC
        ''')
        
        stats = {}
        for row in cursor.fetchall():
            category, total, confirmed, corrections, rate = row
            stats[category] = {
                'total': total,
                'confirmed_correct': confirmed,
                'corrections': corrections,
                'success_rate': rate,
                'accuracy': rate
            }
        
        conn.close()
        return stats
    
    def get_success_patterns_for_category(self, category: str) -> List[Dict]:
        """Получение паттернов успеха для категории"""
        conn = sqlite3.connect(self.training_db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, common_keywords, transcription_samples, 
                   confirmation_count, success_rate
            FROM success_patterns
            WHERE category = ? AND is_active = 1
            ORDER BY confirmation_count DESC
        ''', (category,))
        
        patterns = []
        for row in cursor.fetchall():
            pattern_id, keywords_json, samples_json, count, rate = row
            patterns.append({
                'id': pattern_id,
                'keywords': json.loads(keywords_json) if keywords_json else [],
                'samples': json.loads(samples_json) if samples_json else [],
                'confirmation_count': count,
                'success_rate': rate
            })
        
        conn.close()
        return patterns
    
    def analyze_learning_progress(self, days: int = 30) -> Dict:
        """Анализ прогресса обучения на основе подтверждений"""
        conn = sqlite3.connect(self.training_db_path)
        cursor = conn.cursor()
        
        # Подтверждения за период
        cursor.execute('''
            SELECT COUNT(*) as total_confirmations,
                   COUNT(DISTINCT category) as categories_confirmed,
                   AVG(confidence_level) as avg_confidence
            FROM correct_classifications
            WHERE confirmed_at >= datetime('now', '-{} days')
        '''.format(days))
        
        confirmations = cursor.fetchone()
        
        # Корректировки за период
        cursor.execute('''
            SELECT COUNT(*) as total_corrections
            FROM correction_history
            WHERE correction_date >= datetime('now', '-{} days')
        '''.format(days))
        
        corrections = cursor.fetchone()[0]
        
        # Вычисляем соотношение правильных/неправильных
        total_confirmations = confirmations[0] or 0
        total_interactions = total_confirmations + corrections
        
        accuracy_improvement = 0.0
        if total_interactions > 0:
            current_accuracy = (total_confirmations / total_interactions) * 100
            
            # Сравниваем с предыдущим периодом
            cursor.execute('''
                SELECT COUNT(*) as prev_confirmations
                FROM correct_classifications
                WHERE confirmed_at >= datetime('now', '-{} days')
                  AND confirmed_at < datetime('now', '-{} days')
            '''.format(days * 2, days))
            
            prev_confirmations = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT COUNT(*) as prev_corrections
                FROM correction_history
                WHERE correction_date >= datetime('now', '-{} days')
                  AND correction_date < datetime('now', '-{} days')
            '''.format(days * 2, days))
            
            prev_corrections = cursor.fetchone()[0] or 0
            prev_total = prev_confirmations + prev_corrections
            
            if prev_total > 0:
                prev_accuracy = (prev_confirmations / prev_total) * 100
                accuracy_improvement = current_accuracy - prev_accuracy
        
        conn.close()
        
        return {
            'period_days': days,
            'total_confirmations': total_confirmations,
            'total_corrections': corrections,
            'total_interactions': total_interactions,
            'current_accuracy': (total_confirmations / total_interactions * 100) if total_interactions > 0 else 0,
            'accuracy_improvement': accuracy_improvement,
            'categories_confirmed': confirmations[1] or 0,
            'avg_confidence': confirmations[2] or 0
        }
    
    def analyze_error_patterns(self, days: int = 30) -> List[Dict]:
        """Анализ паттернов ошибок за указанный период"""
        conn = sqlite3.connect(self.training_db_path)
        cursor = conn.cursor()
        
        # Получаем все корректировки за период
        cursor.execute('''
            SELECT original_category, corrected_category, original_reasoning, corrected_reasoning
            FROM correction_history
            WHERE correction_date >= datetime('now', '-{} days')
        '''.format(days))
        
        corrections = cursor.fetchall()
        conn.close()
        
        # Анализируем паттерны
        error_transitions = defaultdict(list)
        
        for orig_cat, corr_cat, orig_reason, corr_reason in corrections:
            key = f"{orig_cat}→{corr_cat}"
            error_transitions[key].append({
                'original_reasoning': orig_reason or '',
                'corrected_reasoning': corr_reason or ''
            })
        
        # Извлекаем ключевые слова из паттернов ошибок
        patterns = []
        for transition, examples in error_transitions.items():
            if len(examples) >= 2:
                orig_cat, corr_cat = transition.split('→')
                
                # Находим общие ключевые слова в ошибочных примерах
                all_reasonings = [ex['original_reasoning'] for ex in examples]
                common_keywords = self._find_common_keywords(all_reasonings)
                
                patterns.append({
                    'transition': transition,
                    'original_category': orig_cat,
                    'corrected_category': corr_cat,
                    'frequency': len(examples),
                    'confidence': min(len(examples) / 10.0, 1.0),
                    'common_keywords': common_keywords,
                    'examples': examples[:5]
                })
        
        patterns.sort(key=lambda x: x['frequency'], reverse=True)
        return patterns
    
    def _find_common_keywords(self, texts: List[str]) -> List[str]:
        """Поиск общих ключевых слов в текстах"""
        all_words = []
        for text in texts:
            words = re.findall(r'\b[а-яё]{4,}\b', text.lower())
            all_words.extend(words)
        
        word_counts = Counter(all_words)
        threshold = len(texts) * 0.5
        common = [word for word, count in word_counts.items() if count >= threshold]
        return common[:10]
    
    def _extract_common_phrases(self, corrections: List[Tuple]) -> Dict[str, int]:
        """Извлечение общих фраз из корректировок"""
        phrases = Counter()
        
        important_phrases = [
            'подтверждает запись', 'уточняет время', 'подумаю', 'перезвоню',
            'уже записан', 'существующая запись', 'переносит запись',
            'нет конкретной записи', 'договоренность связаться',
            'уже нашел решение', 'благодарит', 'подтверждение записи'
        ]
        
        for _, _, orig_reason, corr_reason in corrections:
            text = f"{orig_reason or ''} {corr_reason or ''}".lower()
            for phrase in important_phrases:
                if phrase in text:
                    phrases[phrase] += 1
        
        return dict(phrases)
    
    def auto_update_rules(self, min_confidence: float = 0.7) -> int:
        """Автоматическое обновление правил на основе паттернов ошибок"""
        patterns = self.analyze_error_patterns(days=30)
        
        conn = sqlite3.connect(self.rules_db_path)
        cursor = conn.cursor()
        
        updated_count = 0
        
        for pattern in patterns:
            if pattern['confidence'] < min_confidence:
                continue
            
            orig_cat = pattern['original_category']
            corr_cat = pattern['corrected_category']
            keywords = pattern['common_keywords']
            
            # Формируем правило на основе паттерна
            if keywords:
                rule_text = f"ВНИМАНИЕ: Если в транскрипции встречаются фразы: {', '.join(keywords[:3])}, " \
                          f"то НЕ классифицировать как {orig_cat}. Вероятно это {corr_cat}."
            else:
                rule_text = f"ПАТТЕРН ОШИБКИ: Частая ошибка {orig_cat}→{corr_cat}. " \
                          f"Проверяй внимательнее эту категорию."
            
            # Проверяем, не существует ли уже такое правило (по тексту и категории)
            cursor.execute('''
                SELECT id FROM auto_extracted_rules
                WHERE category_id = ? AND rule_text LIKE ?
                LIMIT 1
            ''', (orig_cat, f'%{orig_cat}→{corr_cat}%'))
            
            existing = cursor.fetchone()
            
            if not existing:
                # Сохраняем автоматически извлеченное правило
                cursor.execute('''
                    INSERT INTO auto_extracted_rules 
                    (rule_text, category_id, confidence, source_type, example_count, is_active)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (rule_text, orig_cat, pattern['confidence'], 'error_pattern',
                      pattern['frequency'], 1))
                updated_count += 1
        
        conn.commit()
        conn.close()
        
        return updated_count
    
    def analyze_example_effectiveness(self) -> Dict:
        """Анализ эффективности обучающих примеров"""
        conn = sqlite3.connect(self.training_db_path)
        cursor = conn.cursor()
        
        # Получаем статистику по примерам
        cursor.execute('''
            SELECT 
                te.id,
                te.used_count,
                te.correct_category
            FROM training_examples te
            WHERE te.is_active = 1
        ''')
        
        examples_stats = cursor.fetchall()
        
        # Получаем данные об эффективности
        cursor.execute('''
            SELECT example_id, times_used, times_confirmed, times_misled, success_rate
            FROM example_effectiveness
        ''')
        
        effectiveness_data = {row[0]: row[1:] for row in cursor.fetchall()}
        
        # Получаем количество корректировок после использования примеров
        effective_examples = []
        ineffective_examples = []
        
        for ex_id, used_count, category in examples_stats:
            if used_count == 0:
                continue
            
            eff_data = effectiveness_data.get(ex_id, (0, 0, 0, 0.0))
            times_used, times_confirmed, times_misled, success_rate = eff_data
            
            # Вычисляем метрику эффективности
            if times_used > 0:
                effectiveness_score = success_rate
            else:
                effectiveness_score = 0.5  # Нейтральная оценка если нет данных
            
            if effectiveness_score >= 0.7:
                effective_examples.append({
                    'id': ex_id,
                    'score': effectiveness_score,
                    'used_count': used_count,
                    'times_confirmed': times_confirmed
                })
            elif effectiveness_score < 0.3 and used_count >= 5:
                ineffective_examples.append({
                    'id': ex_id,
                    'score': effectiveness_score,
                    'used_count': used_count,
                    'times_misled': times_misled
                })
        
        conn.close()
        
        return {
            'effective_count': len(effective_examples),
            'ineffective_count': len(ineffective_examples),
            'effective_examples': effective_examples[:10],
            'ineffective_examples': ineffective_examples[:10]
        }
    
    def suggest_example_improvements(self) -> List[Dict]:
        """Предложения по улучшению примеров"""
        effectiveness = self.analyze_example_effectiveness()
        suggestions = []
        
        # Предложение: деактивировать неэффективные примеры
        for ex in effectiveness['ineffective_examples']:
            suggestions.append({
                'type': 'deactivate',
                'example_id': ex['id'],
                'reason': f'Низкая эффективность ({ex["score"]:.2%}), используется {ex["used_count"]} раз',
                'priority': 'high'
            })
        
        # Предложение: добавить больше примеров для проблемных категорий
        patterns = self.analyze_error_patterns(days=7)
        for pattern in patterns[:5]:
            if pattern['frequency'] >= 3:
                suggestions.append({
                    'type': 'add_examples',
                    'category': pattern['corrected_category'],
                    'reason': f'Частая ошибка {pattern["original_category"]}→{pattern["corrected_category"]} ({pattern["frequency"]} раз)',
                    'suggested_keywords': pattern['common_keywords'][:5],
                    'priority': 'medium'
                })
        
        return suggestions
    
    def learn_from_successful_classifications(self, min_count: int = 5) -> List[Dict]:
        """Обучение на успешных классификациях (без корректировок)"""
        conn = sqlite3.connect(self.training_db_path)
        cursor = conn.cursor()
        
        # Находим категории с высокой точностью
        cursor.execute('''
            SELECT 
                category,
                COUNT(*) as confirm_count
            FROM correct_classifications
            WHERE confirmed_at >= datetime('now', '-30 days')
            GROUP BY category
            HAVING confirm_count >= ?
        ''', (min_count,))
        
        successful_categories = cursor.fetchall()
        
        successful_patterns = []
        
        for category, _ in successful_categories:
            # Получаем примеры из подтверждений
            cursor.execute('''
                SELECT transcription, reasoning
                FROM correct_classifications
                WHERE category = ? AND confirmed_at >= datetime('now', '-30 days')
                LIMIT 10
            ''', (category,))
            
            examples = cursor.fetchall()
            if examples:
                transcriptions = [ex[0] for ex in examples if ex[0]]
                if transcriptions:
                    common_words = self._find_common_keywords(transcriptions)
                    
                    successful_patterns.append({
                        'category': category,
                        'common_keywords': common_words,
                        'example_count': len(examples),
                        'confidence': 0.9
                    })
        
        conn.close()
        return successful_patterns
    
    def generate_learning_report(self) -> Dict:
        """Генерация базового отчета о самообучении"""
        patterns = self.analyze_error_patterns(days=30)
        effectiveness = self.analyze_example_effectiveness()
        suggestions = self.suggest_example_improvements()
        successful = self.learn_from_successful_classifications()
        
        return {
            'error_patterns': {
                'total': len(patterns),
                'top_5': patterns[:5]
            },
            'example_effectiveness': effectiveness,
            'suggestions': {
                'total': len(suggestions),
                'high_priority': [s for s in suggestions if s['priority'] == 'high'],
                'all': suggestions
            },
            'successful_patterns': {
                'categories_with_high_accuracy': len(successful),
                'patterns': successful
            },
            'recommendations': self._generate_recommendations(patterns, effectiveness, suggestions)
        }
    
    def _generate_recommendations(self, patterns, effectiveness, suggestions) -> List[str]:
        """Генерация рекомендаций на основе анализа"""
        recommendations = []
        
        if patterns:
            top_error = patterns[0]
            recommendations.append(
                f"Самая частая ошибка: {top_error['original_category']}→{top_error['corrected_category']} "
                f"({top_error['frequency']} раз). Рекомендуется добавить больше примеров для категории {top_error['corrected_category']}."
            )
        
        if effectiveness['ineffective_count'] > 0:
            recommendations.append(
                f"Найдено {effectiveness['ineffective_count']} неэффективных примеров. "
                f"Рекомендуется их пересмотреть или деактивировать."
            )
        
        high_priority = [s for s in suggestions if s['priority'] == 'high']
        if high_priority:
            recommendations.append(
                f"{len(high_priority)} срочных рекомендаций требуют внимания."
            )
        
        return recommendations
    
    def generate_enhanced_learning_report(self) -> Dict:
        """Расширенный отчет о самообучении с учетом подтверждений"""
        base_report = self.generate_learning_report()
        success_stats = self.get_category_success_stats()
        learning_progress = self.analyze_learning_progress()
        
        top_categories = sorted(
            success_stats.items(),
            key=lambda x: x[1]['success_rate'],
            reverse=True
        )[:5]
        
        problem_categories = [
            (cat, stats) for cat, stats in success_stats.items()
            if stats['total'] >= 5 and stats['success_rate'] < 70
        ]
        
        return {
            **base_report,
            'success_statistics': {
                'by_category': success_stats,
                'top_performing': [{'category': cat, **stats} for cat, stats in top_categories],
                'needs_attention': [{'category': cat, **stats} for cat, stats in problem_categories]
            },
            'learning_progress': learning_progress,
            'recommendations': self._generate_enhanced_recommendations(
                base_report, success_stats, learning_progress
            )
        }
    
    def _generate_enhanced_recommendations(self, base_report, success_stats, progress) -> List[str]:
        """Генерация расширенных рекомендаций с учетом подтверждений"""
        recommendations = base_report.get('recommendations', [])
        
        if progress['accuracy_improvement'] > 0:
            recommendations.append(
                f"Точность классификации выросла на {progress['accuracy_improvement']:.1f}% "
                f"за последние {progress['period_days']} дней. Отлично!"
            )
        elif progress['accuracy_improvement'] < 0:
            recommendations.append(
                f"Точность классификации снизилась на {abs(progress['accuracy_improvement']):.1f}%. "
                f"Рекомендуется проверить новые обучающие примеры."
            )
        
        if progress['total_confirmations'] > 0:
            recommendations.append(
                f"Подтверждено {progress['total_confirmations']} правильных классификаций. "
                f"Система накапливает знания о успешных паттернах."
            )
        
        problem_cats = [
            cat for cat, stats in success_stats.items()
            if stats['total'] >= 5 and stats['success_rate'] < 70
        ]
        if problem_cats:
            recommendations.append(
                f"Категории, требующие внимания: {', '.join(problem_cats[:3])}. "
                f"Рекомендуется добавить больше примеров для этих категорий."
            )
        
        return recommendations
    
    def apply_auto_improvements(self, auto_update: bool = False) -> Dict:
        """Применение автоматических улучшений"""
        report = self.generate_learning_report()
        
        if auto_update:
            # Автоматически обновляем правила
            rules_updated = self.auto_update_rules()
            
            # Деактивируем неэффективные примеры (только с очень низкой эффективностью)
            conn = sqlite3.connect(self.training_db_path, timeout=10.0)
            cursor = conn.cursor()
            
            deactivated = 0
            for ex in report['example_effectiveness']['ineffective_examples']:
                if ex['score'] < 0.2:
                    cursor.execute('UPDATE training_examples SET is_active = 0 WHERE id = ?', (ex['id'],))
                    deactivated += 1
            
            conn.commit()
            conn.close()
            
            return {
                'rules_updated': rules_updated,
                'examples_deactivated': deactivated,
                'status': 'auto_improvements_applied'
            }
        
        return {
            'status': 'analysis_only',
            'report': report
        }


class IntegratedLearningSystem:
    """Интегрированная система обучения с подтверждениями"""
    
    def __init__(self):
        try:
            from .training_examples import TrainingExamplesManager
            from .classification_rules import ClassificationRulesManager
        except ImportError:
            from training_examples import TrainingExamplesManager
            from classification_rules import ClassificationRulesManager
        
        self.training_manager = TrainingExamplesManager()
        self.rules_manager = ClassificationRulesManager()
        self.self_learning = SelfLearningSystem()
    
    def mark_classification_correct(self, phone_number, call_date, call_time,
                                    category, reasoning, transcription,
                                    confirmed_by="user", confidence=5, comment=""):
        """Отметить классификацию как правильную"""
        return self.self_learning.mark_as_correct(
            phone_number, call_date, call_time,
            category, reasoning, transcription,
            confirmed_by, confidence_level=confidence, comment=comment
        )
    
    def process_new_correction(self, transcription, orig_cat, corr_cat,
                               orig_reason, corr_reason, operator_name=""):
        """Обработка новой корректировки"""
        # Сохраняем корректировку
        self.training_manager.add_training_example(
            transcription, corr_cat, corr_reason,
            orig_cat, orig_reason, operator_name
        )
        
        # Обновляем статистику (корректировка = ошибка)
        self.self_learning._update_category_success_stats(orig_cat, is_correct=False)
        
        # Анализируем паттерны
        patterns = self.self_learning.analyze_error_patterns(days=7)
        recent_patterns = [p for p in patterns if p['frequency'] >= 3]
        if recent_patterns:
            self.self_learning.auto_update_rules(min_confidence=0.8)
        
        return True
    
    def daily_learning_cycle(self):
        """Ежедневный цикл самообучения"""
        # Анализ ошибок за последние 30 дней
        report = self.self_learning.generate_enhanced_learning_report()
        
        # Автоматическое обновление правил
        rules_updated = self.self_learning.auto_update_rules(min_confidence=0.7)
        
        # Анализ эффективности примеров
        effectiveness = self.self_learning.analyze_example_effectiveness()
        
        return {
            'report': report,
            'rules_updated': rules_updated,
            'effectiveness': effectiveness,
            'timestamp': datetime.now().isoformat()
        }

