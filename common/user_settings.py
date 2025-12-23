from copy import deepcopy
from pathlib import Path


def default_config_template():
    return {
        'api_keys': {
            'speechmatics_api_key': '',
            'thebai_api_key': '',
            'thebai_url': 'https://api.deepseek.com/v1/chat/completions',
            'thebai_model': 'deepseek-reasoner',
            'telegram_bot_token': ''
        },
        'telegram': {
            'alert_chat_id': '',
            'tg_channel_nizh': '',
            'tg_channel_other': ''
        },
        'paths': {
            'base_records_path': '',
            'prompts_file': '',
            'additional_vocab_file': '',
            'script_prompt_file': '',
            'source_type': 'local',  # 'local' или 'ftp'
            'ftp_connection_id': None  # ID FTP подключения, если source_type = 'ftp'
        },
        'employee_by_extension': {},
        'stations': {},
        'station_chat_ids': {},
        'station_mapping': {},
        'nizh_station_codes': [],
        'transcription': {
            'tbank_stereo_enabled': False,
            # Использовать ли дополнительный словарь при транскрипции
            # По умолчанию включено
            'use_additional_vocab': True,
            # Автоматическое определение имени оператора из транскрипции
            # True - пытаться извлечь имя из транскрипции, затем из таблицы
            # False - сразу брать из таблицы EMPLOYEE_BY_EXTENSION
            'auto_detect_operator_name': True,
        },
        'filename': {
            'enabled': False,
            'patterns': [],
            'extensions': ['.mp3', '.wav']
        },
        'allowed_stations': []
    }


def default_prompts_template():
    return {
        'default': '',
        'anchors': {},
        'stations': {}
    }


def default_vocabulary_template():
    return {
        # Флаг: использовать ли дополнительный словарь при транскрипции
        # True  - словарь подключается и передаётся на сервер транскрипций
        # False - словарь игнорируется, но слова остаются сохранёнными
        'enabled': True,
        'additional_vocab': []
    }


def default_logs_template():
    return []


def default_script_prompt_template():
    return {
        'checklist': [],
        'prompt': ''
    }


def build_runtime_config(project_config, config_data=None, user_id=None):
    """
    Собирает конфигурацию профиля с учётом значений по умолчанию и legacy-config.
    Возвращает (runtime_config, updated_config_data, changed_flag).
    """
    config_data = deepcopy(config_data) if config_data else default_config_template()
    changed = False

    def _fallback(attr, default=''):
        return getattr(project_config, attr, default) if hasattr(project_config, attr) else default

    api_keys_cfg = config_data.get('api_keys') or {}
    runtime_api_keys = {
        'speechmatics_api_key': api_keys_cfg.get('speechmatics_api_key') or _fallback('SPEECHMATICS_API_KEY', ''),
        'thebai_api_key': api_keys_cfg.get('thebai_api_key') or _fallback('THEBAI_API_KEY', ''),
        'thebai_url': api_keys_cfg.get('thebai_url') or _fallback('THEBAI_URL', 'https://api.deepseek.com/v1/chat/completions'),
        'thebai_model': api_keys_cfg.get('thebai_model') or _fallback('THEBAI_MODEL', 'deepseek-reasoner'),
        'telegram_bot_token': api_keys_cfg.get('telegram_bot_token') or _fallback('TELEGRAM_BOT_TOKEN', '')
    }

    paths_cfg = config_data.get('paths') or {}
    base_records_path = (paths_cfg.get('base_records_path') or '').strip()
    default_base = _fallback('BASE_RECORDS_PATH', '')
    if user_id and default_base and not base_records_path:
        base_records_path = str(Path(str(default_base)) / 'users' / str(user_id))
        paths_cfg['base_records_path'] = base_records_path
        changed = True
    
    # Автоматически формируем пути к конфигурационным файлам в пользовательской директории
    user_config_dir = None
    if user_id and base_records_path:
        user_config_dir = Path(base_records_path) / 'config'
    
    prompts_file = paths_cfg.get('prompts_file') or ''
    if not prompts_file:
        if user_config_dir:
            prompts_file = str(user_config_dir / 'prompts.yaml')
            paths_cfg['prompts_file'] = prompts_file
            changed = True
        else:
            prompts_file = str(_fallback('PROMPTS_FILE', ''))
    
    additional_vocab_file = paths_cfg.get('additional_vocab_file') or ''
    if not additional_vocab_file:
        if user_config_dir:
            additional_vocab_file = str(user_config_dir / 'additional_vocab.yaml')
            paths_cfg['additional_vocab_file'] = additional_vocab_file
            changed = True
        else:
            additional_vocab_file = str(_fallback('ADDITIONAL_VOCAB_FILE', ''))
    
    script_prompt_file = paths_cfg.get('script_prompt_file') or ''
    if not script_prompt_file:
        if user_config_dir:
            script_prompt_file = str(user_config_dir / 'script_prompt_8.yaml')
            paths_cfg['script_prompt_file'] = script_prompt_file
            changed = True
        else:
            script_prompt_file = str(_fallback('SCRIPT_PROMPT_8_PATH', ''))
    runtime_paths = {
        'base_records_path': base_records_path or str(default_base),
        'prompts_file': prompts_file,
        'additional_vocab_file': additional_vocab_file,
        'script_prompt_file': script_prompt_file
    }
    config_data['paths'] = paths_cfg

    # Синхронизируем vocabulary.enabled с transcription.use_additional_vocab
    vocabulary_cfg = config_data.get('vocabulary') or {}
    vocab_enabled = vocabulary_cfg.get('enabled', True)  # По умолчанию True
    
    transcription_cfg = config_data.get('transcription') or {}
    # Если use_additional_vocab не задан явно, берем из vocabulary.enabled
    if 'use_additional_vocab' not in transcription_cfg:
        transcription_cfg['use_additional_vocab'] = vocab_enabled
        changed = True
    
    runtime = {
        'api_keys': runtime_api_keys,
        'paths': runtime_paths,
        'telegram': config_data.get('telegram') or {
            'alert_chat_id': _fallback('ALERT_CHAT_ID', ''),
            'tg_channel_nizh': _fallback('TG_CHANNEL_NIZH', ''),
            'tg_channel_other': _fallback('TG_CHANNEL_OTHER', '')
        },
        'employee_by_extension': config_data.get('employee_by_extension') or deepcopy(getattr(project_config, 'EMPLOYEE_BY_EXTENSION', {})),
        'stations': config_data.get('stations') or deepcopy(getattr(project_config, 'STATION_NAMES', {})),
        'station_chat_ids': config_data.get('station_chat_ids') or deepcopy(getattr(project_config, 'STATION_CHAT_IDS', {})),
        'station_mapping': config_data.get('station_mapping') or deepcopy(getattr(project_config, 'STATION_MAPPING', {})),
        'nizh_station_codes': config_data.get('nizh_station_codes') or list(getattr(project_config, 'NIZH_STATION_CODES', [])),
        'transcription': transcription_cfg if transcription_cfg else {
            'tbank_stereo_enabled': bool(getattr(project_config, 'TBANK_STEREO_ENABLED', False)),
            'use_additional_vocab': vocab_enabled
        },
        'filename': config_data.get('filename') or default_config_template()['filename'],
        'allowed_stations': config_data.get('allowed_stations')
    }
    
    # Обновляем config_data для сохранения синхронизации
    config_data['transcription'] = runtime['transcription']

    return runtime, config_data, changed
