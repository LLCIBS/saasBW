#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Система автоматического самообучения (PostgreSQL / SQLAlchemy).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from database.models import (
    UserAutoExtractedRule,
    UserClassificationSuccessStat,
    UserCorrectClassification,
    UserCorrectionHistory,
    UserExampleEffectiveness,
    UserSuccessPattern,
    UserTrainingExample,
    db,
)


class SelfLearningSystem:
    """Система автоматического самообучения с подтверждениями"""

    def __init__(self, user_id: Optional[int] = None) -> None:
        uid = user_id
        if uid is None:
            env_uid = os.environ.get("CLASSIFICATION_USER_ID")
            uid = int(env_uid) if env_uid and str(env_uid).isdigit() else None
        if uid is None or int(uid) <= 0:
            raise ValueError(
                "SelfLearningSystem требует user_id=... или CLASSIFICATION_USER_ID"
            )
        self.user_id = int(uid)

    def init_learning_tables(self) -> None:
        """Схема создаётся в PostgreSQL (db.create_all / миграции)."""
        pass

    def init_rules_tables(self) -> None:
        pass

    def mark_as_correct(
        self,
        phone_number: str,
        call_date: str,
        call_time: str,
        category: str,
        reasoning: str,
        transcription: str,
        confirmed_by: str,
        confidence_level: int = 5,
        comment: str = "",
    ) -> bool:
        import logging

        logger = logging.getLogger(__name__)
        try:
            transcription_hash = hashlib.md5(transcription.encode("utf-8")).hexdigest()
            existing = (
                UserCorrectClassification.query.filter_by(
                    user_id=self.user_id,
                    phone_number=phone_number,
                    call_date=call_date,
                    call_time=call_time,
                )
                .first()
            )
            if existing:
                existing.category = category
                existing.reasoning = reasoning
                existing.transcription_hash = transcription_hash
                existing.confidence_level = int(confidence_level)
                existing.comment = comment or ""
                existing.confirmed_by = confirmed_by
                existing.confirmed_at = datetime.utcnow()
            else:
                db.session.add(
                    UserCorrectClassification(
                        user_id=self.user_id,
                        phone_number=phone_number,
                        call_date=call_date,
                        call_time=call_time,
                        category=category,
                        reasoning=reasoning,
                        transcription_hash=transcription_hash,
                        confirmed_by=confirmed_by,
                        confidence_level=int(confidence_level),
                        comment=comment or "",
                    )
                )
            db.session.commit()
            try:
                self._update_category_success_stats(category, is_correct=True)
            except Exception as se:
                logger.warning("Ошибка при обновлении статистики: %s", se)
            try:
                self._update_success_patterns(transcription, category, reasoning)
            except Exception as pe:
                logger.warning("Ошибка при обновлении паттернов: %s", pe)
            try:
                self._improve_example_effectiveness(transcription, category)
            except Exception as ee:
                logger.warning("Ошибка при обновлении эффективности: %s", ee)
            return True
        except Exception as e:
            logger.exception("Ошибка при отметке как правильной: %s", e)
            db.session.rollback()
            return False

    def _update_category_success_stats(self, category: str, is_correct: bool = True) -> None:
        row = (
            UserClassificationSuccessStat.query.filter_by(
                user_id=self.user_id, category=category
            )
            .first()
        )
        if row:
            total = int(row.total_classified or 0) + 1
            confirmed = int(row.confirmed_correct or 0) + (1 if is_correct else 0)
            corrections = int(row.corrections_count or 0) + (0 if is_correct else 1)
            row.total_classified = total
            row.confirmed_correct = confirmed
            row.corrections_count = corrections
            row.success_rate = (confirmed / total * 100) if total > 0 else 0.0
            row.last_updated = datetime.utcnow()
        else:
            if is_correct:
                db.session.add(
                    UserClassificationSuccessStat(
                        user_id=self.user_id,
                        category=category,
                        total_classified=1,
                        confirmed_correct=1,
                        corrections_count=0,
                        success_rate=100.0,
                    )
                )
            else:
                db.session.add(
                    UserClassificationSuccessStat(
                        user_id=self.user_id,
                        category=category,
                        total_classified=1,
                        confirmed_correct=0,
                        corrections_count=1,
                        success_rate=0.0,
                    )
                )
        db.session.commit()

    def _update_success_patterns(self, transcription: str, category: str, reasoning: str) -> None:
        keywords = self._extract_keywords_from_text(transcription)
        row = (
            UserSuccessPattern.query.filter_by(
                user_id=self.user_id, category=category, is_active=True
            )
            .order_by(UserSuccessPattern.confirmation_count.desc())
            .first()
        )
        if row:
            existing_keywords = json.loads(row.common_keywords) if row.common_keywords else []
            combined = list(set(existing_keywords + keywords))[:20]
            samples = json.loads(row.transcription_samples) if row.transcription_samples else []
            sample_text = transcription[:200]
            if sample_text not in samples:
                samples.append(sample_text)
                samples = samples[-10:]
            row.common_keywords = json.dumps(combined, ensure_ascii=False)
            row.transcription_samples = json.dumps(samples, ensure_ascii=False)
            row.confirmation_count = int(row.confirmation_count or 0) + 1
            row.last_confirmed = datetime.utcnow()
        else:
            db.session.add(
                UserSuccessPattern(
                    user_id=self.user_id,
                    category=category,
                    common_keywords=json.dumps(keywords, ensure_ascii=False),
                    transcription_samples=json.dumps([transcription[:200]], ensure_ascii=False),
                    confirmation_count=1,
                )
            )
        db.session.commit()

    def _improve_example_effectiveness(self, transcription: str, category: str) -> None:
        example_ids = [
            r.id
            for r in UserTrainingExample.query.filter_by(
                user_id=self.user_id, correct_category=category, is_active=True
            ).all()
        ]
        transcription_keywords = set(self._extract_keywords_from_text(transcription))
        for ex_id in example_ids:
            ex = UserTrainingExample.query.filter_by(
                user_id=self.user_id, id=ex_id
            ).first()
            if not ex:
                continue
            ex_keywords = set(self._extract_keywords_from_text(ex.transcription))
            similarity = len(transcription_keywords & ex_keywords) / max(
                len(transcription_keywords | ex_keywords), 1
            )
            if similarity <= 0.3:
                continue
            eff = UserExampleEffectiveness.query.filter_by(
                user_id=self.user_id, example_id=ex_id
            ).first()
            if eff:
                tc = int(eff.times_confirmed or 0) + 1
                eff.times_confirmed = tc
                tu = max(int(eff.times_used or 0), 1)
                eff.success_rate = tc / tu
                eff.last_used = datetime.utcnow()
            else:
                db.session.add(
                    UserExampleEffectiveness(
                        user_id=self.user_id,
                        example_id=ex_id,
                        times_confirmed=1,
                        success_rate=1.0,
                        last_used=datetime.utcnow(),
                    )
                )
        db.session.commit()

    def _extract_keywords_from_text(self, text: str) -> List[str]:
        stop_words = {
            "это",
            "что",
            "как",
            "так",
            "для",
            "или",
            "если",
            "но",
            "да",
            "нет",
            "он",
            "она",
            "они",
            "мы",
            "вы",
            "меня",
            "тебя",
            "его",
            "её",
            "быть",
            "был",
            "была",
            "было",
            "были",
            "в",
            "на",
            "с",
            "по",
            "от",
            "до",
            "из",
            "за",
            "под",
            "над",
            "к",
            "о",
            "об",
            "со",
            "во",
            "при",
        }
        words = re.findall(r"\b[а-яё]{4,}\b", text.lower())
        keywords = [w for w in words if w not in stop_words]
        word_counts = Counter(keywords)
        return [word for word, count in word_counts.most_common(15)]

    def get_category_success_stats(self) -> Dict[str, Dict]:
        rows = UserClassificationSuccessStat.query.filter_by(user_id=self.user_id).all()
        stats = {}
        for r in rows:
            stats[r.category] = {
                "total": r.total_classified,
                "confirmed_correct": r.confirmed_correct,
                "corrections": r.corrections_count,
                "success_rate": r.success_rate,
                "accuracy": r.success_rate,
            }
        return stats

    def get_success_patterns_for_category(self, category: str) -> List[Dict]:
        rows = (
            UserSuccessPattern.query.filter_by(
                user_id=self.user_id, category=category, is_active=True
            )
            .order_by(UserSuccessPattern.confirmation_count.desc())
            .all()
        )
        patterns = []
        for row in rows:
            patterns.append(
                {
                    "id": row.id,
                    "keywords": json.loads(row.common_keywords) if row.common_keywords else [],
                    "samples": json.loads(row.transcription_samples)
                    if row.transcription_samples
                    else [],
                    "confirmation_count": row.confirmation_count,
                    "success_rate": row.success_rate,
                }
            )
        return patterns

    def analyze_learning_progress(self, days: int = 30) -> Dict:
        since = datetime.utcnow() - timedelta(days=days)
        prev_since = datetime.utcnow() - timedelta(days=days * 2)

        from sqlalchemy import func

        confirmations = db.session.query(
            func.count(UserCorrectClassification.id),
            func.count(func.distinct(UserCorrectClassification.category)),
            func.avg(UserCorrectClassification.confidence_level),
        ).filter(
            UserCorrectClassification.user_id == self.user_id,
            UserCorrectClassification.confirmed_at >= since,
        ).first()

        corrections = (
            UserCorrectionHistory.query.filter(
                UserCorrectionHistory.user_id == self.user_id,
                UserCorrectionHistory.correction_date >= since,
            )
            .count()
        )
        total_confirmations = int(confirmations[0] or 0) if confirmations else 0
        total_interactions = total_confirmations + corrections
        prev_confirmations = (
            UserCorrectClassification.query.filter(
                UserCorrectClassification.user_id == self.user_id,
                UserCorrectClassification.confirmed_at >= prev_since,
                UserCorrectClassification.confirmed_at < since,
            ).count()
        )
        prev_corrections = (
            UserCorrectionHistory.query.filter(
                UserCorrectionHistory.user_id == self.user_id,
                UserCorrectionHistory.correction_date >= prev_since,
                UserCorrectionHistory.correction_date < since,
            ).count()
        )
        prev_total = prev_confirmations + prev_corrections
        current_accuracy = (
            (total_confirmations / total_interactions * 100) if total_interactions > 0 else 0.0
        )
        accuracy_improvement = 0.0
        if prev_total > 0:
            prev_accuracy = (prev_confirmations / prev_total * 100) if prev_total > 0 else 0.0
            accuracy_improvement = current_accuracy - prev_accuracy

        return {
            "period_days": days,
            "total_confirmations": total_confirmations,
            "total_corrections": corrections,
            "total_interactions": total_interactions,
            "current_accuracy": current_accuracy,
            "accuracy_improvement": accuracy_improvement,
            "categories_confirmed": int(confirmations[1] or 0) if confirmations else 0,
            "avg_confidence": float(confirmations[2] or 0) if confirmations else 0.0,
        }

    def analyze_error_patterns(self, days: int = 30) -> List[Dict]:
        since = datetime.utcnow() - timedelta(days=days)
        rows = (
            UserCorrectionHistory.query.filter(
                UserCorrectionHistory.user_id == self.user_id,
                UserCorrectionHistory.correction_date >= since,
            )
            .all()
        )
        error_transitions = defaultdict(list)
        for c in rows:
            key = f"{c.original_category}→{c.corrected_category}"
            error_transitions[key].append(
                {
                    "original_reasoning": c.original_reasoning or "",
                    "corrected_reasoning": c.corrected_reasoning or "",
                }
            )
        patterns: List[Dict] = []
        for transition, examples in error_transitions.items():
            if len(examples) < 2:
                continue
            if "→" not in transition:
                continue
            orig_cat, corr_cat = transition.split("→", 1)
            all_reasonings = [ex["original_reasoning"] for ex in examples]
            common_keywords = self._find_common_keywords(all_reasonings)
            patterns.append(
                {
                    "transition": transition,
                    "original_category": orig_cat,
                    "corrected_category": corr_cat,
                    "frequency": len(examples),
                    "confidence": min(len(examples) / 10.0, 1.0),
                    "common_keywords": common_keywords,
                    "examples": examples[:5],
                }
            )
        patterns.sort(key=lambda x: x["frequency"], reverse=True)
        return patterns

    def _find_common_keywords(self, texts: List[str]) -> List[str]:
        all_words: List[str] = []
        for text in texts:
            words = re.findall(r"\b[а-яё]{4,}\b", (text or "").lower())
            all_words.extend(words)
        word_counts = Counter(all_words)
        threshold = len(texts) * 0.5
        if threshold < 1:
            threshold = 1
        common = [word for word, count in word_counts.items() if count >= threshold]
        return common[:10]

    def auto_update_rules(self, min_confidence: float = 0.7) -> int:
        patterns = self.analyze_error_patterns(days=30)
        updated = 0
        for pattern in patterns:
            if pattern["confidence"] < min_confidence:
                continue
            orig_cat = pattern["original_category"]
            corr_cat = pattern["corrected_category"]
            keywords = pattern["common_keywords"]
            if keywords:
                rule_text = (
                    f"ВНИМАНИЕ: Если в транскрипции встречаются фразы: {', '.join(keywords[:3])}, "
                    f"то НЕ классифицировать как {orig_cat}. Вероятно это {corr_cat}."
                )
            else:
                rule_text = (
                    f"ПАТТЕРН ОШИБКИ: Частая ошибка {orig_cat}→{corr_cat}. "
                    f"Проверяй внимательнее эту категорию."
                )
            like_part = f"%{orig_cat}→{corr_cat}%"
            exists = (
                UserAutoExtractedRule.query.filter(
                    UserAutoExtractedRule.user_id == self.user_id,
                    UserAutoExtractedRule.category_id == orig_cat,
                    UserAutoExtractedRule.rule_text.like(like_part),
                )
                .first()
            )
            if not exists:
                db.session.add(
                    UserAutoExtractedRule(
                        user_id=self.user_id,
                        rule_text=rule_text,
                        category_id=orig_cat,
                        confidence=pattern["confidence"],
                        source_type="error_pattern",
                        example_count=pattern["frequency"],
                        is_active=True,
                    )
                )
                updated += 1
        db.session.commit()
        return updated

    def analyze_example_effectiveness(self) -> Dict:
        ex_rows = (
            UserTrainingExample.query.filter_by(
                user_id=self.user_id, is_active=True
            )
            .all()
        )
        eff_map: Dict[int, Any] = {}
        for e in UserExampleEffectiveness.query.filter_by(user_id=self.user_id).all():
            eff_map[e.example_id] = (e.times_used, e.times_confirmed, e.times_misled, e.success_rate or 0.0)
        effective_examples = []
        ineffective_examples = []
        for r in ex_rows:
            ex_id = r.id
            if int(r.used_count or 0) == 0:
                continue
            eff = eff_map.get(
                ex_id, (0, 0, 0, 0.5)
            )
            times_used, times_confirmed, times_misled, success_rate = eff[0], eff[1], eff[2], eff[3]
            if int(r.used_count or 0) > 0 and times_used == 0 and times_confirmed == 0:
                effectiveness_score = 0.5
            else:
                effectiveness_score = success_rate
            if effectiveness_score >= 0.7:
                effective_examples.append(
                    {
                        "id": ex_id,
                        "score": effectiveness_score,
                        "used_count": r.used_count,
                        "times_confirmed": times_confirmed,
                    }
                )
            elif effectiveness_score < 0.3 and (r.used_count or 0) >= 5:
                ineffective_examples.append(
                    {
                        "id": ex_id,
                        "score": effectiveness_score,
                        "used_count": r.used_count,
                        "times_misled": times_misled,
                    }
                )
        return {
            "effective_count": len(effective_examples),
            "ineffective_count": len(ineffective_examples),
            "effective_examples": effective_examples[:10],
            "ineffective_examples": ineffective_examples[:10],
        }

    def suggest_example_improvements(self) -> List[Dict]:
        effectiveness = self.analyze_example_effectiveness()
        suggestions: List[Dict] = []
        for ex in effectiveness["ineffective_examples"]:
            suggestions.append(
                {
                    "type": "deactivate",
                    "example_id": ex["id"],
                    "reason": f'Низкая эффективность ({ex["score"]:.2%}), используется {ex["used_count"]} раз',
                    "priority": "high",
                }
            )
        patterns = self.analyze_error_patterns(days=7)
        for pattern in patterns[:5]:
            if pattern["frequency"] >= 3:
                suggestions.append(
                    {
                        "type": "add_examples",
                        "category": pattern["corrected_category"],
                        "reason": f'Частая ошибка {pattern["original_category"]}→{pattern["corrected_category"]} ({pattern["frequency"]} раз)',
                        "suggested_keywords": pattern["common_keywords"][:5],
                        "priority": "medium",
                    }
                )
        return suggestions

    def learn_from_successful_classifications(self, min_count: int = 5) -> List[Dict]:
        since = datetime.utcnow() - timedelta(days=30)
        from sqlalchemy import func

        q = (
            db.session.query(
                UserCorrectClassification.category,
                func.count(UserCorrectClassification.id),
            )
            .filter(
                UserCorrectClassification.user_id == self.user_id,
                UserCorrectClassification.confirmed_at >= since,
            )
            .group_by(UserCorrectClassification.category)
            .having(func.count(UserCorrectClassification.id) >= min_count)
            .all()
        )
        successful_patterns: List[Dict] = []
        for category, _cnt in q:
            rows = (
                UserCorrectClassification.query.filter(
                    UserCorrectClassification.user_id == self.user_id,
                    UserCorrectClassification.category == category,
                    UserCorrectClassification.confirmed_at >= since,
                )
                .limit(10)
                .all()
            )
            texts = [r.reasoning or "" for r in rows if r.reasoning]
            if not texts:
                continue
            common_words = self._find_common_keywords(texts)
            successful_patterns.append(
                {
                    "category": category,
                    "common_keywords": common_words,
                    "example_count": len(rows),
                    "confidence": 0.9,
                }
            )
        return successful_patterns

    def generate_learning_report(self) -> Dict:
        patterns = self.analyze_error_patterns(days=30)
        effectiveness = self.analyze_example_effectiveness()
        suggestions = self.suggest_example_improvements()
        successful = self.learn_from_successful_classifications()
        return {
            "error_patterns": {"total": len(patterns), "top_5": patterns[:5]},
            "example_effectiveness": effectiveness,
            "suggestions": {
                "total": len(suggestions),
                "high_priority": [s for s in suggestions if s["priority"] == "high"],
                "all": suggestions,
            },
            "successful_patterns": {
                "categories_with_high_accuracy": len(successful),
                "patterns": successful,
            },
            "recommendations": self._generate_recommendations(patterns, effectiveness, suggestions),
        }

    def _generate_recommendations(
        self, patterns: List, effectiveness: Dict, suggestions: List
    ) -> List[str]:
        recommendations: List[str] = []
        if patterns:
            top_error = patterns[0]
            recommendations.append(
                f"Самая частая ошибка: {top_error['original_category']}→{top_error['corrected_category']} "
                f"({top_error['frequency']} раз). Рекомендуется добавить больше примеров для категории {top_error['corrected_category']}."
            )
        if effectiveness.get("ineffective_count", 0) > 0:
            recommendations.append(
                f"Найдено {effectiveness['ineffective_count']} неэффективных примеров. "
                f"Рекомендуется их пересмотреть или деактивировать."
            )
        high_priority = [s for s in suggestions if s.get("priority") == "high"]
        if high_priority:
            recommendations.append(
                f"{len(high_priority)} срочных рекомендаций требуют внимания."
            )
        return recommendations

    def generate_enhanced_learning_report(self) -> Dict:
        base_report = self.generate_learning_report()
        success_stats = self.get_category_success_stats()
        learning_progress = self.analyze_learning_progress()
        top_categories = sorted(
            success_stats.items(), key=lambda x: x[1]["success_rate"], reverse=True
        )[:5]
        problem_categories = [
            (cat, stats)
            for cat, stats in success_stats.items()
            if stats["total"] >= 5 and stats["success_rate"] < 70
        ]
        return {
            **base_report,
            "success_statistics": {
                "by_category": success_stats,
                "top_performing": [{"category": cat, **stats} for cat, stats in top_categories],
                "needs_attention": [{"category": cat, **stats} for cat, stats in problem_categories],
            },
            "learning_progress": learning_progress,
            "recommendations": self._generate_enhanced_recommendations(
                base_report, success_stats, learning_progress
            ),
        }

    def _generate_enhanced_recommendations(
        self, base_report: Dict, success_stats: Dict, progress: Dict
    ) -> List[str]:
        recommendations = list(base_report.get("recommendations", []))
        if progress.get("accuracy_improvement", 0) > 0:
            recommendations.append(
                f"Точность классификации выросла на {progress['accuracy_improvement']:.1f}% "
                f"за последние {progress['period_days']} дней. Отлично!"
            )
        elif progress.get("accuracy_improvement", 0) < 0:
            recommendations.append(
                f"Точность классификации снизилась на {abs(progress['accuracy_improvement']):.1f}%. "
                f"Рекомендуется проверить новые обучающие примеры."
            )
        if progress.get("total_confirmations", 0) > 0:
            recommendations.append(
                f"Подтверждено {progress['total_confirmations']} правильных классификаций. "
                f"Система накапливает знания о успешных паттернах."
            )
        problem_cats = [
            cat
            for cat, stats in success_stats.items()
            if stats.get("total", 0) >= 5 and stats.get("success_rate", 0) < 70
        ]
        if problem_cats:
            recommendations.append(
                f"Категории, требующие внимания: {', '.join(problem_cats[:3])}. "
                f"Рекомендуется добавить больше примеров для этих категорий."
            )
        return recommendations

    def apply_auto_improvements(self, auto_update: bool = False) -> Dict:
        report = self.generate_learning_report()
        if auto_update:
            rules_updated = self.auto_update_rules()
            deactivated = 0
            for ex in report["example_effectiveness"]["ineffective_examples"]:
                if ex["score"] < 0.2:
                    r = UserTrainingExample.query.filter_by(
                        user_id=self.user_id, id=ex["id"]
                    ).first()
                    if r:
                        r.is_active = False
                        deactivated += 1
            db.session.commit()
            return {
                "rules_updated": rules_updated,
                "examples_deactivated": deactivated,
                "status": "auto_improvements_applied",
            }
        return {"status": "analysis_only", "report": report}


