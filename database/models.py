# database/models.py
"""
�?�?�?��>�� �+�����< �?���?�?�<�: �?�>? Call Analyzer
�?�?���?�>�?���?��'�?�? SQLAlchemy �?�>? �?���+�?�'< �? PostgreSQL
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Index, Text
from sqlalchemy.dialects.postgresql import JSONB


db = SQLAlchemy()


class User(UserMixin, db.Model):
    """�?�?�?��>? ���?�>?���?�?���'��>? �?�>? ���?�'�?�?������Ő��"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False)  # admin, user, viewer
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    settings = db.relationship(
        'UserSettings',
        back_populates='user',
        uselist=False,
        cascade='all, delete-orphan'
    )
    calls = db.relationship('Call', back_populates='user', lazy='dynamic')
    transfer_cases = db.relationship('TransferCase', back_populates='user', lazy='dynamic')
    recall_cases = db.relationship('RecallCase', back_populates='user', lazy='dynamic')
    system_logs = db.relationship('SystemLog', back_populates='user', lazy='dynamic')

    def set_password(self, password):
        """�?�?�'���?�?�?��'? �����?�?�>? (�:�?�?��?�?�?���?���)"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """�?�?�?�?��?��'? �����?�?�>?"""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


class Call(db.Model):
    """�?�?�?��>? ���?�?�?���"""
    __tablename__ = 'calls'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    filename = db.Column(db.String(500), nullable=False, index=True)
    file_path = db.Column(db.String(1000), nullable=False)
    phone_number = db.Column(db.String(20), nullable=True, index=True)
    station_code = db.Column(db.String(20), nullable=True, index=True)
    call_time = db.Column(db.DateTime, nullable=False, index=True)
    transcript = db.Column(Text, nullable=True)
    analysis = db.Column(Text, nullable=True)
    call_type = db.Column(db.String(50), nullable=True)  # [���?�?�-�'�?�?�?�?]
    call_class = db.Column(db.String(50), nullable=True)  # [�?�>?����]
    call_result = db.Column(db.String(50), nullable=True)  # [���?�-�?�>�����?��]
    is_legal_entity = db.Column(db.Boolean, default=False, nullable=False)
    meta_data = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        Index('idx_calls_station_time', 'user_id', 'station_code', 'call_time'),
        Index('idx_calls_phone_time', 'user_id', 'phone_number', 'call_time'),
    )

    def __repr__(self):
        return f'<Call {self.filename}>'

    user = db.relationship('User', back_populates='calls')


class TransferCase(db.Model):
    """�?�?�?��>? �����?�� ����?��?�?�?��"""
    __tablename__ = 'transfer_cases'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    phone_number = db.Column(db.String(20), nullable=False, index=True)
    station_code = db.Column(db.String(20), nullable=True)
    call_time = db.Column(db.DateTime, nullable=False, index=True)
    deadline = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(20), default='waiting', nullable=False, index=True)  # waiting, completed, failed
    target_station = db.Column(db.String(20), nullable=True)
    analysis = db.Column(Text, nullable=True)
    tg_msg_id = db.Column(db.String(50), nullable=True)
    remind_at = db.Column(db.DateTime, nullable=True, index=True)
    notified = db.Column(db.Boolean, default=False, nullable=False)
    meta_data = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_transfers_status_deadline', 'user_id', 'status', 'deadline'),
        Index('idx_transfers_remind', 'user_id', 'remind_at', 'notified'),
    )

    def __repr__(self):
        return f'<TransferCase {self.phone_number} {self.status}>'

    user = db.relationship('User', back_populates='transfer_cases')


class RecallCase(db.Model):
    """�?�?�?��>? �����?�� ����?����?�?�?��"""
    __tablename__ = 'recall_cases'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    phone_number = db.Column(db.String(20), nullable=False, index=True)
    station_code = db.Column(db.String(20), nullable=True)
    call_time = db.Column(db.DateTime, nullable=False, index=True)
    deadline = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(20), default='waiting', nullable=False, index=True)
    recall_station = db.Column(db.String(20), nullable=True)
    recall_when = db.Column(db.String(200), nullable=True)
    analysis = db.Column(Text, nullable=True)
    tg_msg_id = db.Column(db.String(50), nullable=True)
    remind_at = db.Column(db.DateTime, nullable=True, index=True)
    notified = db.Column(db.Boolean, default=False, nullable=False)
    meta_data = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_recalls_status_deadline', 'user_id', 'status', 'deadline'),
        Index('idx_recalls_remind', 'user_id', 'remind_at', 'notified'),
    )

    def __repr__(self):
        return f'<RecallCase {self.phone_number} {self.status}>'

    user = db.relationship('User', back_populates='recall_cases')


class FtpConnection(db.Model):
    """Модель для FTP подключений"""
    __tablename__ = 'ftp_connections'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)  # Название подключения
    host = db.Column(db.String(255), nullable=False)  # FTP сервер
    port = db.Column(db.Integer, default=21, nullable=False)  # Порт (21 для FTP, 22 для SFTP)
    username = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(255), nullable=False)  # В зашифрованном виде
    remote_path = db.Column(db.String(1000), nullable=False, default='/')  # Удаленная папка
    protocol = db.Column(db.String(10), default='ftp', nullable=False)  # ftp или sftp
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # Активно ли подключение
    sync_interval = db.Column(db.Integer, default=300, nullable=False)  # Интервал синхронизации в секундах
    start_from = db.Column(db.DateTime, nullable=True)  # Дата, с которой начинать обработку файлов
    last_processed_mtime = db.Column(db.DateTime, nullable=True)  # Момент времени последнего обработанного файла
    last_processed_filename = db.Column(db.String(500), nullable=True)  # Имя последнего обработанного файла
    last_sync = db.Column(db.DateTime, nullable=True)  # Время последней синхронизации
    last_error = db.Column(Text, nullable=True)  # Последняя ошибка
    download_count = db.Column(db.Integer, default=0, nullable=False)  # Количество скачанных файлов
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_ftp_user_active', 'user_id', 'is_active'),
    )

    user = db.relationship('User', backref=db.backref('ftp_connections_rel', lazy='dynamic'))

    def __repr__(self):
        return f'<FtpConnection {self.name} ({self.host})>'

    # Пароль хранится в открытом виде, так как нужен для FTP подключения
    # В production рекомендуется использовать переменные окружения или зашифрованное хранилище


class SystemLog(db.Model):
    """�?�?�?��>? �?��?�'��?�?�<�: �>�?�?�?�?"""
    __tablename__ = 'system_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    level = db.Column(db.String(20), nullable=False, index=True)  # INFO, WARNING, ERROR
    module = db.Column(db.String(100), nullable=True)
    message = db.Column(Text, nullable=False)
    meta_data = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index('idx_logs_level_time', 'user_id', 'level', 'created_at'),
    )

    def __repr__(self):
        return f'<SystemLog {self.level} {self.created_at}>'

    user = db.relationship('User', back_populates='system_logs')


class UserSettings(db.Model):
    """�?��?�?�?�?���>�?�?�<�� �?���?�'�?�?����� ���?�>?���?�?���'��>?."""
    __tablename__ = 'user_settings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    data = db.Column(JSONB, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', back_populates='settings')

    def __repr__(self):
        return f'<UserSettings user_id={self.user_id}>'
