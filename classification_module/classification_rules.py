#!/usr/bin/env python3
"""
Менеджер правил классификации и промптов (PostgreSQL / SQLAlchemy).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from database.models import (
    UserAutoExtractedRule,
    UserClassificationCriticalRule,
    UserClassificationHistory,
    UserClassificationRule,
    UserClassificationSchedule,
    UserClassificationSetting,
    UserClassificationSystemPrompt,
    db,
)


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _to_iso(val: Any) -> Any:
    if isinstance(val, datetime):
        return val.isoformat()
    return val


class ClassificationRulesManager:
    """Менеджер для управления правилами классификации и промптами (per user_id)."""

    def __init__(
        self,
        user_id: Optional[int] = None,
        classification_root: Any = None,
        **_: Any,
    ) -> None:
        uid = user_id
        if uid is None:
            env_uid = os.environ.get("CLASSIFICATION_USER_ID")
            uid = int(env_uid) if env_uid and str(env_uid).isdigit() else None
        if uid is None or int(uid) <= 0:
            raise ValueError(
                "ClassificationRulesManager требует user_id=... или переменную окружения CLASSIFICATION_USER_ID"
            )
        self.user_id = int(uid)
        self._classification_root: Optional[Path] = None
        if classification_root is not None:
            self._classification_root = Path(classification_root).resolve()
        self._ensure_notify_defaults()
        self._load_default_rules()

    @property
    def classification_root(self) -> Path:
        """Каталог .../classification для логов и uploads (если задан в конструкторе)."""
        if self._classification_root is not None:
            return self._classification_root
        return Path()

    def _ensure_notify_defaults(self) -> None:
        """Telegram/MAX ключи по умолчанию (как INSERT OR IGNORE в SQLite)."""
        defaults = [
            ("telegram_enabled", "0", "Включить отправку отчетов в Telegram"),
            ("telegram_bot_token", "", "Токен Telegram-бота"),
            ("telegram_chat_id", "", "ID чата или канала для отправки"),
            ("max_enabled", "0", "Включить отправку отчетов в MAX"),
            ("max_access_token", "", "Токен бота MAX (business.max.ru → Чат-боты)"),
            ("max_chat_id", "", "Числовой chat_id чата MAX для отчётов"),
        ]
        for key, val, desc in defaults:
            exists = (
                UserClassificationSetting.query.filter_by(user_id=self.user_id, setting_key=key).first()
            )
            if not exists:
                db.session.add(
                    UserClassificationSetting(
                        user_id=self.user_id, setting_key=key, setting_value=val, description=desc
                    )
                )
        db.session.commit()

    def _load_default_rules(self) -> None:
        """Загрузка стандартных правил при первом запуске"""
        n = UserClassificationSystemPrompt.query.filter_by(user_id=self.user_id).count()
        if n > 0:
            return

        default_prompt = """Ты - опытный аналитик автосервиса с глубоким пониманием бизнес-процессов. Проанализируй транскрипцию звонка и определи его тип с учетом контекста предыдущих звонков клиента.

ВАЖНО: Соблюдай СТРОГИЙ ПОРЯДОК ПРИОРИТЕТОВ! Правила расположены в порядке убывания приоритета - проверяй их последовательно.

ФОРМАТ ОТВЕТА:
Ответь строго только в следующем формате:
[КАТЕГОРИЯ:IN.* или OUT.*]
[ОБОСНОВАНИЕ:краткое понятное объяснение на русском языке, 1-3 предложения]

