-- SQL миграция для создания таблиц для нормализации данных из user_settings.data
-- Выполнить после создания моделей в database/models.py

-- Таблица конфигурации пользователя
CREATE TABLE IF NOT EXISTS user_config (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    source_type VARCHAR(50),
    prompts_file VARCHAR(1000),
    base_records_path VARCHAR(1000),
    ftp_connection_id INTEGER REFERENCES ftp_connections(id),
    script_prompt_file VARCHAR(1000),
    additional_vocab_file VARCHAR(1000),
    thebai_api_key VARCHAR(255),
    telegram_bot_token VARCHAR(255),
    speechmatics_api_key VARCHAR(255),
    alert_chat_id VARCHAR(100),
    tg_channel_nizh VARCHAR(100),
    tg_channel_other VARCHAR(100),
    tbank_stereo_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    use_additional_vocab BOOLEAN NOT NULL DEFAULT TRUE,
    auto_detect_operator_name BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_stations JSONB,
    nizh_station_codes JSONB,
    legal_entity_keywords JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_config_user ON user_config(user_id);

-- Таблица станций пользователя
CREATE TABLE IF NOT EXISTS user_stations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code VARCHAR(20) NOT NULL,
    name VARCHAR(500) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, code)
);

CREATE INDEX IF NOT EXISTS idx_station_user_code ON user_stations(user_id, code);

-- Таблица маппинга станций (основная -> подстанции)
CREATE TABLE IF NOT EXISTS user_station_mappings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    main_station_code VARCHAR(20) NOT NULL,
    sub_station_code VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, main_station_code, sub_station_code)
);

CREATE INDEX IF NOT EXISTS idx_mapping_user_main ON user_station_mappings(user_id, main_station_code);

-- Таблица chat_id станций
CREATE TABLE IF NOT EXISTS user_station_chat_ids (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    station_code VARCHAR(20) NOT NULL,
    chat_id VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, station_code, chat_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_user_station ON user_station_chat_ids(user_id, station_code);

-- Таблица маппинга расширений к сотрудникам
CREATE TABLE IF NOT EXISTS user_employee_extensions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    extension VARCHAR(20) NOT NULL,
    employee VARCHAR(200) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, extension)
);

CREATE INDEX IF NOT EXISTS idx_employee_user_ext ON user_employee_extensions(user_id, extension);

-- Таблица промптов пользователя
CREATE TABLE IF NOT EXISTS user_prompts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    prompt_type VARCHAR(50) NOT NULL,
    prompt_key VARCHAR(100) NOT NULL,
    prompt_text TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, prompt_type, prompt_key)
);

CREATE INDEX IF NOT EXISTS idx_prompt_user_type ON user_prompts(user_id, prompt_type);

-- Таблица словаря пользователя
CREATE TABLE IF NOT EXISTS user_vocabulary (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    additional_vocab JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vocab_user ON user_vocabulary(user_id);

-- Таблица промпта скрипта пользователя
CREATE TABLE IF NOT EXISTS user_script_prompts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    prompt_text TEXT NOT NULL,
    checklist JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_script_user ON user_script_prompts(user_id);