class IntegratedLearningSystem:
    """Интегрированная система обучения; требует user_id в конструкторе."""

    def __init__(self, user_id: Optional[int] = None) -> None:
        from .training_examples import TrainingExamplesManager
        from .classification_rules import ClassificationRulesManager

        self.user_id = int(
            user_id
            or os.environ.get("CLASSIFICATION_USER_ID", "0")
        )
        if self.user_id <= 0:
            raise ValueError("IntegratedLearningSystem: укажите user_id=...")
        self.training_manager = TrainingExamplesManager(user_id=self.user_id)
        self.rules_manager = ClassificationRulesManager(user_id=self.user_id)
        self.self_learning = SelfLearningSystem(user_id=self.user_id)

    def mark_classification_correct(
        self,
        phone_number,
        call_date,
        call_time,
        category,
        reasoning,
        transcription,
        confirmed_by="user",
        confidence=5,
        comment="",
    ) -> bool:
        return self.self_learning.mark_as_correct(
            phone_number,
            call_date,
            call_time,
            category,
            reasoning,
            transcription,
            confirmed_by,
            confidence_level=confidence,
            comment=comment,
        )

    def process_new_correction(
        self,
        transcription,
        orig_cat,
        corr_cat,
        orig_reason,
        corr_reason,
        operator_name="",
    ) -> bool:
        self.training_manager.add_training_example(
            transcription, corr_cat, corr_reason, orig_cat, orig_reason, operator_name
        )
        self.self_learning._update_category_success_stats(orig_cat, is_correct=False)
        patterns = self.self_learning.analyze_error_patterns(days=7)
        recent = [p for p in patterns if p["frequency"] >= 3]
        if recent:
            self.self_learning.auto_update_rules(min_confidence=0.8)
        return True

    def daily_learning_cycle(self) -> Dict:
        report = self.self_learning.generate_enhanced_learning_report()
        rules_updated = self.self_learning.auto_update_rules(min_confidence=0.7)
        effectiveness = self.self_learning.analyze_example_effectiveness()
        return {
            "report": report,
            "rules_updated": rules_updated,
            "effectiveness": effectiveness,
            "timestamp": datetime.now().isoformat(),
        }
