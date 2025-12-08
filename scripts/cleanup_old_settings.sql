-- SQL скрипт для очистки старых данных из user_settings
-- ВНИМАНИЕ: Выполняйте только после полной миграции данных и обновления кода!

-- Вариант 1: Очистить только колонку data (оставить таблицу для совместимости)
UPDATE user_settings SET data = '{}'::jsonb WHERE data IS NOT NULL;

-- Вариант 2: Удалить колонку data полностью (если код полностью обновлен)
-- ALTER TABLE user_settings DROP COLUMN IF EXISTS data;

-- Вариант 3: Удалить всю таблицу user_settings (если она больше не нужна)
-- ВНИМАНИЕ: Это удалит таблицу полностью! Убедитесь, что код не использует UserSettings!
-- DROP TABLE IF EXISTS user_settings CASCADE;

-- Проверка результатов
SELECT 
    COUNT(*) as total_settings,
    COUNT(CASE WHEN data = '{}'::jsonb OR data IS NULL THEN 1 END) as empty_data,
    COUNT(CASE WHEN data != '{}'::jsonb AND data IS NOT NULL THEN 1 END) as has_data
FROM user_settings;
