-- Миграция: добавление полей для ручного выбора периода в таблицу report_schedules
-- Выполнить после обновления модели в database/models.py

ALTER TABLE report_schedules
    ADD COLUMN IF NOT EXISTS manual_start_date DATE,
    ADD COLUMN IF NOT EXISTS manual_end_date DATE;
