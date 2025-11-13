# auth/decorators.py
"""
Декораторы для проверки прав доступа
"""

from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user


def admin_required(f):
    """Декоратор для проверки прав администратора"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Пожалуйста, войдите в систему', 'error')
            return redirect(url_for('auth.login'))
        if current_user.role != 'admin':
            flash('Доступ запрещен. Требуются права администратора', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*roles):
    """Декоратор для проверки роли пользователя"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Пожалуйста, войдите в систему', 'error')
                return redirect(url_for('auth.login'))
            if current_user.role not in roles:
                flash('Доступ запрещен', 'error')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