ВАЖНО:
- не используй английский язык
- не пиши Category / Explanation / Summary / Here's why
- не используй markdown, списки и лишние заголовки
- не пиши ничего кроме этих двух строк
- в [КАТЕГОРИЯ:...] укажи один точный символьный код категории
- в [ОБОСНОВАНИЕ:...] дай только человеческое объяснение выбора категории

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

        db.session.add(
            UserClassificationSystemPrompt(
                user_id=self.user_id,
                name="default_prompt",
                content=default_prompt,
                description="Основной промпт для классификации звонков",
                is_active=True,
            )
        )

        default_rules = [
            (
                "1",
                "НЕ ЦЕЛЕВОЙ",
                "СТРОГО НЕ ЦЕЛЕВОЙ: Отечественный авто (Lada, UAZ, ГАЗ, ВАЗ), авто 2006 г.в. или старше, запрос по отдельной снятой запчасти, не клиент (поставщик, реклама, банк, страховка), грузовик/спецтехника, тестовый звонок, звонок не по автомобилю. КРИТЕРИИ: Если НЕ иномарка 2007+ г.в. ИЛИ НЕ автомобиль целиком - ОБЯЗАТЕЛЬНО категория 1.",
                15,
            ),
            (
                "2",
                "ЗАПИСЬ НА СЕРВИС",
                "СТРОГО ЗАПИСЬ: Целевой звонок (иномарка 2007+ г.в., автомобиль целиком) с КОНКРЕТНОЙ записью на время/дату. ОБЯЗАТЕЛЬНЫЕ КРИТЕРИИ: 1) Четкое время визита (дата + время), 2) НЕ фразы \"подумаю\", \"перезвоню\", \"найду решение\", 3) Конкретная договоренность о визите. КОНТЕКСТ: Первый контакт клиента или повторный после долгого перерыва. ИСКЛЮЧЕНИЯ: Если есть фразы сомнения - это категория 3.",
                12,
            ),
            (
                "3",
                "КОНСУЛЬТАЦИЯ",
                "СТРОГО КОНСУЛЬТАЦИЯ: Целевой звонок, уточнение деталей для будущего визита (работы, цены, условия), но записи нет. ВКЛЮЧАЕТ: \"подумаю\", \"перезвоню\", \"уже нашел решение\", \"уточню детали\", \"сравню цены\", \"посмотрю варианты\". КОНТЕКСТ: Первый звонок по новой проблеме или уточнение деталей. ПРИОРИТЕТ: Если есть сомнения клиента - это категория 3, НЕ 2.",
                11,
            ),
            (
                "4",
                "ПОДУМАЕТ/ОТКАЗ",
                "СТРОГО ОТКАЗ: Целевой звонок с прямым отказом или четкими фразами отказа: \"не буду\", \"не нужно\", \"отказываюсь\", \"не подходит\", \"не интересно\", \"не буду ремонтировать\". НЕ включает \"подумаю\" - это категория 3. КОНТЕКСТ: Учитывай предыдущие звонки - если был отказ, это может быть повторная попытка.",
                10,
            ),
            (
                "5",
                "НЕТ ВРЕМЕНИ/ЗАНЯТО",
                "СТРОГО НЕТ ВРЕМЕНИ: Целевой звонок, но нет свободных окон в ближайшее время. КРИТЕРИИ: Конкретные фразы \"нет времени\", \"занято\", \"нет свободных окон\", \"очередь большая\", \"запись на месяц вперед\". КОНТЕКСТ: Учитывай загруженность сервиса и предыдущие записи клиента.",
                9,
            ),
            (
                "6",
                "ВЫСОКАЯ СТОИМОСТЬ",
                "СТРОГО ДОРОГО: Целевой звонок, отказ исключительно из-за цены. КРИТЕРИИ: Четкие фразы \"дорого\", \"много денег\", \"не потяну\", \"слишком дорого\", \"не по карману\", \"ценник высокий\". КОНТЕКСТ: Сравни с предыдущими звонками по стоимости.",
                8,
            ),
            (
                "7",
                "СВОИ ЗАПЧАСТИ",
                "СТРОГО СВОИ ЗАПЧАСТИ: Целевой звонок, клиент настаивает на своих запчастях или хочет ремонт с использованием своих деталей. КРИТЕРИИ: \"у меня есть запчасти\", \"привезу свои детали\", \"хочу со своими запчастями\", \"у меня уже куплено\".",
                7,
            ),
            (
                "8",
                "НЕ ВЫПОЛНЯЕМ РАБОТЫ",
                "СТРОГО НЕ ВЫПОЛНЯЕМ: Целевой звонок, техническая невозможность выполнения. КРИТЕРИИ: \"не работаем с этой маркой\", \"нет специалиста\", \"нет оборудования\", \"не берем такие работы\", \"не наша специализация\".",
                6,
            ),
            (
                "9",
                "ПЕРЕШЛИ В МЕССЕНДЖЕР",
                "СТРОГО МЕССЕНДЖЕР: Целевой звонок с договоренностью обсудить детали в мессенджере. КРИТЕРИИ: Конкретные фразы \"напишу в WhatsApp\", \"отправлю в Telegram\", \"свяжемся в мессенджере\", \"перейдем в чат\".",
                5,
            ),
            (
                "10",
                "ЗАПЛАНИРОВАН ПЕРЕЗВОН",
                "СТРОГО ПЕРЕЗВОН: Целевой звонок с договоренностью созвониться позже в конкретное время. КРИТЕРИИ: Конкретное время перезвона \"перезвоню завтра\", \"созвонимся в пятницу\", \"перезвоню в 15:00\". КОНТЕКСТ: Проверь, состоялся ли обещанный перезвон.",
                4,
            ),
            (
                "11",
                "ПЕРЕАДРЕСАЦИЯ",
                "СТРОГО ПЕРЕАДРЕСАЦИЯ: Целевой звонок с перенаправлением в другой филиал/сервис по географическому принципу. КРИТЕРИИ: \"обратитесь в другой филиал\", \"мы не работаем в вашем районе\", \"ближе к вам другой сервис\".",
                3,
            ),
            (
                "12",
                "ОБЗВОН",
                "СТРОГО ОБЗВОН: Исходящий звонок ОТ СЕРВИСА клиенту с предложением услуг, акций, планового ТО, напоминаний о записи. КРИТЕРИИ: Звонок ИНИЦИИРОВАН сервисом, предложение услуг, напоминание о ТО, акции.",
                2,
            ),
            (
                "13",
                "ПОСЛЕДУЮЩИЙ КОНТАКТ",
                "СТРОГО ПОСЛЕДУЮЩИЙ: Звонок по УЖЕ СУЩЕСТВУЮЩЕЙ записи или автомобилю в ремонте. КРИТЕРИИ: ОБЯЗАТЕЛЬНО проверь историю - должен быть предыдущий звонок с записью (категория 2) или уже существующий автомобиль в сервисе. ВКЛЮЧАЕТ: подтверждение записи, уточнение времени записи, перенос времени записи, статус ремонта. ЗАПРЕТ: НИКОГДА не классифицируй первый звонок клиента как \"Последующий контакт\"!",
                1,
            ),
            (
                "14",
                "ДРУГОЕ",
                "СТРОГО ДРУГОЕ: Иные причины нецелевого звонка, которые не подходят под другие категории. КРИТЕРИИ: Неопределенные случаи, технические проблемы, неясные ситуации.",
                0,
            ),
        ]

        for category_id, category_name, rule_text, priority in default_rules:
            db.session.add(
                UserClassificationRule(
                    user_id=self.user_id,
                    category_id=category_id,
                    category_name=category_name,
                    rule_text=rule_text,
                    priority=priority,
                )
            )

        critical_rules = [
            (
                "СТРОГО: Первый звонок клиента",
                "КРИТИЧЕСКОЕ ПРАВИЛО: Если это ПЕРВЫЙ звонок клиента - НЕЛЬЗЯ классифицировать как \"Последующий контакт\" (13). ОБЯЗАТЕЛЬНО проверь историю звонков клиента перед классификацией категории 13.",
                "Защита от неправильной классификации первого звонка",
            ),
            (
                "СТРОГО: Последующий контакт",
                "КРИТИЧЕСКОЕ ПРАВИЛО: \"Последующий контакт\" (13) ТОЛЬКО если есть предыдущая запись (категория 2) или автомобиль уже в сервисе. БЕЗ предыдущей записи - это категория 3.",
                "Проверка наличия предыдущих записей",
            ),
            (
                "СТРОГО: Подтверждение записи",
                "КРИТИЧЕСКОЕ ПРАВИЛО: \"Подтверждение записи\" = ПОСЛЕДУЮЩИЙ КОНТАКТ (13), НЕ запись на сервис (2). Если клиент подтверждает уже существующую запись - это категория 13.",
                "Различение подтверждения и новой записи",
            ),
            (
                "СТРОГО: Уточнение времени",
                "КРИТИЧЕСКОЕ ПРАВИЛО: \"Уточнение времени записи\" = ПОСЛЕДУЮЩИЙ КОНТАКТ (13). Если клиент уточняет время уже существующей записи - это категория 13.",
                "Уточнение времени - это не новая запись",
            ),
            (
                "СТРОГО: Подумаю/перезвоню",
                "КРИТИЧЕСКОЕ ПРАВИЛО: \"Подумаю\", \"перезвоню\", \"найду решение\" = КОНСУЛЬТАЦИЯ (3), НЕ запись на сервис (2). Любые фразы сомнения - это категория 3.",
                "Различение размышлений и записи",
            ),
            (
                "СТРОГО: Уже нашел решение",
                "КРИТИЧЕСКОЕ ПРАВИЛО: \"Уже нашел решение\", \"уже решил проблему\" = КОНСУЛЬТАЦИЯ (3). Клиент уже решил проблему самостоятельно.",
                "Клиент уже решил проблему самостоятельно",
            ),
            (
                "СТРОГО: Временные интервалы",
                "КРИТИЧЕСКОЕ ПРАВИЛО: Учитывай временные интервалы между звонками. Если прошло много времени с последнего звонка - это может быть новый контакт.",
                "Анализ временных промежутков",
            ),
            (
                "СТРОГО: Последовательность",
                "КРИТИЧЕСКОЕ ПРАВИЛО: Анализируй последовательность: Запись (2) → Последующий контакт (13). Без записи не может быть последующего контакта.",
                "Логическая последовательность звонков",
            ),
            (
                "СТРОГО: Целевой звонок",
                "КРИТИЧЕСКОЕ ПРАВИЛО: Сначала определи целевой ли звонок (иномарка 2007+ г.в., автомобиль целиком). Если НЕ целевой - категория 1.",
                "Определение целевого звонка",
            ),
            (
                "СТРОГО: Конкретная запись",
                "КРИТИЧЕСКОЕ ПРАВИЛО: Для категории 2 (Запись на сервис) ОБЯЗАТЕЛЬНО должно быть конкретное время визита или в словах присудствуют приезжайте сейчас, или скоро буду и подобные. Без конкретного времени - это категория 3.",
                "Критерии записи на сервис",
            ),
            (
                "СТРОГО: Отказ vs Сомнение",
                "КРИТИЧЕСКОЕ ПРАВИЛО: Четко различай отказ (категория 4) и сомнение (категория 3). \"Не буду\" = отказ, \"подумаю\" = сомнение.",
                "Различение отказа и сомнения",
            ),
            (
                "СТРОГО: Приоритет правил",
                "КРИТИЧЕСКОЕ ПРАВИЛО: Соблюдай приоритет правил. Правила с высоким приоритетом проверяются первыми. Нецелевые звонки (категория 1) имеют наивысший приоритет.",
                "Соблюдение приоритетов",
            ),
        ]
        for name, rule_text, description in critical_rules:
            db.session.add(
                UserClassificationCriticalRule(
                    user_id=self.user_id, name=name, rule_text=rule_text, description=description
                )
            )
        db.session.commit()

    def get_system_prompts(self) -> List[Dict]:
        rows = (
            UserClassificationSystemPrompt.query.filter_by(user_id=self.user_id)
            .order_by(UserClassificationSystemPrompt.created_at.desc())
            .all()
        )
        return [self._prompt_row(p) for p in rows]

    @staticmethod
    def _prompt_row(p: UserClassificationSystemPrompt) -> Dict:
        return {
            "id": p.id,
            "name": p.name,
            "content": p.content,
            "is_active": bool(p.is_active),
            "created_at": _to_iso(p.created_at),
            "updated_at": _to_iso(p.updated_at),
            "description": p.description,
        }

    def get_active_system_prompt(self) -> Optional[Dict]:
        p = (
            UserClassificationSystemPrompt.query.filter_by(user_id=self.user_id, is_active=True)
            .order_by(UserClassificationSystemPrompt.updated_at.desc())
            .first()
        )
        return self._prompt_row(p) if p else None

    def add_system_prompt(self, name: str, content: str, description: str = "") -> bool:
        try:
            db.session.add(
                UserClassificationSystemPrompt(
                    user_id=self.user_id, name=name, content=content, description=description or ""
                )
            )
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка добавления промпта: {e}")
            return False

    def update_system_prompt(self, prompt_id: int, name: str, content: str, description: str = "") -> bool:
        try:
            p = UserClassificationSystemPrompt.query.filter_by(
                user_id=self.user_id, id=prompt_id
            ).first()
            if not p:
                return False
            p.name = name
            p.content = content
            p.description = description or ""
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка обновления промпта: {e}")
            return False

    def toggle_system_prompt_active(self, prompt_id: int) -> bool:
        try:
            UserClassificationSystemPrompt.query.filter_by(user_id=self.user_id).update(
                {"is_active": False}
            )
            p = UserClassificationSystemPrompt.query.filter_by(
                user_id=self.user_id, id=prompt_id
            ).first()
            if p:
                p.is_active = True
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка переключения промпта: {e}")
            return False

    def delete_system_prompt(self, prompt_id: int) -> bool:
        try:
            p = UserClassificationSystemPrompt.query.filter_by(
                user_id=self.user_id, id=prompt_id
            ).first()
            if p:
                db.session.delete(p)
                db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка удаления промпта: {e}")
            return False

    def get_classification_rules(self) -> List[Dict]:
        rows = (
            UserClassificationRule.query.filter_by(user_id=self.user_id)
            .order_by(UserClassificationRule.priority.desc(), UserClassificationRule.category_id)
            .all()
        )
        return [self._class_rule_row(r) for r in rows]

    @staticmethod
    def _class_rule_row(r: UserClassificationRule) -> Dict:
        return {
            "id": r.id,
            "category_id": r.category_id,
            "category_name": r.category_name,
            "rule_text": r.rule_text,
            "priority": r.priority,
            "is_active": bool(r.is_active),
            "created_at": _to_iso(r.created_at),
            "updated_at": _to_iso(r.updated_at),
            "examples": r.examples,
            "conditions": r.conditions,
        }

    def get_active_classification_rules(self) -> List[Dict]:
        rows = (
            UserClassificationRule.query.filter_by(user_id=self.user_id, is_active=True)
            .order_by(UserClassificationRule.priority.desc(), UserClassificationRule.category_id)
            .all()
        )
        return [self._class_rule_row(r) for r in rows]

    def add_classification_rule(
        self,
        category_id: str,
        category_name: str,
        rule_text: str,
        priority: int = 0,
        examples: str = "",
        conditions: str = "",
    ) -> bool:
        try:
            db.session.add(
                UserClassificationRule(
                    user_id=self.user_id,
                    category_id=category_id,
                    category_name=category_name,
                    rule_text=rule_text,
                    priority=priority,
                    examples=examples or None,
                    conditions=conditions or None,
                )
            )
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка добавления правила: {e}")
            return False

    def update_classification_rule(
        self,
        rule_id: int,
        category_id: str,
        category_name: str,
        rule_text: str,
        priority: int = 0,
        examples: str = "",
        conditions: str = "",
    ) -> bool:
        try:
            r = UserClassificationRule.query.filter_by(user_id=self.user_id, id=rule_id).first()
            if not r:
                return False
            r.category_id = category_id
            r.category_name = category_name
            r.rule_text = rule_text
            r.priority = priority
            r.examples = examples or None
            r.conditions = conditions or None
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка обновления правила: {e}")
            return False

    def toggle_classification_rule_active(self, rule_id: int) -> bool:
        try:
            r = UserClassificationRule.query.filter_by(user_id=self.user_id, id=rule_id).first()
            if r:
                r.is_active = not r.is_active
                db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка переключения правила: {e}")
            return False

    def delete_classification_rule(self, rule_id: int) -> bool:
        try:
            r = UserClassificationRule.query.filter_by(user_id=self.user_id, id=rule_id).first()
            if r:
                db.session.delete(r)
                db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка удаления правила: {e}")
            return False

    def get_critical_rules(self) -> List[Dict]:
        rows = (
            UserClassificationCriticalRule.query.filter_by(user_id=self.user_id)
            .order_by(UserClassificationCriticalRule.created_at.desc())
            .all()
        )
        return [self._crit_row(c) for c in rows]

    @staticmethod
    def _crit_row(c: UserClassificationCriticalRule) -> Dict:
        return {
            "id": c.id,
            "name": c.name,
            "rule_text": c.rule_text,
            "is_active": bool(c.is_active),
            "created_at": _to_iso(c.created_at),
            "updated_at": _to_iso(c.updated_at),
            "description": c.description,
        }

    def get_active_critical_rules(self) -> List[Dict]:
        rows = (
            UserClassificationCriticalRule.query.filter_by(user_id=self.user_id, is_active=True)
            .order_by(UserClassificationCriticalRule.created_at.desc())
            .all()
        )
        return [self._crit_row(c) for c in rows]

    def add_critical_rule(self, name: str, rule_text: str, description: str = "") -> bool:
        try:
            db.session.add(
                UserClassificationCriticalRule(
                    user_id=self.user_id, name=name, rule_text=rule_text, description=description or ""
                )
            )
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка добавления критического правила: {e}")
            return False

    def update_critical_rule(self, rule_id: int, name: str, rule_text: str, description: str = "") -> bool:
        try:
            c = UserClassificationCriticalRule.query.filter_by(
                user_id=self.user_id, id=rule_id
            ).first()
            if not c:
                return False
            c.name = name
            c.rule_text = rule_text
            c.description = description or ""
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка обновления критического правила: {e}")
            return False

    def toggle_critical_rule_active(self, rule_id: int) -> bool:
        try:
            c = UserClassificationCriticalRule.query.filter_by(
                user_id=self.user_id, id=rule_id
            ).first()
            if c:
                c.is_active = not c.is_active
                db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка переключения критического правила: {e}")
            return False

    def delete_critical_rule(self, rule_id: int) -> bool:
        try:
            c = UserClassificationCriticalRule.query.filter_by(
                user_id=self.user_id, id=rule_id
            ).first()
            if c:
                db.session.delete(c)
                db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка удаления критического правила: {e}")
            return False

    def get_auto_extracted_rules(self) -> List[Dict]:
        rows = (
            UserAutoExtractedRule.query.filter_by(user_id=self.user_id, is_active=True)
            .order_by(
                UserAutoExtractedRule.confidence.desc(), UserAutoExtractedRule.example_count.desc()
            )
            .all()
        )
        return [
            {
                "id": r.id,
                "rule_text": r.rule_text,
                "category_id": r.category_id,
                "confidence": r.confidence,
                "source_type": r.source_type,
                "example_count": r.example_count,
            }
            for r in rows
        ]

    def generate_system_prompt(
        self, call_history: str = "", training_examples: str = "", call_type: str = "Не определен"
    ) -> str:
        active_prompt = self.get_active_system_prompt()
        if not active_prompt:
            return "Ошибка: нет активного системного промпта"

        classification_rules = self.get_active_classification_rules()
        critical_rules = self.get_active_critical_rules()
        auto_extracted_rules = self.get_auto_extracted_rules()

        category_rules_text = ""
        for rule in classification_rules:
            category_rules_text += f"{rule['category_id']}. {rule['category_name']}: {rule['rule_text']}\n"
            if rule.get("examples"):
                category_rules_text += f"   Примеры: {rule['examples']}\n"
            if rule.get("conditions"):
                category_rules_text += f"   Условия: {rule['conditions']}\n"
            category_rules_text += "\n"

        auto_rules_text = ""
        if auto_extracted_rules:
            auto_rules_text = "АВТОМАТИЧЕСКИ ИЗВЛЕЧЁННЫЕ ПРАВИЛА (на основе частых ошибок):\n"
            for rule in auto_extracted_rules:
                confidence_stars = "⚠️" if rule["confidence"] >= 0.8 else "ℹ️"
                auto_rules_text += f"{confidence_stars} {rule['rule_text']} "
                auto_rules_text += f"(уверенность: {rule['confidence']:.0%}, примеров: {rule['example_count']})\n"
            auto_rules_text += "\n"

        critical_rules_text = ""
        for rule in critical_rules:
            critical_rules_text += f"- {rule['rule_text']}\n"

        prompt_content = active_prompt["content"]
        prompt_content = prompt_content.replace("{CALL_TYPE}", call_type)
        prompt_content = prompt_content.replace("{CALL_HISTORY}", call_history or "Нет истории звонков")
        prompt_content = prompt_content.replace(
            "{TRAINING_EXAMPLES}", training_examples or "Нет обучающих примеров"
        )
        prompt_content = prompt_content.replace("{CATEGORY_RULES}", category_rules_text)

        if auto_rules_text and "{AUTO_RULES}" not in prompt_content:
            if "{CRITICAL_RULES}" in prompt_content:
                prompt_content = prompt_content.replace("{CRITICAL_RULES}", auto_rules_text + "{CRITICAL_RULES}")
            else:
                prompt_content += "\n\n" + auto_rules_text
        elif "{AUTO_RULES}" in prompt_content:
            prompt_content = prompt_content.replace("{AUTO_RULES}", auto_rules_text)

        prompt_content = prompt_content.replace("{CRITICAL_RULES}", critical_rules_text)

        strict_format_block = """

ФИНАЛЬНЫЙ ФОРМАТ ОТВЕТА (обязателен всегда, даже если выше в промпте указано иначе):
Верни строго только две строки:
[КАТЕГОРИЯ:IN.* или OUT.*]
[ОБОСНОВАНИЕ:краткое понятное объяснение на русском языке, 1-3 предложения]

Правила финального ответа:
- только русский язык
- без markdown и списков
- без английских фраз вроде Category, Explanation, Summary, Here's why
- без дополнительного текста до или после этих двух строк
- код категории должен быть одним из допустимых кодов IN.* / OUT.*
"""

        if strict_format_block.strip() not in prompt_content:
            prompt_content = prompt_content.rstrip() + "\n" + strict_format_block

        return prompt_content

    def get_setting(self, key, default_value=None) -> Any:
        row = UserClassificationSetting.query.filter_by(
            user_id=self.user_id, setting_key=key
        ).first()
        return row.setting_value if row else default_value

    def set_setting(self, key, value, description=None) -> None:
        val = str(value) if value is not None else ""
        row = UserClassificationSetting.query.filter_by(
            user_id=self.user_id, setting_key=key
        ).first()
        if row:
            row.setting_value = val
            if description is not None:
                row.description = description
        else:
            db.session.add(
                UserClassificationSetting(
                    user_id=self.user_id, setting_key=key, setting_value=val, description=description
                )
            )
        db.session.commit()

    def get_all_settings(self) -> List[Dict]:
        rows = (
            UserClassificationSetting.query.filter_by(user_id=self.user_id)
            .order_by(UserClassificationSetting.setting_key)
            .all()
        )
        return [{"key": r.setting_key, "value": r.setting_value, "description": r.description} for r in rows]

    def add_classification_task(
        self, task_id, input_folder, output_file, context_days=0, operator_name=None
    ) -> None:
        h = UserClassificationHistory(
            user_id=self.user_id,
            task_id=str(task_id),
            input_folder=input_folder,
            output_file=output_file,
            context_days=int(context_days or 0),
            status="running",
            operator_name=operator_name,
        )
        db.session.add(h)
        db.session.commit()

    def update_classification_task(self, task_id, **kwargs) -> None:
        h = UserClassificationHistory.query.filter_by(
            user_id=self.user_id, task_id=str(task_id)
        ).first()
        if not h:
            return
        for key, value in kwargs.items():
            if key == "status" and value is not None:
                h.status = str(value)
            elif key == "total_files" and value is not None:
                h.total_files = int(value)
            elif key == "processed_files" and value is not None:
                h.processed_files = int(value)
            elif key == "corrections_count" and value is not None:
                h.corrections_count = int(value)
            elif key == "duration" and value is not None:
                h.duration = str(value)
            elif key == "error_message" and value is not None:
                h.error_message = str(value)
            elif key == "end_time" and value is not None:
                h.end_time = _parse_dt(value) or h.end_time
        db.session.commit()

    def get_classification_history(self, limit=10) -> List[Dict]:
        rows = (
            UserClassificationHistory.query.filter_by(user_id=self.user_id)
            .order_by(UserClassificationHistory.start_time.desc())
            .limit(int(limit))
            .all()
        )
        return [self._hist_dict(h) for h in rows]

    @staticmethod
    def _hist_dict(h: UserClassificationHistory) -> Dict:
        return {
            "task_id": h.task_id,
            "input_folder": h.input_folder,
            "output_file": h.output_file,
            "context_days": h.context_days,
            "status": h.status,
            "total_files": h.total_files,
            "processed_files": h.processed_files,
            "corrections_count": h.corrections_count,
            "start_time": _to_iso(h.start_time),
            "end_time": _to_iso(h.end_time),
            "duration": h.duration,
            "error_message": h.error_message,
            "operator_name": h.operator_name,
        }

    def get_classification_task(self, task_id) -> Optional[Dict]:
        h = UserClassificationHistory.query.filter_by(
            user_id=self.user_id, task_id=str(task_id)
        ).first()
        return self._hist_dict(h) if h else None

    def _normalize_schedule_config(self, schedule_config) -> Any:
        if schedule_config is None:
            return {}
        if isinstance(schedule_config, dict):
            return schedule_config
        if isinstance(schedule_config, str):
            try:
                return json.loads(schedule_config)
            except json.JSONDecodeError:
                return {}
        return {}

    def add_schedule(
        self, name, description, input_folder, context_days, schedule_type, schedule_config, created_by=None
    ):
        cfg = self._normalize_schedule_config(schedule_config)
        if not isinstance(cfg, dict):
            cfg = {}
        next_run_iso = self._calculate_next_run(schedule_type, json.dumps(cfg, ensure_ascii=False))
        s = UserClassificationSchedule(
            user_id=self.user_id,
            name=name,
            description=description,
            input_folder=input_folder,
            context_days=int(context_days or 0),
            schedule_type=schedule_type,
            schedule_config=cfg,
            created_by=created_by,
            next_run=_parse_dt(next_run_iso),
        )
        db.session.add(s)
        db.session.commit()
        return s.id

    def update_schedule(self, schedule_id, **kwargs) -> None:
        s = UserClassificationSchedule.query.filter_by(
            user_id=self.user_id, id=int(schedule_id)
        ).first()
        if not s:
            return
        allowed = {
            "name",
            "description",
            "input_folder",
            "context_days",
            "schedule_type",
            "schedule_config",
            "is_active",
            "next_run",
        }
        for key, value in kwargs.items():
            if key not in allowed:
                continue
            if key == "schedule_config":
                s.schedule_config = self._normalize_schedule_config(value)
            elif key == "context_days" and value is not None:
                s.context_days = int(value)
            elif key == "is_active" and value is not None:
                s.is_active = bool(value)
            elif key == "next_run" and value is not None:
                s.next_run = _parse_dt(value) if not isinstance(value, datetime) else value
            elif hasattr(s, key):
                setattr(s, key, value)
        db.session.commit()

    def get_schedules(self, active_only=True) -> List[Dict]:
        q = UserClassificationSchedule.query.filter_by(user_id=self.user_id)
        if active_only:
            q = q.filter_by(is_active=True)
        rows = q.order_by(UserClassificationSchedule.next_run.asc()).all()
        return [self._sched_dict(s) for s in rows]

    @staticmethod
    def _sched_dict(s: UserClassificationSchedule) -> Dict:
        cfg = s.schedule_config
        if isinstance(cfg, dict):
            cfg_str = json.dumps(cfg, ensure_ascii=False)
        else:
            cfg_str = str(cfg) if cfg is not None else "{}"
        return {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "input_folder": s.input_folder,
            "context_days": s.context_days,
            "schedule_type": s.schedule_type,
            "schedule_config": cfg_str,
            "is_active": bool(s.is_active),
            "last_run": _to_iso(s.last_run),
            "next_run": _to_iso(s.next_run),
            "created_at": _to_iso(s.created_at),
            "created_by": s.created_by,
            "run_count": s.run_count,
            "success_count": s.success_count,
            "error_count": s.error_count,
        }

    def get_schedule(self, schedule_id) -> Optional[Dict]:
        s = UserClassificationSchedule.query.filter_by(
            user_id=self.user_id, id=int(schedule_id)
        ).first()
        return self._sched_dict(s) if s else None

    def delete_schedule(self, schedule_id) -> None:
        s = UserClassificationSchedule.query.filter_by(
            user_id=self.user_id, id=int(schedule_id)
        ).first()
        if s:
            db.session.delete(s)
            db.session.commit()

    def update_schedule_run_stats(self, schedule_id, success=True) -> None:
        s = UserClassificationSchedule.query.filter_by(
            user_id=self.user_id, id=int(schedule_id)
        ).first()
        if not s:
            return
        s.run_count = int(s.run_count or 0) + 1
        if success:
            s.success_count = int(s.success_count or 0) + 1
        else:
            s.error_count = int(s.error_count or 0) + 1
        s.last_run = datetime.utcnow()
        db.session.commit()

    def get_due_schedules(self) -> List[Dict]:
        now = datetime.now()
        rows = (
            UserClassificationSchedule.query.filter_by(user_id=self.user_id, is_active=True)
            .filter(UserClassificationSchedule.next_run != None)  # noqa: E711
            .filter(UserClassificationSchedule.next_run <= now)
            .order_by(UserClassificationSchedule.next_run.asc())
            .all()
        )
        out = []
        for s in rows:
            cfg = s.schedule_config
            cfg_str = json.dumps(cfg, ensure_ascii=False) if isinstance(cfg, dict) else str(cfg or "{}")
            out.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "input_folder": s.input_folder,
                    "context_days": s.context_days,
                    "schedule_type": s.schedule_type,
                    "schedule_config": cfg_str,
                    "next_run": _to_iso(s.next_run),
                }
            )
        return out

    def update_next_run(self, schedule_id) -> None:
        s = UserClassificationSchedule.query.filter_by(
            user_id=self.user_id, id=int(schedule_id)
        ).first()
        if not s:
            return
        cfg = s.schedule_config or {}
        nriso = self._calculate_next_run(s.schedule_type, json.dumps(cfg, ensure_ascii=False))
        s.next_run = _parse_dt(nriso)
        db.session.commit()

    def _calculate_next_run(self, schedule_type, schedule_config) -> str:
        from datetime import datetime, timedelta

        try:
            if isinstance(schedule_config, str):
                config = json.loads(schedule_config) if schedule_config else {}
            elif isinstance(schedule_config, dict):
                config = schedule_config
            else:
                config = {}
        except Exception:
            config = {}

        now = datetime.now()

        if schedule_type == "daily":
            hour = config.get("hour", 9)
            minute = config.get("minute", 0)
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
        elif schedule_type == "weekly":
            days = config.get("days", [1])
            hour = config.get("hour", 9)
            minute = config.get("minute", 0)
            current_weekday = now.weekday() + 1
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
        elif schedule_type == "monthly":
            day = config.get("day", 1)
            hour = config.get("hour", 9)
            minute = config.get("minute", 0)
            if now.day < day:
                next_run = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
            else:
                if now.month == 12:
                    next_run = now.replace(
                        year=now.year + 1, month=1, day=day, hour=hour, minute=minute, second=0, microsecond=0
                    )
                else:
                    next_run = now.replace(
                        month=now.month + 1, day=day, hour=hour, minute=minute, second=0, microsecond=0
                    )
        else:
            next_run = now + timedelta(days=1)
            next_run = next_run.replace(hour=9, minute=0, second=0, microsecond=0)

        return next_run.isoformat()
