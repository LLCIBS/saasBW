#!/usr/bin/env python3
"""
Перенос данных классификации из per-user SQLite в PostgreSQL.

Использование (из корня проекта, с активированным venv):
    python scripts/migrate_sqlite_classification_to_postgres.py
    python scripts/migrate_sqlite_classification_to_postgres.py --user-id 1

Перезапись: по умолчанию пользователь пропускается, если в PostgreSQL уже есть
системные промпты. Для принудительного импорта: --force
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web_interface.app import app  # noqa: E402
from database import models as M  # noqa: E402


def _user_base_path(user) -> Path:
    cfg = M.UserConfig.query.filter_by(user_id=user.id).first()
    if cfg and cfg.base_records_path:
        return Path(cfg.base_records_path)
    base_root = Path(str(app.config.get("BASE_RECORDS_PATH", Path.cwd())))
    return base_root / "users" / str(user.id)


def _parse_dt(val):
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    s = str(val)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(s[:19], fmt) if "T" not in s else datetime.fromisoformat(
                s.replace("Z", "+00:00")
            )
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _migrate_rules_db(db_path: Path, user_id: int, force: bool) -> None:
    if not db_path.is_file():
        return
    if not force and M.UserClassificationSystemPrompt.query.filter_by(user_id=user_id).count() > 0:
        print(f"  [skip rules] user {user_id}: промпты уже в PostgreSQL (добавьте --force)")
        return
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    table_names = [
        r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    for table in table_names:
        if table == "system_prompts":
            for r in cur.execute("SELECT * FROM system_prompts").fetchall():
                d = dict(r)
                m = M.UserClassificationSystemPrompt(
                    user_id=user_id,
                    name=d.get("name") or "prompt",
                    content=d.get("content") or "",
                    is_active=bool(d.get("is_active", 1)),
                    created_at=_parse_dt(d.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_dt(d.get("updated_at")) or datetime.utcnow(),
                    description=d.get("description"),
                )
                M.db.session.add(m)
        if table == "classification_rules":
            for r in cur.execute("SELECT * FROM classification_rules").fetchall():
                d = dict(r)
                m = M.UserClassificationRule(
                    user_id=user_id,
                    category_id=d.get("category_id") or "",
                    category_name=d.get("category_name") or "",
                    rule_text=d.get("rule_text") or "",
                    priority=int(d.get("priority") or 0),
                    is_active=bool(d.get("is_active", 1)),
                    examples=d.get("examples"),
                    conditions=d.get("conditions"),
                    created_at=_parse_dt(d.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_dt(d.get("updated_at")) or datetime.utcnow(),
                )
                M.db.session.add(m)
        if table == "critical_rules":
            for r in cur.execute("SELECT * FROM critical_rules").fetchall():
                d = dict(r)
                m = M.UserClassificationCriticalRule(
                    user_id=user_id,
                    name=d.get("name") or "",
                    rule_text=d.get("rule_text") or "",
                    is_active=bool(d.get("is_active", 1)),
                    created_at=_parse_dt(d.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_dt(d.get("updated_at")) or datetime.utcnow(),
                    description=d.get("description"),
                )
                M.db.session.add(m)
        if table == "system_settings":
            for r in cur.execute("SELECT * FROM system_settings").fetchall():
                d = dict(r)
                m = M.UserClassificationSetting(
                    user_id=user_id,
                    setting_key=d.get("setting_key") or "",
                    setting_value=str(d.get("setting_value") or ""),
                    description=d.get("description"),
                    created_at=_parse_dt(d.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_dt(d.get("updated_at")) or datetime.utcnow(),
                )
                M.db.session.add(m)
        if table == "classification_history":
            for r in cur.execute("SELECT * FROM classification_history").fetchall():
                d = dict(r)
                m = M.UserClassificationHistory(
                    user_id=user_id,
                    task_id=str(d.get("task_id") or ""),
                    input_folder=d.get("input_folder") or "",
                    output_file=d.get("output_file") or "",
                    context_days=int(d.get("context_days") or 0),
                    status=d.get("status") or "running",
                    total_files=int(d.get("total_files") or 0),
                    processed_files=int(d.get("processed_files") or 0),
                    corrections_count=int(d.get("corrections_count") or 0),
                    start_time=_parse_dt(d.get("start_time")) or datetime.utcnow(),
                    end_time=_parse_dt(d.get("end_time")),
                    duration=d.get("duration"),
                    error_message=d.get("error_message"),
                    operator_name=d.get("operator_name"),
                )
                M.db.session.add(m)
        if table == "classification_schedules":
            for r in cur.execute("SELECT * FROM classification_schedules").fetchall():
                d = dict(r)
                sc = d.get("schedule_config")
                if isinstance(sc, str):
                    try:
                        j = json.loads(sc) if sc else {}
                    except Exception:
                        j = {}
                else:
                    j = sc or {}
                m = M.UserClassificationSchedule(
                    user_id=user_id,
                    name=d.get("name") or "",
                    description=d.get("description"),
                    input_folder=d.get("input_folder") or "",
                    context_days=int(d.get("context_days") or 0),
                    schedule_type=d.get("schedule_type") or "daily",
                    schedule_config=j,
                    is_active=bool(d.get("is_active", 1)),
                    last_run=_parse_dt(d.get("last_run")),
                    next_run=_parse_dt(d.get("next_run")),
                    created_at=_parse_dt(d.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_dt(d.get("updated_at")) or datetime.utcnow(),
                    created_by=d.get("created_by"),
                    run_count=int(d.get("run_count") or 0),
                    success_count=int(d.get("success_count") or 0),
                    error_count=int(d.get("error_count") or 0),
                )
                M.db.session.add(m)
        if table == "auto_extracted_rules":
            for r in cur.execute("SELECT * FROM auto_extracted_rules").fetchall():
                d = dict(r)
                m = M.UserAutoExtractedRule(
                    user_id=user_id,
                    rule_text=d.get("rule_text") or "",
                    category_id=d.get("category_id") or "",
                    confidence=float(d.get("confidence") or 0.0),
                    source_type=d.get("source_type") or "pattern_analysis",
                    example_count=int(d.get("example_count") or 0),
                    is_active=bool(d.get("is_active", 1)),
                    created_at=_parse_dt(d.get("created_at")) or datetime.utcnow(),
                    last_verified=_parse_dt(d.get("last_verified")),
                )
                M.db.session.add(m)
    conn.close()
    M.db.session.commit()
    print(f"  [ok] rules DB -> PostgreSQL user_id={user_id}")


def _migrate_training_db(db_path: Path, user_id: int, force: bool) -> None:
    if not db_path.is_file():
        return
    if not force and M.UserTrainingExample.query.filter_by(user_id=user_id).count() > 0:
        print(f"  [skip training] user {user_id}: примеры уже в PostgreSQL (добавьте --force)")
        return
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    for r in cur.execute("SELECT * FROM training_examples").fetchall():
        d = dict(r)
        m = M.UserTrainingExample(
            user_id=user_id,
            transcription_hash=d.get("transcription_hash") or "",
            transcription=d.get("transcription") or "",
            correct_category=d.get("correct_category") or "",
            correct_reasoning=d.get("correct_reasoning") or "",
            original_category=d.get("original_category"),
            original_reasoning=d.get("original_reasoning"),
            operator_comment=d.get("operator_comment"),
            created_at=_parse_dt(d.get("created_at")) or datetime.utcnow(),
            used_count=int(d.get("used_count") or 0),
            is_active=bool(d.get("is_active", 1)),
        )
        M.db.session.add(m)
    for r in cur.execute("SELECT * FROM classification_metrics").fetchall():
        d = dict(r)
        m = M.UserClassificationMetric(
            user_id=user_id,
            metric_date=datetime.strptime(str(d.get("date"))[:10], "%Y-%m-%d").date()
            if d.get("date")
            else datetime.utcnow().date(),
            total_calls=int(d.get("total_calls") or 0),
            correct_classifications=int(d.get("correct_classifications") or 0),
            corrections_made=int(d.get("corrections_made") or 0),
            accuracy_rate=float(d.get("accuracy_rate") or 0.0),
            created_at=_parse_dt(d.get("created_at")) or datetime.utcnow(),
        )
        M.db.session.add(m)
    for r in cur.execute("SELECT * FROM correction_history").fetchall():
        d = dict(r)
        m = M.UserCorrectionHistory(
            user_id=user_id,
            phone_number=d.get("phone_number"),
            call_date=d.get("call_date"),
            call_time=d.get("call_time"),
            station=d.get("station"),
            original_category=d.get("original_category") or "",
            corrected_category=d.get("corrected_category") or "",
            original_reasoning=d.get("original_reasoning"),
            corrected_reasoning=d.get("corrected_reasoning"),
            operator_name=d.get("operator_name"),
            correction_date=_parse_dt(d.get("correction_date")) or datetime.utcnow(),
        )
        M.db.session.add(m)
    for t in [
        "correct_classifications",
        "classification_success_stats",
        "error_patterns",
        "example_effectiveness",
        "success_patterns",
    ]:
        try:
            cur.execute(f"SELECT * FROM {t} LIMIT 0")
        except Exception:
            continue
        for r in cur.execute(f"SELECT * FROM {t}").fetchall():
            d = dict(r)
            if t == "correct_classifications":
                M.db.session.add(
                    M.UserCorrectClassification(
                        user_id=user_id,
                        phone_number=d.get("phone_number"),
                        call_date=d.get("call_date"),
                        call_time=d.get("call_time"),
                        category=d.get("category") or "",
                        reasoning=d.get("reasoning"),
                        transcription_hash=d.get("transcription_hash"),
                        confirmed_by=d.get("confirmed_by"),
                        confirmed_at=_parse_dt(d.get("confirmed_at")) or datetime.utcnow(),
                        confidence_level=int(d.get("confidence_level") or 5),
                        comment=d.get("comment"),
                    )
                )
            elif t == "classification_success_stats":
                M.db.session.add(
                    M.UserClassificationSuccessStat(
                        user_id=user_id,
                        category=d.get("category") or "",
                        total_classified=int(d.get("total_classified") or 0),
                        confirmed_correct=int(d.get("confirmed_correct") or 0),
                        corrections_count=int(d.get("corrections_count") or 0),
                        success_rate=float(d.get("success_rate") or 0.0),
                        last_updated=_parse_dt(d.get("last_updated")) or datetime.utcnow(),
                    )
                )
            elif t == "error_patterns":
                M.db.session.add(
                    M.UserErrorPattern(
                        user_id=user_id,
                        pattern_text=d.get("pattern_text") or "",
                        original_category=d.get("original_category") or "",
                        corrected_category=d.get("corrected_category") or "",
                        frequency=int(d.get("frequency") or 0),
                        confidence_score=float(d.get("confidence_score") or 0.0),
                        is_active=bool(d.get("is_active", 1)),
                        first_seen=_parse_dt(d.get("first_seen")) or datetime.utcnow(),
                        last_seen=_parse_dt(d.get("last_seen")) or datetime.utcnow(),
                        examples=d.get("examples"),
                    )
                )
            elif t == "example_effectiveness":
                # Пропуск: example_id в SQLite локален, в PG id примеров другие.
                pass
            elif t == "success_patterns":
                M.db.session.add(
                    M.UserSuccessPattern(
                        user_id=user_id,
                        category=d.get("category") or "",
                        common_keywords=d.get("common_keywords"),
                        transcription_samples=d.get("transcription_samples"),
                        confirmation_count=int(d.get("confirmation_count") or 0),
                        success_rate=float(d.get("success_rate") or 1.0),
                        is_active=bool(d.get("is_active", 1)),
                        created_at=_parse_dt(d.get("created_at")) or datetime.utcnow(),
                        last_confirmed=_parse_dt(d.get("last_confirmed")),
                    )
                )
    conn.close()
    M.db.session.commit()
    print(f"  [ok] training DB -> PostgreSQL user_id={user_id}")


def _clear_user_pg(user_id: int) -> None:
    for model in [
        M.UserSuccessPattern,
        M.UserExampleEffectiveness,
        M.UserErrorPattern,
        M.UserCorrectClassification,
        M.UserClassificationSuccessStat,
        M.UserCorrectionHistory,
        M.UserClassificationMetric,
        M.UserTrainingExample,
        M.UserAutoExtractedRule,
        M.UserClassificationSchedule,
        M.UserClassificationHistory,
        M.UserClassificationSetting,
        M.UserClassificationCriticalRule,
        M.UserClassificationRule,
        M.UserClassificationSystemPrompt,
    ]:
        model.query.filter_by(user_id=user_id).delete()
    M.db.session.commit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user-id", type=int, default=None, help="Только этот пользователь")
    p.add_argument(
        "--force",
        action="store_true",
        help="Удалить существующие данные классификации в PG для пользователя и импортировать заново",
    )
    args = p.parse_args()
    with app.app_context():
        M.db.create_all()
        q = M.User.query
        if args.user_id is not None:
            q = q.filter_by(id=args.user_id)
        users = q.all()
        if not users:
            print("Пользователи не найдены.")
            return
        for u in users:
            base = _user_base_path(u)
            root = base / "classification"
            rules_db = root / "classification_rules.db"
            train_db = root / "training_examples.db"
            print(f"User {u.id} ({u.username}): {root}")
            if args.force and (rules_db.is_file() or train_db.is_file()):
                _clear_user_pg(int(u.id))
            try:
                _migrate_rules_db(rules_db, int(u.id), force=args.force)
                _migrate_training_db(train_db, int(u.id), force=args.force)
            except Exception as e:
                print(f"  [error] {e}")
                M.db.session.rollback()
                raise
        print("Готово.")


if __name__ == "__main__":
    main()
