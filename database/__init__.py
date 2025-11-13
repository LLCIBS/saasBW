# database/__init__.py
"""
Инициализация базы данных
"""

from .models import db, User, Call, TransferCase, RecallCase, SystemLog

__all__ = ['db', 'User', 'Call', 'TransferCase', 'RecallCase', 'SystemLog']

