# auth/__init__.py
"""
Модуль авторизации
"""

from flask_login import LoginManager
from database.models import User

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Пожалуйста, войдите для доступа к этой странице.'
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    """Загрузка пользователя для Flask-Login"""
    return User.query.get(int(user_id))

