-- Миграция: источник привязки номеров + метаданные строк
-- Применение к существующей БД PostgreSQL:
--
--   Вариант 1 (рекомендуется, как остальные миграции в проекте):
--     python scripts/migrate_employee_mapping_sources.py
--
--   Вариант 2 (если установлен psql):
--     psql "%DATABASE_URL%" -f scripts/migration_employee_mapping_sources.sql
--
-- Не запускайте этот файл через «python имя_файла.sql» — это не Python.

-- Таблица настроек внешнего источника (одна строка на пользователя)
CREATE TABLE IF NOT EXISTS user_employee_mapping_sources (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    mode VARCHAR(40) NOT NULL DEFAULT 'manual',
    provider_type VARCHAR(40) NOT NULL DEFAULT 'generic_rest_json',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    refresh_ttl_seconds INTEGER NOT NULL DEFAULT 300,
    request_config JSONB,
    mapping_config JSONB,
    normalize_config JSONB,
    last_success_at TIMESTAMP,
    last_attempt_at TIMESTAMP,
    last_sync_ok BOOLEAN,
    last_sync_error VARCHAR(500),
    last_records_count INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_emp_map_src_user ON user_employee_mapping_sources(user_id);

-- Расширение user_employee_extensions
ALTER TABLE user_employee_extensions
    ADD COLUMN IF NOT EXISTS origin_type VARCHAR(20) NOT NULL DEFAULT 'manual';

ALTER TABLE user_employee_extensions
    ADD COLUMN IF NOT EXISTS external_ref VARCHAR(120);

ALTER TABLE user_employee_extensions
    ADD COLUMN IF NOT EXISTS synced_at TIMESTAMP;

-- Существующие строки считаем ручными
UPDATE user_employee_extensions SET origin_type = 'manual' WHERE origin_type IS NULL OR origin_type = '';
