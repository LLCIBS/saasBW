# call_analyzer/config.py
import json
import logging
import os
import sys
from pathlib import Path

# Загружаем переменные окружения из .env (если есть)
try:
    from dotenv import load_dotenv
    # Загружаем .env из корня проекта (на уровень выше call_analyzer)
    project_root = Path(__file__).parent.parent
    env_path = project_root / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # python-dotenv не установлен, используем только os.getenv
    pass

PROFILE_USER_ID = os.getenv("CALL_ANALYZER_USER_ID")
PROFILE_USERNAME = os.getenv("CALL_ANALYZER_USERNAME", "")
PROFILE_LABEL = PROFILE_USERNAME or (PROFILE_USER_ID and f'user-{PROFILE_USER_ID}') or "global"

# Internal Transcription Service
# Автоматически подбираем дефолтный URL в зависимости от окружения,
# чтобы при деплое с dev на prod не приходилось править код.
_env = os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "development"
if _env.lower() in ("production", "prod"):
    _default_transcribe_url = "http://10.8.0.2:8000/transcribe"
else:
    _default_transcribe_url = "http://192.168.101.59:8000/transcribe"

INTERNAL_TRANSCRIPTION_URL = os.getenv("INTERNAL_TRANSCRIPTION_URL", _default_transcribe_url)

# TheB.ai
THEBAI_API_KEY = os.getenv("THEBAI_API_KEY", "sk-c2e6e3c3f0964c6780bcf4db6cc6c644")
THEBAI_URL = os.getenv("THEBAI_URL", "https://api.deepseek.com/v1/chat/completions")
THEBAI_MODEL = os.getenv("THEBAI_MODEL", "deepseek-reasoner")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7990616547:AAG-4jvHgWhR6JtR6pk3wOxzeWmreHnzMyY")
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID", "-1002413323859")

# Пути к файлам (читаем из .env или используем значения по умолчанию)
_script_prompt_8_default = Path("D:\\ООО ИБС\\Бествей\\Система чек листов коммерция BW\\monv2_безRerTruck web5\\script_prompt_8.yaml")
SCRIPT_PROMPT_8_PATH = Path(os.getenv("SCRIPT_PROMPT_8_PATH", str(_script_prompt_8_default)))

_base_records_default = Path("D:\\calls")
BASE_RECORDS_PATH = Path(os.getenv("BASE_RECORDS_PATH", str(_base_records_default)))  # общая база

_prompts_default = Path("D:\\ООО ИБС\\Бествей\\Система чек листов коммерция BW\\monv2_безRerTruck web5\\prompts.yaml")
PROMPTS_FILE = Path(os.getenv("PROMPTS_FILE", str(_prompts_default)))

_additional_vocab_default = Path("D:\\ООО ИБС\\Бествей\\Система чек листов коммерция BW\\monv2_безRerTruck web5\\additional_vocab.yaml")
ADDITIONAL_VOCAB_FILE = Path(os.getenv("ADDITIONAL_VOCAB_FILE", str(_additional_vocab_default)))

# Пример словаря станций
STATION_CHAT_IDS = {
'128801': ['-1002413323859'],
    '303': ['-1002413323859'],
}

STATION_NAMES = {
"128801": "Фокус на Малышева",
    "303": "Крауля 44",
}

STATION_MAPPING = {
'128801': ['128802', '128804'],
    '303': ['311', '301'],
}




# Список кодов станций, относящихся к Нижегородскому региону.
NIZH_STATION_CODES = [
    '128801',
    '303',
]


# Telegram-канал для уведомлений по Нижегородским станциям.
TG_CHANNEL_NIZH = os.getenv("TG_CHANNEL_NIZH", '-1002413323859')  # Здесь укажите ID или username канала для Нижегородских

# Для остальных станций (те, которых нет в списке NIZH_STATION_CODES) используем другой канал:
TG_CHANNEL_OTHER = os.getenv("TG_CHANNEL_OTHER", '-1002413323859')  # ID или username канала для остальных станций

# Привязка внутренних номеров (станций и подстанций) к сотрудникам
# Ключ: строка кода станции/подстанции (например, "202" или "403")
# Значение: произвольная строка с именем/фамилией сотрудника
EMPLOYEE_BY_EXTENSION = {
    '301': '1',
    '303': '2',
    '311': '3',
    '128801': '4',
    '128802': '5',
    '128804': '6',
}

# Конфигурация для расшифровки имен файлов звонков
FILENAME_PATTERNS = {
    # Основной формат fs_*_*_*
    'fs_pattern': r'^fs_([^_]+)_([^_]+)_([^_]+)_',
    
    # Формат с дефисами external-*
    'external_pattern': r'^external-([^\-]+)-([^\-]+)-(\d{8})-(\d{6})(?:-.+)?',
    
    # Формат out-* (исходящие FTP)
    'out_pattern': r'^out-([^\-]+)-([^\-]+)-(\d{8})-(\d{6})(?:-.+)?',
    
    # Новый формат: вход_EkbFocusMal128801_с_79536098664_на_73432260822_от_2025_10_20
    'direction_pattern': r'^вход_([a-zA-Z\-]+)(\d+)_с_(\d+)_на_(\d+)_от_(\d{4})_(\d{1,2})_(\d{1,2})(?:\.\w+)?$',
    
    # Поддерживаемые расширения файлов
    'supported_extensions': ['.mp3', '.wav'],
    
    # Формат даты и времени в именах файлов
    'datetime_format': '%Y-%m-%d-%H-%M-%S',
    'datetime_format_compact': '%Y%m%d-%H%M%S',
    'date_format_direction': '%Y_%m_%d',  # Для нового формата: 2025_10_20
}

