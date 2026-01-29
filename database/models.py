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
    profile_data = db.relationship(
        'UserProfileData',
        back_populates='user',
        uselist=False,
        cascade='all, delete-orphan'
    )

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


class UserProfileData(db.Model):
    """Модель для данных профиля пользователя (юридическое/физическое лицо)."""
    __tablename__ = 'user_profile_data'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)
    entity_type = db.Column(db.String(20), nullable=True)  # 'legal' или 'physical'
    
    # Поля для юридического лица
    legal_name = db.Column(db.String(500), nullable=True)  # Название организации
    legal_inn = db.Column(db.String(20), nullable=True)  # ИНН
    legal_kpp = db.Column(db.String(20), nullable=True)  # КПП
    legal_ogrn = db.Column(db.String(20), nullable=True)  # ОГРН
    legal_address = db.Column(Text, nullable=True)  # Юридический адрес
    actual_address = db.Column(Text, nullable=True)  # Фактический адрес
    
    # Поля для физического лица
    physical_full_name = db.Column(db.String(200), nullable=True)  # ФИО
    physical_inn = db.Column(db.String(20), nullable=True)  # ИНН
    passport_series = db.Column(db.String(10), nullable=True)  # Серия паспорта
    passport_number = db.Column(db.String(20), nullable=True)  # Номер паспорта
    registration_address = db.Column(Text, nullable=True)  # Адрес регистрации
    
    # Служебные поля
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_profile_user', 'user_id'),
        Index('idx_profile_entity_type', 'entity_type'),
    )

    user = db.relationship('User', back_populates='profile_data')

    def __repr__(self):
        return f'<UserProfileData user_id={self.user_id} entity_type={self.entity_type}>'


class UserConfig(db.Model):
    """Модель для конфигурации пользователя"""
    __tablename__ = 'user_config'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)
    
    # Paths
    source_type = db.Column(db.String(50), nullable=True)  # 'ftp' или 'local'
    prompts_file = db.Column(db.String(1000), nullable=True)
    base_records_path = db.Column(db.String(1000), nullable=True)
    ftp_connection_id = db.Column(db.Integer, db.ForeignKey('ftp_connections.id'), nullable=True)
    script_prompt_file = db.Column(db.String(1000), nullable=True)
    additional_vocab_file = db.Column(db.String(1000), nullable=True)
    
    # API Keys
    thebai_api_key = db.Column(db.String(255), nullable=True)
    telegram_bot_token = db.Column(db.String(255), nullable=True)
    speechmatics_api_key = db.Column(db.String(255), nullable=True)
    
    # Telegram
    alert_chat_id = db.Column(db.String(100), nullable=True)
    tg_channel_nizh = db.Column(db.String(100), nullable=True)
    tg_channel_other = db.Column(db.String(100), nullable=True)
    reports_chat_id = db.Column(db.String(100), nullable=True)
    
    # Transcription
    tbank_stereo_enabled = db.Column(db.Boolean, default=False, nullable=False)
    use_additional_vocab = db.Column(db.Boolean, default=True, nullable=False)
    auto_detect_operator_name = db.Column(db.Boolean, default=False, nullable=False)
    # Форматы файлов
    use_custom_filename_patterns = db.Column(db.Boolean, default=False, nullable=False)
    filename_patterns = db.Column(JSONB, nullable=True)  # список паттернов [{key, regex, description, example}]
    filename_extensions = db.Column(JSONB, nullable=True)  # список допустимых расширений
    
    # Arrays stored as JSONB
    allowed_stations = db.Column(JSONB, nullable=True)  # массив кодов станций
    nizh_station_codes = db.Column(JSONB, nullable=True)  # массив кодов станций
    legal_entity_keywords = db.Column(JSONB, nullable=True)  # массив ключевых слов
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_config_user', 'user_id'),
    )
    
    user = db.relationship('User', backref=db.backref('config', uselist=False, cascade='all, delete-orphan'))
    ftp_connection = db.relationship('FtpConnection', foreign_keys=[ftp_connection_id])
    
    def __repr__(self):
        return f'<UserConfig user_id={self.user_id}>'


