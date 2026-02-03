-- Миграция: добавление колонки business_profile в user_config
-- Выполните: psql -U user -d database -f migrate_add_business_profile.sql

ALTER TABLE user_config
ADD COLUMN IF NOT EXISTS business_profile VARCHAR(50) NOT NULL DEFAULT 'autoservice';