# Описание форматов файлов для документации
FILENAME_FORMATS = {
    'incoming': {
        'pattern': 'fs_[phone_number]_[station_code]_[datetime]_...',
        'description': 'Входящий звонок: номер телефона, код станции, дата и время',
        'example': 'fs_79056154237_9301_2025-10-13-10-28-03_...'
    },
    'outgoing': {
        'pattern': 'fs_[station_code]_[phone_number]_[datetime]_...',
        'description': 'Исходящий звонок: код станции, номер телефона, дата и время',
        'example': 'fs_9301_79056154237_2025-10-13-10-28-03_...'
    },
    'external': {
        'pattern': 'external-[station]-[phone]-[YYYYMMDD]-[HHMMSS]-...',
        'description': 'Внешний звонок (Ретрак)',
        'example': 'external-9301-79056154237-20251013-102803-...'
    },
    'outgoing_ftp': {
        'pattern': 'out-[phone]-[station]-[YYYYMMDD]-[HHMMSS]-...',
        'description': 'Исходящий звонок (FTP)',
        'example': 'out-89196552973-203-20251120-173809-...'
    },
    'direction_format': {
        'pattern': 'вход_[station_name][station_code]_с_[from_phone]_на_[to_phone]_от_[YYYY]_[MM]_[DD]',
        'description': 'Звонок с указанием направления: название станции, код станции, номера телефонов, дата',
        'example': 'вход_EkbFocusMal128801_с_79536098664_на_73432260822_от_2025_10_20'
    }
}
ALLOWED_STATIONS = None
PROFILE_SETTINGS = {}
# Включен ли стерео режим для T-Bank (по умолчанию False)
TBANK_STEREO_ENABLED = False  # По умолчанию моно режим
# Использовать ли дополнительный словарь транскрипции (ADDITIONAL_VOCAB_FILE)
# По умолчанию включено, чтобы не ломать существующее поведение.
USE_ADDITIONAL_VOCAB = True
# Автоматическое определение имени оператора из транскрипции
# True - пытаться извлечь имя из транскрипции, затем из таблицы
# False - сразу брать из таблицы EMPLOYEE_BY_EXTENSION
AUTO_DETECT_OPERATOR_NAME = True


def _apply_profile_overrides():
    profile_path = os.getenv("CALL_ANALYZER_PROFILE_PATH")
    if not profile_path:
        return
    try:
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = json.load(f)
    except Exception as exc:
        logging.error("Не удалось загрузить профиль %s: %s", profile_path, exc)
        return
    _apply_profile_dict(profile_data)


def _apply_profile_dict(profile_data):
    global BASE_RECORDS_PATH, PROMPTS_FILE, ADDITIONAL_VOCAB_FILE, SCRIPT_PROMPT_8_PATH
    global TELEGRAM_BOT_TOKEN
    global ALERT_CHAT_ID, TG_CHANNEL_NIZH, TG_CHANNEL_OTHER
    global STATION_NAMES, STATION_CHAT_IDS, STATION_MAPPING
    global NIZH_STATION_CODES, EMPLOYEE_BY_EXTENSION
    global ALLOWED_STATIONS, PROFILE_SETTINGS, TBANK_STEREO_ENABLED, USE_ADDITIONAL_VOCAB, AUTO_DETECT_OPERATOR_NAME

    PROFILE_SETTINGS = profile_data or {}

    paths = (profile_data or {}).get('paths') or {}
    if paths.get('base_records_path'):
        BASE_RECORDS_PATH = Path(paths['base_records_path'])
    if paths.get('prompts_file'):
        PROMPTS_FILE = Path(paths['prompts_file'])
    if paths.get('additional_vocab_file'):
        ADDITIONAL_VOCAB_FILE = Path(paths['additional_vocab_file'])
    if paths.get('script_prompt_file'):
        SCRIPT_PROMPT_8_PATH = Path(paths['script_prompt_file'])

    api_keys = (profile_data or {}).get('api_keys') or {}
    if api_keys.get('telegram_bot_token'):
        TELEGRAM_BOT_TOKEN = api_keys['telegram_bot_token']

    telegram_cfg = (profile_data or {}).get('telegram') or {}
    if telegram_cfg.get('alert_chat_id'):
        ALERT_CHAT_ID = telegram_cfg['alert_chat_id']
    if telegram_cfg.get('tg_channel_nizh'):
        TG_CHANNEL_NIZH = telegram_cfg['tg_channel_nizh']
    if telegram_cfg.get('tg_channel_other'):
        TG_CHANNEL_OTHER = telegram_cfg['tg_channel_other']

    EMPLOYEE_BY_EXTENSION = (profile_data or {}).get('employee_by_extension') or EMPLOYEE_BY_EXTENSION
    STATION_NAMES = (profile_data or {}).get('stations') or STATION_NAMES
    STATION_CHAT_IDS = (profile_data or {}).get('station_chat_ids') or STATION_CHAT_IDS
    STATION_MAPPING = (profile_data or {}).get('station_mapping') or STATION_MAPPING
    NIZH_STATION_CODES = (profile_data or {}).get('nizh_station_codes') or NIZH_STATION_CODES

    ALLOWED_STATIONS = profile_data.get('allowed_stations')

    # Читаем настройки транскрипции из профиля пользователя
    transcription_cfg = (profile_data or {}).get('transcription') or {}
    TBANK_STEREO_ENABLED = bool(transcription_cfg.get('tbank_stereo_enabled', False))
    # Если флаг не задан в профиле, по умолчанию используем словарь
    USE_ADDITIONAL_VOCAB = bool(transcription_cfg.get('use_additional_vocab', True))
    # Автоматическое определение имени оператора (по умолчанию включено)
    AUTO_DETECT_OPERATOR_NAME = bool(transcription_cfg.get('auto_detect_operator_name', True))


_apply_profile_overrides()
