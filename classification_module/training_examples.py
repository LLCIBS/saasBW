"""
Система управления обучающими примерами для классификации звонков (PostgreSQL).
"""

from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from database.models import UserClassificationMetric, UserCorrectionHistory, UserTrainingExample, db


class TrainingExamplesManager:
    """Менеджер обучающих примеров (per user_id)."""

    def __init__(
        self,
        user_id: Optional[int] = None,
        db_path: Any = None,
        classification_root: Any = None,
        **_: Any,
    ) -> None:
        uid = user_id
        if uid is None:
            env_uid = os.environ.get("CLASSIFICATION_USER_ID")
            uid = int(env_uid) if env_uid and str(env_uid).isdigit() else None
        if uid is None or int(uid) <= 0:
            raise ValueError(
                "TrainingExamplesManager требует user_id=... или CLASSIFICATION_USER_ID"
            )
        self.user_id = int(uid)
        self.db_path = str(db_path) if db_path else ""
        self._classification_root: Optional[Path] = None
        if classification_root is not None:
            self._classification_root = Path(classification_root).resolve()
        elif self.db_path and str(self.db_path).endswith(".db"):
            self._classification_root = Path(self.db_path).resolve().parent

    def add_training_example(
        self,
        transcription: str,
        correct_category: str,
        correct_reasoning: str,
        original_category: str = None,
        original_reasoning: str = None,
        operator_comment: str = None,
    ) -> bool:
        try:
            transcription_hash = hashlib.md5(transcription.encode("utf-8")).hexdigest()
            ex = (
                UserTrainingExample.query.filter_by(
                    user_id=self.user_id, transcription_hash=transcription_hash
                )
                .first()
            )
            if ex:
                ex.correct_category = correct_category
                ex.correct_reasoning = correct_reasoning
                ex.original_category = original_category
                ex.original_reasoning = original_reasoning
                ex.operator_comment = operator_comment
                ex.created_at = datetime.utcnow()
            else:
                ex = UserTrainingExample(
                    user_id=self.user_id,
                    transcription_hash=transcription_hash,
                    transcription=transcription,
                    correct_category=correct_category,
                    correct_reasoning=correct_reasoning,
                    original_category=original_category,
                    original_reasoning=original_reasoning,
                    operator_comment=operator_comment,
                )
                db.session.add(ex)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка при добавлении обучающего примера: {e}")
            return False

    def get_training_examples(self, category: str = None, limit: int = 10) -> List[Dict]:
        q = UserTrainingExample.query.filter_by(user_id=self.user_id, is_active=True)
        if category:
            q = q.filter_by(correct_category=category)
        rows = (
            q.order_by(UserTrainingExample.used_count.asc(), UserTrainingExample.created_at.desc())
            .limit(int(limit))
            .all()
        )
        examples = [
            {
                "transcription": r.transcription,
                "category": r.correct_category,
                "reasoning": r.correct_reasoning,
                "used_count": r.used_count,
            }
            for r in rows
        ]
        if examples:
            transcriptions = [ex["transcription"] for ex in examples]
            for r in UserTrainingExample.query.filter(
                UserTrainingExample.user_id == self.user_id,
                UserTrainingExample.transcription.in_(transcriptions),
            ).all():
                r.used_count = int(r.used_count or 0) + 1
            db.session.commit()
        return examples

    def get_similar_examples(self, transcription: str, limit: int = 3) -> List[Dict]:
        keywords = self._extract_keywords(transcription)
        examples: List[Dict] = []
        for keyword in keywords[:5]:
            rows = (
                UserTrainingExample.query.filter(
                    UserTrainingExample.user_id == self.user_id,
                    UserTrainingExample.is_active == True,  # noqa: E712
                    UserTrainingExample.transcription.like(f"%{keyword}%"),
                )
                .limit(limit)
                .all()
            )
            for r in rows:
                example = {
                    "transcription": r.transcription,
                    "category": r.correct_category,
                    "reasoning": r.correct_reasoning,
                }
                if example not in examples:
                    examples.append(example)
                if len(examples) >= limit:
                    return examples
        return examples

    def _extract_keywords(self, text: str) -> List[str]:
        important_words = [
            "запись",
            "записать",
            "записывайте",
            "согласен",
            "подходит",
            "отказ",
            "не нужно",
            "не интересно",
            "подумаю",
            "перезвоню",
            "дорого",
            "не по карману",
            "занято",
            "нет времени",
            "не выполняем",
            "свои запчасти",
            "мессенджер",
            "whatsapp",
            "telegram",
            "обзвон",
            "акция",
            "предложение",
            "то",
            "техобслуживание",
            "переадресация",
            "другой сервис",
            "другой адрес",
        ]
        text_lower = text.lower()
        return [w for w in important_words if w in text_lower]

    def add_correction(
        self,
        phone_number: str,
        call_date: str,
        call_time: str,
        station: str,
        original_category: str,
        corrected_category: str,
        original_reasoning: str,
        corrected_reasoning: str,
        operator_name: str = None,
    ) -> bool:
        try:
            db.session.add(
                UserCorrectionHistory(
                    user_id=self.user_id,
                    phone_number=phone_number,
                    call_date=call_date,
                    call_time=call_time,
                    station=station,
                    original_category=original_category,
                    corrected_category=corrected_category,
                    original_reasoning=original_reasoning,
                    corrected_reasoning=corrected_reasoning,
                    operator_name=operator_name,
                )
            )
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка при добавлении корректировки: {e}")
            return False

    def update_daily_metrics(
        self, date_str: str, total_calls: int, correct_classifications: int, corrections_made: int
    ) -> None:
        try:
            d = date.fromisoformat(str(date_str)[:10])
        except ValueError:
            d = date.today()
        accuracy_rate = (correct_classifications / total_calls * 100) if total_calls > 0 else 0.0
        m = (
            UserClassificationMetric.query.filter_by(
                user_id=self.user_id, metric_date=d
            )
            .first()
        )
        if m:
            m.total_calls = total_calls
            m.correct_classifications = correct_classifications
            m.corrections_made = corrections_made
            m.accuracy_rate = accuracy_rate
        else:
            db.session.add(
                UserClassificationMetric(
                    user_id=self.user_id,
                    metric_date=d,
                    total_calls=total_calls,
                    correct_classifications=correct_classifications,
                    corrections_made=corrections_made,
                    accuracy_rate=accuracy_rate,
                )
            )
        db.session.commit()

    def get_metrics_summary(self, days: int = 30) -> Dict:
        from sqlalchemy import func

        training_stats = db.session.query(
            func.count(UserTrainingExample.id), func.avg(UserTrainingExample.used_count)
        ).filter(UserTrainingExample.user_id == self.user_id, UserTrainingExample.is_active == True).first()  # noqa: E712

        since = date.today() - timedelta(days=days)
        mrows = (
            UserClassificationMetric.query.filter(
                UserClassificationMetric.user_id == self.user_id,
                UserClassificationMetric.metric_date >= since,
            )
            .all()
        )
        total_calls = sum((r.total_calls or 0) for r in mrows)
        correct_c = sum((r.correct_classifications or 0) for r in mrows)
        corrections_m = sum((r.corrections_made or 0) for r in mrows)
        avg_acc = (
            sum((r.accuracy_rate or 0) for r in mrows) / len(mrows) if mrows else 0.0
        )

        since_dt = datetime.utcnow() - timedelta(days=days)
        from sqlalchemy import func as sfunc

        top_rows = (
            db.session.query(
                UserCorrectionHistory.original_category,
                UserCorrectionHistory.corrected_category,
                sfunc.count().label("cnt"),
            )
            .filter(
                UserCorrectionHistory.user_id == self.user_id,
                UserCorrectionHistory.correction_date >= since_dt,
            )
            .group_by(
                UserCorrectionHistory.original_category,
                UserCorrectionHistory.corrected_category,
            )
            .order_by(sfunc.count().desc())
            .limit(10)
            .all()
        )
        return {
            "training_examples": int(training_stats[0] or 0) if training_stats else 0,
            "avg_example_usage": round(float(training_stats[1] or 0), 2) if training_stats else 0.0,
            "total_calls": total_calls,
            "correct_classifications": correct_c,
            "corrections_made": corrections_m,
            "accuracy_rate": round(avg_acc, 2),
            "top_errors": [
                {"original": t[0], "corrected": t[1], "count": t[2]} for t in top_rows
            ],
        }

    def get_all_examples(self) -> List[Dict]:
        rows = (
            UserTrainingExample.query.filter_by(user_id=self.user_id)
            .order_by(UserTrainingExample.created_at.desc())
            .all()
        )
        return [
            {
                "id": r.id,
                "transcription": r.transcription,
                "correct_category": r.correct_category,
                "correct_reasoning": r.correct_reasoning,
                "original_category": r.original_category,
                "original_reasoning": r.original_reasoning,
                "operator_comment": r.operator_comment,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "used_count": r.used_count,
                "is_active": bool(r.is_active),
            }
            for r in rows
        ]

    def toggle_example_status(self, example_id: int) -> bool:
        try:
            r = UserTrainingExample.query.filter_by(
                user_id=self.user_id, id=example_id
            ).first()
            if r:
                r.is_active = not r.is_active
                db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка при изменении статуса примера: {e}")
            return False

    def delete_example(self, example_id: int) -> bool:
        try:
            r = UserTrainingExample.query.filter_by(
                user_id=self.user_id, id=example_id
            ).first()
            if r:
                db.session.delete(r)
                db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка при удалении примера: {e}")
            return False


# Глобальный экземпляр больше не используется (нужен user_id)
training_manager = None  # type: ignore
