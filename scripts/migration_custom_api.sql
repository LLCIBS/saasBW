-- Миграция: источник «Кастомный API» (REST JSON → скачивание записей)
-- Применение:
--   python scripts/migrate_custom_api.py
-- или:
--   psql "%DATABASE_URL%" -f scripts/migration_custom_api.sql

CREATE TABLE IF NOT EXISTS custom_api_connections (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL DEFAULT 'Кастомный API',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    request_config JSONB,
    mapping_config JSONB,
    start_from TIMESTAMP,
    sync_interval_minutes INTEGER NOT NULL DEFAULT 60,
    last_sync TIMESTAMP,
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_custom_api_user_active ON custom_api_connections(user_id, is_active);

CREATE TABLE IF NOT EXISTS custom_api_imported_calls (
    id SERIAL PRIMARY KEY,
    connection_id INTEGER NOT NULL REFERENCES custom_api_connections(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    external_key VARCHAR(128) NOT NULL,
    record_url TEXT,
    saved_path VARCHAR(2000),
    raw_payload JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'ok',
    error_message TEXT,
    downloaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_api_import_conn_ext
    ON custom_api_imported_calls(connection_id, external_key);

CREATE INDEX IF NOT EXISTS idx_custom_api_import_user ON custom_api_imported_calls(user_id);

ALTER TABLE user_config
    ADD COLUMN IF NOT EXISTS custom_api_connection_id INTEGER REFERENCES custom_api_connections(id);
