# database/models.py
"""
�?�?�?��>�� �+�����< �?���?�?�<�: �?�>? Call Analyzer
�?�?���?�>�?���?��'�?�? SQLAlchemy �?�>? �?���+�?�'< �? PostgreSQL
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Date, Index, Text
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


class RostelecomAtsConnection(db.Model):
    """Подключение к облачной АТС Ростелеком (Интеграционный API)"""
    __tablename__ = 'rostelecom_ats_connections'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, default='Ростелеком')
    # Адрес API Ростелеком (например https://api.cloudpbx.rt.ru)
    api_url = db.Column(db.String(500), nullable=False)
    # Уникальный код идентификации (X-Client-ID) из ЛК Ростелеком
    client_id = db.Column(db.String(100), nullable=False)
    # Уникальный ключ для подписи (X-Client-Sign) из ЛК Ростелеком
    sign_key = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Маппинг request_pin (внутренний номер) -> station_code для маршрутизации
    pin_to_station = db.Column(JSONB, nullable=True)  # {"317": "9301", "318": "9302"}
    # Фильтр по направлению: ["incoming", "outbound", "internal"]. Пусто/None = все направления
    allowed_directions = db.Column(JSONB, nullable=True)
    # Дата, с которой обрабатывать звонки. Пусто = все
    start_from = db.Column(db.DateTime, nullable=True)
    # Интервал синхронизации в минутах (запрос domain_call_history + download + get_record). 0 = только ручная синхр.
    sync_interval_minutes = db.Column(db.Integer, default=60, nullable=False)
    last_sync = db.Column(db.DateTime, nullable=True)  # Время последней синхронизации
    last_webhook_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_rostelecom_user_active', 'user_id', 'is_active'),
    )

    user = db.relationship('User', backref=db.backref('rostelecom_ats_connections', lazy='dynamic'))

    def __repr__(self):
        return f'<RostelecomAtsConnection {self.name} (user={self.user_id})>'


class StocrmConnection(db.Model):
    """Подключение к CRM StoCRM (API для получения записей звонков)"""
    __tablename__ = 'stocrm_connections'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, default='StoCRM')
    # Поддомен StoCRM (например "mycompany" → mycompany.stocrm.ru)
    domain = db.Column(db.String(200), nullable=False)
    # API-ключ (SID) из раздела «Настройки → API ключи» StoCRM
    sid = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Фильтр по направлению: ["IN", "OUT"]. Пусто/None = все направления
    allowed_directions = db.Column(JSONB, nullable=True)
    # Дата, с которой обрабатывать звонки. Пусто = последние 7 дней
    start_from = db.Column(db.DateTime, nullable=True)
    # Интервал синхронизации в минутах. 0 = только ручная синхронизация
    sync_interval_minutes = db.Column(db.Integer, default=60, nullable=False)
    last_sync = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_stocrm_user_active', 'user_id', 'is_active'),
    )

    user = db.relationship('User', backref=db.backref('stocrm_connections', lazy='dynamic'))

    def __repr__(self):
        return f'<StocrmConnection {self.name} domain={self.domain} (user={self.user_id})>'


class CustomApiConnection(db.Model):
    """Подключение к произвольному REST API для списка записей звонков (JSON → скачивание файла)."""
    __tablename__ = 'custom_api_connections'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, default='Кастомный API')
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # URL, method, headers, params, body, timeout, SSL, auth — как у employee_mapping
    request_config = db.Column(JSONB, nullable=True)
    # items_path, record_url_field, station_field, original_filename_field, external_id_field, timestamp_field
    mapping_config = db.Column(JSONB, nullable=True)
    start_from = db.Column(db.DateTime, nullable=True)
    sync_interval_minutes = db.Column(db.Integer, default=60, nullable=False)
    last_sync = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_custom_api_user_active', 'user_id', 'is_active'),
    )

    user = db.relationship('User', backref=db.backref('custom_api_connections', lazy='dynamic'))

    def __repr__(self):
        return f'<CustomApiConnection {self.name} (user={self.user_id})>'


class CustomApiImportedCall(db.Model):
    """Идемпотентность: уже скачанные записи по внешнему ключу."""
    __tablename__ = 'custom_api_imported_calls'

    id = db.Column(db.Integer, primary_key=True)
    connection_id = db.Column(
        db.Integer, db.ForeignKey('custom_api_connections.id', ondelete='CASCADE'), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    external_key = db.Column(db.String(128), nullable=False)
    record_url = db.Column(Text, nullable=True)
    saved_path = db.Column(db.String(2000), nullable=True)
    raw_payload = db.Column(JSONB, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='ok')
    error_message = db.Column(Text, nullable=True)
    downloaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('connection_id', 'external_key', name='uq_custom_api_import_conn_ext'),
        Index('idx_custom_api_import_user', 'user_id'),
    )

    connection = db.relationship('CustomApiConnection', backref=db.backref('imported_calls', lazy='dynamic'))

    def __repr__(self):
        return f'<CustomApiImportedCall conn={self.connection_id} key={self.external_key[:16]}...>'


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


# Доступные отраслевые профили для многоотраслевой платформы
BUSINESS_PROFILES = {
    'autoservice': {'label': 'Автосервис', 'icon': 'fa-car'},
    'restaurant': {'label': 'Ресторан / общепит', 'icon': 'fa-utensils'},
    'dental': {'label': 'Стоматологическая клиника', 'icon': 'fa-tooth'},
    'retail': {'label': 'Розничная торговля', 'icon': 'fa-store'},
    'medical': {'label': 'Медицинский центр', 'icon': 'fa-hospital'},
    'universal': {'label': 'Универсальный (другое)', 'icon': 'fa-briefcase'},
}

# Пресеты словаря по отраслям (для быстрого добавления типичных терминов)
VOCAB_PRESETS = {
    'autoservice': {
        'stations': ['Бествей', 'Бринского', 'Мечникова', 'Таганрогская', 'Ижевская', 'Спартаковская',
                     'Дзержинск', 'Чонгарская', 'Сахарова', 'Коминтерна', 'Республиканская', 'Арзамас',
                     'Хальзовская', 'Родионова'],
        'terms': ['мастер приёмщик', 'развал-схождение', 'замена масла', 'диагностика', 'автосервис',
                  'техцентр', 'сервисный центр', 'консультант'],
    },
    'restaurant': {
        'stations': ['зал', 'терраса', 'банкетный зал'],
        'terms': ['ресторан', 'кафе', 'столик', 'бронирование', 'банкет', 'меню', 'администратор', 'официант'],
    },
    'dental': {
        'stations': ['клиника', 'филиал'],
        'terms': ['стоматология', 'стоматолог', 'приём', 'консультация', 'имплантация', 'протезирование',
                  'ортодонт', 'гигиена', 'анестезия'],
    },
    'retail': {
        'stations': ['магазин', 'филиал'],
        'terms': ['менеджер', 'консультант', 'доставка', 'наличие', 'заказ'],
    },
    'medical': {
        'stations': ['клиника', 'филиал'],
        'terms': ['врач', 'приём', 'консультация', 'анализы', 'диагностика'],
    },
    'universal': {
        'stations': ['филиал', 'офис'],
        'terms': ['Здравствуйте', 'Добрый день', 'администратор', 'менеджер', 'консультант', 'запись'],
    },
}


class UserConfig(db.Model):
    """Модель для конфигурации пользователя"""
    __tablename__ = 'user_config'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)
    
    # Отраслевой профиль: autoservice, restaurant, dental, retail, medical, universal
    business_profile = db.Column(db.String(50), default='autoservice', nullable=False)
    
    # Paths
    source_type = db.Column(db.String(50), nullable=True)  # 'local', 'ftp', 'rostelecom', 'stocrm', 'custom_api'
    prompts_file = db.Column(db.String(1000), nullable=True)
    base_records_path = db.Column(db.String(1000), nullable=True)
    ftp_connection_id = db.Column(db.Integer, db.ForeignKey('ftp_connections.id'), nullable=True)
    rostelecom_ats_connection_id = db.Column(db.Integer, db.ForeignKey('rostelecom_ats_connections.id'), nullable=True)
    stocrm_connection_id = db.Column(db.Integer, db.ForeignKey('stocrm_connections.id'), nullable=True)
    custom_api_connection_id = db.Column(db.Integer, db.ForeignKey('custom_api_connections.id'), nullable=True)
    script_prompt_file = db.Column(db.String(1000), nullable=True)
    additional_vocab_file = db.Column(db.String(1000), nullable=True)
    
    # API Keys
    thebai_api_key = db.Column(db.String(255), nullable=True)
    thebai_url = db.Column(db.String(500), nullable=True)  # URL LLM (DeepSeek или локальная Gemma)
    thebai_model = db.Column(db.String(100), nullable=True)  # имя модели (deepseek-chat, gemma2:9b и т.д.)
    telegram_bot_token = db.Column(db.String(255), nullable=True)
    speechmatics_api_key = db.Column(db.String(255), nullable=True)
    gemini_api_key = db.Column(db.String(255), nullable=True)
    # Включение каналов уведомлений (Telegram / MAX)
    telegram_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    max_notifications_enabled = db.Column(db.Boolean, default=True, nullable=False)
    # Отправка в MAX файла «Полный текст разбора чек-листа» после разбора звонка
    max_send_checklist_analysis_file = db.Column(db.Boolean, default=True, nullable=False)
    max_access_token = db.Column(db.String(255), nullable=True)
    
    # Telegram
    alert_chat_id = db.Column(db.String(100), nullable=True)
    tg_channel_nizh = db.Column(db.String(100), nullable=True)
    tg_channel_other = db.Column(db.String(100), nullable=True)
    reports_chat_id = db.Column(db.String(100), nullable=True)
    
    # MAX (дубль полей Telegram)
    max_alert_chat_id = db.Column(db.String(100), nullable=True)
    max_tg_channel_nizh = db.Column(db.String(100), nullable=True)
    max_tg_channel_other = db.Column(db.String(100), nullable=True)
    max_reports_chat_id = db.Column(db.String(100), nullable=True)
    
    # Transcription
    # engine: internal — HTTP-сервис Whisper (по умолчанию); gemini — Google Gemini API
    transcription_engine = db.Column(db.String(20), default='internal', nullable=False)
    gemini_model = db.Column(db.String(120), nullable=True)
    tbank_stereo_enabled = db.Column(db.Boolean, default=False, nullable=False)
    use_additional_vocab = db.Column(db.Boolean, default=True, nullable=False)
    auto_detect_operator_name = db.Column(db.Boolean, default=False, nullable=False)
    # Срок хранения исходных аудиофайлов на диске (дней); 0 — не удалять автоматически
    audio_retention_days = db.Column(db.Integer, default=10, nullable=False)
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
    rostelecom_ats_connection = db.relationship('RostelecomAtsConnection', foreign_keys=[rostelecom_ats_connection_id])
    stocrm_connection = db.relationship('StocrmConnection', foreign_keys=[stocrm_connection_id])
    custom_api_connection = db.relationship('CustomApiConnection', foreign_keys=[custom_api_connection_id])
    
    def __repr__(self):
        return f'<UserConfig user_id={self.user_id}>'


class UserStation(db.Model):
    """Модель для станций пользователя"""
    __tablename__ = 'user_stations'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    code = db.Column(db.String(20), nullable=False)  # код станции
    name = db.Column(db.String(500), nullable=False)  # название станции
    # Краткое имя для колонок Excel (классификация и сводные); если NULL — используется name
    report_name = db.Column(db.String(200), nullable=True)
    # Порядок на вкладке «Станции» и в отчётах (меньше — левее)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
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


class UserStationMaxChatId(db.Model):
    """MAX chat_id по станциям (параллель user_station_chat_ids)."""
    __tablename__ = 'user_station_max_chat_ids'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    station_code = db.Column(db.String(20), nullable=False)
    chat_id = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_maxchat_user_station', 'user_id', 'station_code'),
        db.UniqueConstraint('user_id', 'station_code', 'chat_id', name='uq_user_station_max_chat'),
    )

    user = db.relationship('User', backref=db.backref('station_max_chat_ids', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<UserStationMaxChatId user_id={self.user_id} station={self.station_code} chat_id={self.chat_id}>'


class UserEmployeeMappingSource(db.Model):
    """Настройки внешнего источника привязки внутренних номеров к сотрудникам (REST/JSON)."""
    __tablename__ = 'user_employee_mapping_sources'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)

    # manual | sync_replace | sync_merge_manual_priority | sync_only
    mode = db.Column(db.String(40), nullable=False, default='manual')
    provider_type = db.Column(db.String(40), nullable=False, default='generic_rest_json')
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    refresh_ttl_seconds = db.Column(db.Integer, nullable=False, default=300)

    # URL, method, headers, query, timeout, auth (JSON)
    request_config = db.Column(JSONB, nullable=True)
    mapping_config = db.Column(JSONB, nullable=True)
    normalize_config = db.Column(JSONB, nullable=True)

    last_success_at = db.Column(db.DateTime, nullable=True)
    last_attempt_at = db.Column(db.DateTime, nullable=True)
    last_sync_ok = db.Column(db.Boolean, nullable=True)
    last_sync_error = db.Column(db.String(500), nullable=True)
    last_records_count = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('employee_mapping_source', uselist=False, cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<UserEmployeeMappingSource user_id={self.user_id} mode={self.mode} enabled={self.enabled}>'


class UserEmployeeExtension(db.Model):
    """Модель для маппинга расширений к сотрудникам"""
    __tablename__ = 'user_employee_extensions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    extension = db.Column(db.String(20), nullable=False)  # номер расширения
    employee = db.Column(db.String(200), nullable=False)  # имя сотрудника
    # manual — введено вручную; sync — пришло из внешнего источника
    origin_type = db.Column(db.String(20), nullable=False, default='manual')
    external_ref = db.Column(db.String(120), nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)
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

    report_type = db.Column(db.String(50), nullable=False)  # 'week_full'
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


class FinetuneSample(db.Model):
    """Образец для дообучения: аудио + правильная транскрипция"""
    __tablename__ = 'finetune_samples'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    filename = db.Column(db.String(500), nullable=False)
    audio_path = db.Column(db.String(1000), nullable=False)
    transcript = db.Column(Text, nullable=False)
    duration_sec = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('finetune_samples', lazy='dynamic', cascade='all, delete-orphan'))


class FinetuneJob(db.Model):
    """Задача дообучения модели Whisper"""
    __tablename__ = 'finetune_jobs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    status = db.Column(db.String(30), default='pending', nullable=False)  # pending, preparing, training, converting, completed, failed
    total_samples = db.Column(db.Integer, default=0)
    epochs = db.Column(db.Integer, default=3)
    lora_r = db.Column(db.Integer, default=32)
    learning_rate = db.Column(db.Float, default=1e-4)
    progress = db.Column(db.Float, default=0.0)  # 0.0 - 100.0
    current_step = db.Column(db.String(200), nullable=True)  # описание текущего шага
    model_path = db.Column(db.String(1000), nullable=True)  # путь к готовой модели
    error_message = db.Column(Text, nullable=True)
    wer_before = db.Column(db.Float, nullable=True)
    wer_after = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('finetune_jobs', lazy='dynamic', cascade='all, delete-orphan'))


# --- LLM-классификация (данные в PostgreSQL; каталог classification/ — только артефакты) ---


class UserClassificationSystemPrompt(db.Model):
    """Системные промпты классификации (бывш. system_prompts)."""
    __tablename__ = 'user_classification_system_prompts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    content = db.Column(Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    description = db.Column(Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('classification_system_prompts', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='uq_user_classification_prompt_name'),
        Index('idx_ucsp_user', 'user_id'),
    )


class UserClassificationRule(db.Model):
    """Правила классификации."""
    __tablename__ = 'user_classification_rules'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    category_id = db.Column(db.String(100), nullable=False)
    category_name = db.Column(db.String(500), nullable=False)
    rule_text = db.Column(Text, nullable=False)
    priority = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    examples = db.Column(Text, nullable=True)
    conditions = db.Column(Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('classification_rules_rel', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (Index('idx_ucr_user_priority', 'user_id', 'priority'),)


class UserClassificationCriticalRule(db.Model):
    """Критические правила."""
    __tablename__ = 'user_classification_critical_rules'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(500), nullable=False)
    rule_text = db.Column(Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    description = db.Column(Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('classification_critical_rules', lazy='dynamic', cascade='all, delete-orphan'))


class UserClassificationSetting(db.Model):
    """Key/value настройки (бывш. system_settings)."""
    __tablename__ = 'user_classification_settings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    setting_key = db.Column(db.String(200), nullable=False)
    setting_value = db.Column(Text, nullable=False, default='')
    description = db.Column(Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('classification_settings', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'setting_key', name='uq_user_classification_setting_key'),
        Index('idx_ucset_user', 'user_id'),
    )


class UserClassificationHistory(db.Model):
    """История задач классификации."""
    __tablename__ = 'user_classification_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    task_id = db.Column(db.String(120), nullable=False)
    input_folder = db.Column(Text, nullable=False)
    output_file = db.Column(db.String(1000), nullable=False)
    context_days = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(40), nullable=False, default='running')
    total_files = db.Column(db.Integer, default=0, nullable=False)
    processed_files = db.Column(db.Integer, default=0, nullable=False)
    corrections_count = db.Column(db.Integer, default=0, nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    duration = db.Column(db.String(120), nullable=True)
    error_message = db.Column(Text, nullable=True)
    operator_name = db.Column(db.String(200), nullable=True)

    user = db.relationship('User', backref=db.backref('classification_history', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'task_id', name='uq_user_classification_history_task'),
        Index('idx_uch_user_start', 'user_id', 'start_time'),
    )


class UserClassificationSchedule(db.Model):
    """Расписания авто-классификации."""
    __tablename__ = 'user_classification_schedules'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(500), nullable=False)
    description = db.Column(Text, nullable=True)
    input_folder = db.Column(Text, nullable=False)
    context_days = db.Column(db.Integer, default=7, nullable=False)
    schedule_type = db.Column(db.String(50), nullable=False, default='daily')
    schedule_config = db.Column(JSONB, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_run = db.Column(db.DateTime, nullable=True)
    next_run = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = db.Column(db.String(200), nullable=True)
    run_count = db.Column(db.Integer, default=0, nullable=False)
    success_count = db.Column(db.Integer, default=0, nullable=False)
    error_count = db.Column(db.Integer, default=0, nullable=False)

    user = db.relationship('User', backref=db.backref('classification_schedules_rel', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (Index('idx_ucsch_user_next', 'user_id', 'next_run'),)


class UserAutoExtractedRule(db.Model):
    """Автоправила самообучения."""
    __tablename__ = 'user_auto_extracted_rules'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    rule_text = db.Column(Text, nullable=False)
    category_id = db.Column(db.String(100), nullable=False)
    confidence = db.Column(db.Float, default=0.0, nullable=False)
    source_type = db.Column(db.String(80), default='pattern_analysis', nullable=False)
    example_count = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_verified = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('auto_extracted_rules', lazy='dynamic', cascade='all, delete-orphan'))


class UserTrainingExample(db.Model):
    """Обучающие примеры."""
    __tablename__ = 'user_training_examples'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    transcription_hash = db.Column(db.String(64), nullable=False)
    transcription = db.Column(Text, nullable=False)
    correct_category = db.Column(db.String(200), nullable=False)
    correct_reasoning = db.Column(Text, nullable=False)
    original_category = db.Column(db.String(200), nullable=True)
    original_reasoning = db.Column(Text, nullable=True)
    operator_comment = db.Column(Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    used_count = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship('User', backref=db.backref('training_examples_rel', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'transcription_hash', name='uq_user_training_example_hash'),
        Index('idx_ute_user_cat', 'user_id', 'correct_category'),
    )


class UserClassificationMetric(db.Model):
    """Ежедневные метрики качества."""
    __tablename__ = 'user_classification_metrics'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    metric_date = db.Column(Date, nullable=False)
    total_calls = db.Column(db.Integer, default=0, nullable=False)
    correct_classifications = db.Column(db.Integer, default=0, nullable=False)
    corrections_made = db.Column(db.Integer, default=0, nullable=False)
    accuracy_rate = db.Column(db.Float, default=0.0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('classification_metrics', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'metric_date', name='uq_user_classification_metric_date'),
    )


class UserCorrectionHistory(db.Model):
    """История корректировок."""
    __tablename__ = 'user_correction_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    phone_number = db.Column(db.String(40), nullable=True)
    call_date = db.Column(db.String(80), nullable=True)
    call_time = db.Column(db.String(80), nullable=True)
    station = db.Column(db.String(80), nullable=True)
    original_category = db.Column(db.String(200), nullable=False)
    corrected_category = db.Column(db.String(200), nullable=False)
    original_reasoning = db.Column(Text, nullable=True)
    corrected_reasoning = db.Column(Text, nullable=True)
    operator_name = db.Column(db.String(200), nullable=True)
    correction_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('correction_history', lazy='dynamic', cascade='all, delete-orphan'))


class UserCorrectClassification(db.Model):
    """Подтверждения правильных классификаций."""
    __tablename__ = 'user_correct_classifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    phone_number = db.Column(db.String(40), nullable=True)
    call_date = db.Column(db.String(80), nullable=True)
    call_time = db.Column(db.String(80), nullable=True)
    category = db.Column(db.String(200), nullable=False)
    reasoning = db.Column(Text, nullable=True)
    transcription_hash = db.Column(db.String(64), nullable=True)
    confirmed_by = db.Column(db.String(200), nullable=True)
    confirmed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    confidence_level = db.Column(db.Integer, default=5, nullable=False)
    comment = db.Column(Text, nullable=True)

    user = db.relationship('User', backref=db.backref('correct_classifications', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        Index('idx_ucc_user_confirmed', 'user_id', 'confirmed_at'),
    )


class UserClassificationSuccessStat(db.Model):
    """Статистика успешности по категориям."""
    __tablename__ = 'user_classification_success_stats'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    category = db.Column(db.String(200), nullable=False)
    total_classified = db.Column(db.Integer, default=0, nullable=False)
    confirmed_correct = db.Column(db.Integer, default=0, nullable=False)
    corrections_count = db.Column(db.Integer, default=0, nullable=False)
    success_rate = db.Column(db.Float, default=0.0, nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref=db.backref('classification_success_stats', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'category', name='uq_user_class_success_category'),
    )


class UserErrorPattern(db.Model):
    """Паттерны ошибок."""
    __tablename__ = 'user_error_patterns'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    pattern_text = db.Column(Text, nullable=False)
    original_category = db.Column(db.String(200), nullable=False)
    corrected_category = db.Column(db.String(200), nullable=False)
    frequency = db.Column(db.Integer, default=1, nullable=False)
    confidence_score = db.Column(db.Float, default=0.0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    first_seen = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    examples = db.Column(Text, nullable=True)

    user = db.relationship('User', backref=db.backref('error_patterns', lazy='dynamic', cascade='all, delete-orphan'))


class UserExampleEffectiveness(db.Model):
    """Эффективность обучающих примеров."""
    __tablename__ = 'user_example_effectiveness'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    example_id = db.Column(db.Integer, db.ForeignKey('user_training_examples.id', ondelete='CASCADE'), nullable=False, index=True)
    times_used = db.Column(db.Integer, default=0, nullable=False)
    times_helped = db.Column(db.Integer, default=0, nullable=False)
    times_misled = db.Column(db.Integer, default=0, nullable=False)
    times_confirmed = db.Column(db.Integer, default=0, nullable=False)
    success_rate = db.Column(db.Float, default=0.0, nullable=False)
    last_used = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('example_effectiveness', lazy='dynamic', cascade='all, delete-orphan'))
    example = db.relationship('UserTrainingExample', backref=db.backref('effectiveness', uselist=False, cascade='all, delete-orphan'))

    __table_args__ = (db.UniqueConstraint('user_id', 'example_id', name='uq_user_example_effectiveness'),)


class UserSuccessPattern(db.Model):
    """Паттерны успешных классификаций."""
    __tablename__ = 'user_success_patterns'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    category = db.Column(db.String(200), nullable=False)
    common_keywords = db.Column(Text, nullable=True)
    transcription_samples = db.Column(Text, nullable=True)
    confirmation_count = db.Column(db.Integer, default=0, nullable=False)
    success_rate = db.Column(db.Float, default=1.0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_confirmed = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('success_patterns', lazy='dynamic', cascade='all, delete-orphan'))
