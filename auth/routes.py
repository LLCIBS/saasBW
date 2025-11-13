# auth/routes.py
"""
Маршруты для авторизации
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from database.models import db, User, UserSettings
from datetime import datetime
from pathlib import Path
from typing import Optional
from common.user_settings import default_config_template
import shutil
import call_analyzer.config as legacy_config

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


def _get_user_workspace_root(user_id: int) -> Path:
    base_storage = Path(str(getattr(legacy_config, 'BASE_RECORDS_PATH', Path('/var/calls'))))
    return base_storage / "users" / str(user_id)


def _copy_template_file(source_path: Optional[Path], destination_path: Path):
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source_path and source_path.exists():
            if destination_path.exists():
                return
            shutil.copy2(source_path, destination_path)
        else:
            destination_path.touch(exist_ok=True)
    except Exception as exc:
        current_app.logger.warning(
            "Не удалось подготовить шаблон %s -> %s: %s",
            source_path,
            destination_path,
            exc
        )


def initialize_user_profile_assets(user: User):
    """
    Создает рабочую директорию пользователя, копирует базовые шаблоны
    и фиксирует пути в user_settings.config.paths.
    """
    user_root = _get_user_workspace_root(user.id)
    user_root.mkdir(parents=True, exist_ok=True)
    config_dir = user_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    template_specs = [
        ('prompts_file', getattr(legacy_config, 'PROMPTS_FILE', None), 'prompts.yaml'),
        ('additional_vocab_file', getattr(legacy_config, 'ADDITIONAL_VOCAB_FILE', None), 'additional_vocab.yaml'),
        ('script_prompt_file', getattr(legacy_config, 'SCRIPT_PROMPT_8_PATH', None), 'script_prompt_8.yaml')
    ]

    resolved_paths = {}
    for key, source, filename in template_specs:
        destination = config_dir / filename
        resolved_paths[key] = str(destination)
        source_path = None
        if source:
            try:
                source_path = Path(str(source))
            except Exception:
                source_path = None
        _copy_template_file(source_path, destination)

    settings = UserSettings.query.filter_by(user_id=user.id).first()
    if not settings:
        settings = UserSettings(user_id=user.id, data={})
        db.session.add(settings)

    data = settings.data or {}
    config_section = data.get('config') or default_config_template()
    paths_section = config_section.get('paths') or {}
    paths_section['base_records_path'] = str(user_root)
    for key, value in resolved_paths.items():
        paths_section[key] = value
    config_section['paths'] = paths_section
    data['config'] = config_section
    settings.data = data
    db.session.commit()


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = bool(request.form.get('remember'))
        
        if not username or not password:
            flash('Пожалуйста, введите имя пользователя и пароль', 'error')
            return render_template('auth/login.html')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash('Ваш аккаунт деактивирован', 'error')
                return render_template('auth/login.html')
            
            # Включаем постоянную сессию
            try:
                from flask import session
                session.permanent = True
            except Exception as e:
                current_app.logger.warning(f"Не удалось установить постоянную сессию: {e}")
            
            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            if not user.settings:
                db.session.add(UserSettings(user_id=user.id, data={}))
            db.session.commit()
            
            # Проверяем, что пользователь действительно залогинен
            try:
                # current_user уже импортирован в начале файла
                current_app.logger.info(f"Пользователь {user.username} (ID: {user.id}) успешно вошел в систему")
                # После login_user нужно использовать current_user из flask_login
                # Но здесь current_user еще может быть не обновлен, поэтому используем user
                current_app.logger.info(f"Пользователь залогинен: {user.username}")
            except Exception as e:
                current_app.logger.error(f"Ошибка при логировании входа: {e}")
            
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль', 'error')
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Выход из системы"""
    logout_user()
    flash('Вы успешно вышли из системы', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Публичная регистрация (роль admin может назначить только администратор)."""
    is_admin = current_user.is_authenticated and getattr(current_user, 'role', None) == 'admin'

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'user') if is_admin else 'user'

        if not username or not password:
            flash('Имя пользователя и пароль обязательны.', 'error')
            return render_template('auth/register.html')

        if User.query.filter_by(username=username).first():
            flash('Такой пользователь уже существует.', 'error')
            return render_template('auth/register.html')

        user = User(username=username, email=email or None, role=role)
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.commit()

            # Создание структуры папок после успешного создания пользователя
            try:
                user_folder = _get_user_workspace_root(user.id)
                now = datetime.utcnow()
                year_folder = user_folder / str(now.year)
                month_folder = year_folder / f"{now.month:02d}"
                day_folder = month_folder / f"{now.day:02d}"

                day_folder.mkdir(parents=True, exist_ok=True)
            except Exception as folder_error:
                # Логируем ошибку создания папок, но не прерываем процесс регистрации
                current_app.logger.warning(
                    "Не удалось подготовить вложенные папки для пользователя %s: %s",
                    user.id,
                    folder_error
                )

            try:
                initialize_user_profile_assets(user)
            except Exception as setup_error:
                current_app.logger.error(
                    "Не удалось инициализировать шаблоны пользователя %s: %s",
                    user.id,
                    setup_error
                )

            if is_admin:
                flash(f'Пользователь {username} создан.', 'success')
                return redirect(url_for('auth.users_list'))

            login_user(user)
            flash('Регистрация прошла успешно, вы вошли в систему.', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при создании пользователя: {str(e)}', 'error')

    return render_template('auth/register.html')

@auth_bp.route('/users')
@login_required
def users_list():
    """Список пользователей (только для админов)"""
    if current_user.role != 'admin':
        flash('Доступ запрещен', 'error')
        return redirect(url_for('index'))
    
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('auth/users_list.html', users=users)

