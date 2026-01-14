-- SQL миграция для создания таблицы report_schedules
-- Выполнить после создания модели в database/models.py

CREATE TABLE IF NOT EXISTS report_schedules (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    report_type VARCHAR(50) NOT NULL,
    schedule_type VARCHAR(20) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,

    daily_time VARCHAR(5),
    interval_value INTEGER,
    interval_unit VARCHAR(10),
    weekly_day INTEGER,
    weekly_time VARCHAR(5),
    cron_expression VARCHAR(100),

    auto_start_date BOOLEAN NOT NULL DEFAULT TRUE,
    auto_end_date BOOLEAN NOT NULL DEFAULT TRUE,
    date_offset_days INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,

    CONSTRAINT uq_report_schedule_user_report UNIQUE (user_id, report_type)
);

CREATE INDEX IF NOT EXISTS idx_report_schedule_user ON report_schedules(user_id);