class UserStation(db.Model):
    """Модель для станций пользователя"""
    __tablename__ = 'user_stations'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    code = db.Column(db.String(20), nullable=False)  # код станции
    name = db.Column(db.String(500), nullable=False)  # название станции
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_station_user_code', 'user_id', 'code'),
        db.UniqueConstraint('user_id', 'code', name='uq_user_station_code'),
    )
    
    user = db.relationship('User', backref=db.backref('stations', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<UserStation user_id={self.user_id} code={self.code} name={self.name}>'


class UserStationMapping(db.Model):
    """Модель для маппинга станций (основная -> подстанции)"""
    __tablename__ = 'user_station_mappings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    main_station_code = db.Column(db.String(20), nullable=False)  # код основной станции
    sub_station_code = db.Column(db.String(20), nullable=False)  # код подстанции
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_mapping_user_main', 'user_id', 'main_station_code'),
        db.UniqueConstraint('user_id', 'main_station_code', 'sub_station_code', name='uq_user_station_mapping'),
    )
    
    user = db.relationship('User', backref=db.backref('station_mappings', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<UserStationMapping user_id={self.user_id} main={self.main_station_code} sub={self.sub_station_code}>'


class UserStationChatId(db.Model):
    """Модель для chat_id станций"""
    __tablename__ = 'user_station_chat_ids'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    station_code = db.Column(db.String(20), nullable=False)
    chat_id = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_chat_user_station', 'user_id', 'station_code'),
        db.UniqueConstraint('user_id', 'station_code', 'chat_id', name='uq_user_station_chat'),
    )
    
    user = db.relationship('User', backref=db.backref('station_chat_ids', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<UserStationChatId user_id={self.user_id} station={self.station_code} chat_id={self.chat_id}>'


class UserEmployeeExtension(db.Model):
    """Модель для маппинга расширений к сотрудникам"""
    __tablename__ = 'user_employee_extensions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    extension = db.Column(db.String(20), nullable=False)  # номер расширения
    employee = db.Column(db.String(200), nullable=False)  # имя сотрудника
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_employee_user_ext', 'user_id', 'extension'),
        db.UniqueConstraint('user_id', 'extension', name='uq_user_employee_ext'),
    )
    
    user = db.relationship('User', backref=db.backref('employee_extensions', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<UserEmployeeExtension user_id={self.user_id} extension={self.extension} employee={self.employee}>'


class UserPrompt(db.Model):
    """Модель для промптов пользователя"""
    __tablename__ = 'user_prompts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    prompt_type = db.Column(db.String(50), nullable=False)  # 'anchor', 'station', 'default'
    prompt_key = db.Column(db.String(100), nullable=False)  # ключ промпта (название якоря, код станции, 'default')
    prompt_text = db.Column(Text, nullable=False)  # текст промпта
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_prompt_user_type', 'user_id', 'prompt_type'),
        db.UniqueConstraint('user_id', 'prompt_type', 'prompt_key', name='uq_user_prompt'),
    )
    
    user = db.relationship('User', backref=db.backref('prompts', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<UserPrompt user_id={self.user_id} type={self.prompt_type} key={self.prompt_key}>'


class UserVocabulary(db.Model):
    """Модель для словаря пользователя"""
    __tablename__ = 'user_vocabulary'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    additional_vocab = db.Column(JSONB, nullable=True)  # массив слов
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_vocab_user', 'user_id'),
    )
    
    user = db.relationship('User', backref=db.backref('vocabulary', uselist=False, cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<UserVocabulary user_id={self.user_id} enabled={self.enabled}>'


class UserScriptPrompt(db.Model):
    """Модель для промпта скрипта пользователя"""
    __tablename__ = 'user_script_prompts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)
    prompt_text = db.Column(Text, nullable=False)  # основной промпт
    checklist = db.Column(JSONB, nullable=True)  # массив объектов чек-листа
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_script_user', 'user_id'),
    )
    
    user = db.relationship('User', backref=db.backref('script_prompt', uselist=False, cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<UserScriptPrompt user_id={self.user_id}>'


class ReportSchedule(db.Model):
    """Модель для расписания автоматической генерации отчетов"""
    __tablename__ = 'report_schedules'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    report_type = db.Column(db.String(50), nullable=False)  # 'week_full', 'rr_3', 'rr_bad', 'skolko_52'
    schedule_type = db.Column(db.String(20), nullable=False)  # 'daily', 'interval', 'weekly', 'custom'
    enabled = db.Column(db.Boolean, nullable=False, default=True)

    # Для daily: время (HH:MM)
    daily_time = db.Column(db.String(5), nullable=True)  # '12:00'

    # Для interval: интервал в днях/часах
    interval_value = db.Column(db.Integer, nullable=True)  # 2
    interval_unit = db.Column(db.String(10), nullable=True)  # 'days' или 'hours'

    # Для weekly: день недели и время
    weekly_day = db.Column(db.Integer, nullable=True)  # 0-6 (понедельник-воскресенье)
    weekly_time = db.Column(db.String(5), nullable=True)

    # Для custom: cron expression
    cron_expression = db.Column(db.String(100), nullable=True)

    # Параметры генерации периода
    period_type = db.Column(db.String(20), nullable=False, default='last_week')  # 'last_day', 'last_week', 'last_month', 'last_n_days'
    period_n_days = db.Column(db.Integer, nullable=True)  # Для period_type='last_n_days' - количество дней

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_run_at = db.Column(db.DateTime, nullable=True)
    next_run_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('report_schedules', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'report_type', name='uq_report_schedule_user_report'),
    )

    def __repr__(self):
        return f'<ReportSchedule user_id={self.user_id} type={self.report_type} {self.schedule_type}>'
