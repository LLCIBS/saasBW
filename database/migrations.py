# database/migrations.py
"""
Миграции данных из JSON файлов в базу данных
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from .models import db, TransferCase, RecallCase

logger = logging.getLogger(__name__)


def migrate_transfer_cases_from_json(json_file_path: Path, session, default_user_id: int = 1):
    """
    Мигрирует данные переводов из JSON в базу данных
    
    Args:
        json_file_path: Путь к transfer_cases.json
        session: SQLAlchemy session
    """
    if not json_file_path.exists():
        logger.info(f"Файл {json_file_path} не найден, пропускаем миграцию переводов")
        return 0
    
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        migrated_count = 0
        for item in data:
            # Проверяем, существует ли уже такой кейс
            target_user_id = item.get('user_id') or default_user_id
            existing = session.query(TransferCase).filter_by(
                user_id=target_user_id,
                phone_number=item.get('phone_number'),
                call_time=datetime.fromisoformat(item['call_time']) if isinstance(item.get('call_time'), str) else item.get('call_time')
            ).first()
            
            if existing:
                # Обновляем существующий
                existing.deadline = datetime.fromisoformat(item['deadline']) if isinstance(item.get('deadline'), str) else item.get('deadline')
                existing.status = item.get('status', 'waiting')
                existing.target_station = item.get('target_station')
                existing.analysis = item.get('analysis')
                existing.tg_msg_id = item.get('tg_msg_id')
                existing.notified = item.get('notified', False)
                if 'remind_at' in item and item['remind_at']:
                    existing.remind_at = datetime.fromisoformat(item['remind_at']) if isinstance(item.get('remind_at'), str) else item.get('remind_at')
                migrated_count += 1
            else:
                # Создаем новый
                transfer = TransferCase(
                    user_id=target_user_id,
                    phone_number=item.get('phone_number'),
                    station_code=item.get('station_code'),
                    call_time=datetime.fromisoformat(item['call_time']) if isinstance(item.get('call_time'), str) else item.get('call_time'),
                    deadline=datetime.fromisoformat(item['deadline']) if isinstance(item.get('deadline'), str) else item.get('deadline'),
                    status=item.get('status', 'waiting'),
                    target_station=item.get('target_station'),
                    analysis=item.get('analysis'),
                    tg_msg_id=item.get('tg_msg_id'),
                    notified=item.get('notified', False)
                )
                if 'remind_at' in item and item['remind_at']:
                    transfer.remind_at = datetime.fromisoformat(item['remind_at']) if isinstance(item.get('remind_at'), str) else item.get('remind_at')
                session.add(transfer)
                migrated_count += 1
        
        session.commit()
        logger.info(f"Мигрировано {migrated_count} записей переводов из {json_file_path}")
        return migrated_count
        
    except Exception as e:
        logger.error(f"Ошибка миграции переводов из {json_file_path}: {e}")
        session.rollback()
        return 0


def migrate_recall_cases_from_json(json_file_path: Path, session, default_user_id: int = 1):
    """
    Мигрирует данные перезвонов из JSON в базу данных
    
    Args:
        json_file_path: Путь к recall_cases.json
        session: SQLAlchemy session
    """
    if not json_file_path.exists():
        logger.info(f"Файл {json_file_path} не найден, пропускаем миграцию перезвонов")
        return 0
    
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        migrated_count = 0
        for item in data:
            # Проверяем, существует ли уже такой кейс
            target_user_id = item.get('user_id') or default_user_id
            existing = session.query(RecallCase).filter_by(
                user_id=target_user_id,
                phone_number=item.get('phone_number'),
                call_time=datetime.fromisoformat(item['call_time']) if isinstance(item.get('call_time'), str) else item.get('call_time')
            ).first()
            
            if existing:
                # Обновляем существующий
                existing.deadline = datetime.fromisoformat(item['deadline']) if isinstance(item.get('deadline'), str) else item.get('deadline')
                existing.status = item.get('status', 'waiting')
                existing.recall_station = item.get('recall_station')
                existing.recall_when = item.get('recall_when')
                existing.analysis = item.get('analysis')
                existing.tg_msg_id = item.get('tg_msg_id')
                existing.notified = item.get('notified', False)
                if 'remind_at' in item and item['remind_at']:
                    existing.remind_at = datetime.fromisoformat(item['remind_at']) if isinstance(item.get('remind_at'), str) else item.get('remind_at')
                migrated_count += 1
            else:
                # Создаем новый
                recall = RecallCase(
                    user_id=target_user_id,
                    phone_number=item.get('phone_number'),
                    station_code=item.get('station_code'),
                    call_time=datetime.fromisoformat(item['call_time']) if isinstance(item.get('call_time'), str) else item.get('call_time'),
                    deadline=datetime.fromisoformat(item['deadline']) if isinstance(item.get('deadline'), str) else item.get('deadline'),
                    status=item.get('status', 'waiting'),
                    recall_station=item.get('recall_station'),
                    recall_when=item.get('recall_when'),
                    analysis=item.get('analysis'),
                    tg_msg_id=item.get('tg_msg_id'),
                    notified=item.get('notified', False)
                )
                if 'remind_at' in item and item['remind_at']:
                    recall.remind_at = datetime.fromisoformat(item['remind_at']) if isinstance(item.get('remind_at'), str) else item.get('remind_at')
                session.add(recall)
                migrated_count += 1
        
        session.commit()
        logger.info(f"Мигрировано {migrated_count} записей перезвонов из {json_file_path}")
        return migrated_count
        
    except Exception as e:
        logger.error(f"Ошибка миграции перезвонов из {json_file_path}: {e}")
        session.rollback()
        return 0


def run_migrations(project_root: Path, db_session, default_user_id: Optional[int] = None):
    """
    Запускает все миграции данных из JSON в БД
    
    Args:
        project_root: Корневая папка проекта
        db_session: SQLAlchemy session
    """
    logger.info("Начало миграции данных из JSON в базу данных...")
    
    transfer_file = project_root / 'transfer_cases.json'
    recall_file = project_root / 'recall_cases.json'
    
    tenant_id = default_user_id or int(os.getenv('DEFAULT_TENANT_USER_ID', '1'))
    transfer_count = migrate_transfer_cases_from_json(transfer_file, db_session, tenant_id)
    recall_count = migrate_recall_cases_from_json(recall_file, db_session, tenant_id)
    
    logger.info(f"Миграция завершена: {transfer_count} переводов, {recall_count} перезвонов")
    return transfer_count + recall_count

