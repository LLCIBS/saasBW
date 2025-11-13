#!/bin/bash
# deploy.sh
# Скрипт деплоя Call Analyzer на Ubuntu сервер

set -e

APP_USER="callanalyzer"
APP_DIR="/opt/call-analyzer"
VENV_DIR="$APP_DIR/venv"
LOG_DIR="/var/log/call-analyzer"

echo "=========================================="
echo "  Деплой Call Analyzer"
echo "=========================================="
echo ""

# Проверка, что скрипт запущен от правильного пользователя
if [ "$USER" != "$APP_USER" ] && [ "$USER" != "root" ]; then
    echo "Запустите скрипт от пользователя $APP_USER или root"
    exit 1
fi

# Переход в директорию приложения
cd $APP_DIR

# Создание виртуального окружения, если его нет
if [ ! -d "$VENV_DIR" ]; then
    echo "Создание виртуального окружения..."
    python3 -m venv $VENV_DIR
fi

# Активация виртуального окружения
echo "Активация виртуального окружения..."
source $VENV_DIR/bin/activate

# Обновление pip
echo "Обновление pip..."
pip install --upgrade pip

# Установка зависимостей
echo "Установка зависимостей..."
pip install -r requirements.txt

# Установка Tinkoff VoiceKit отдельно (без зависимостей)
echo "Установка Tinkoff VoiceKit..."
pip install --no-deps tinkoff-voicekit-client==0.3.3
pip install "boto3==1.40.49" "botocore==1.40.49" "aiobotocore==2.25.0" "aioboto3==15.4.0"

# Проверка наличия .env файла
if [ ! -f "$APP_DIR/.env" ]; then
    echo "⚠ ВНИМАНИЕ: Файл .env не найден!"
    echo "Создайте файл .env на основе .env.example"
    exit 1
fi

# Инициализация базы данных
echo "Инициализация базы данных..."
python3 scripts/init_db.py

# Миграция данных из JSON (если нужно)
if [ -f "$APP_DIR/transfer_cases.json" ] || [ -f "$APP_DIR/recall_cases.json" ]; then
    echo "Миграция данных из JSON в базу данных..."
    python3 scripts/migrate_json_to_db.py
fi

# Создание директорий для логов
mkdir -p $LOG_DIR
chown -R $APP_USER:$APP_USER $LOG_DIR

# Перезапуск сервисов
echo "Перезапуск сервисов..."
if [ "$USER" = "root" ]; then
    systemctl restart call-analyzer-service
    systemctl restart call-analyzer-web
    systemctl restart nginx
else
    echo "Для перезапуска сервисов выполните:"
    echo "  sudo systemctl restart call-analyzer-service"
    echo "  sudo systemctl restart call-analyzer-web"
    echo "  sudo systemctl restart nginx"
fi

echo ""
echo "=========================================="
echo "  Деплой завершен!"
echo "=========================================="
echo ""
echo "Проверьте статус сервисов:"
echo "  sudo systemctl status call-analyzer-service"
echo "  sudo systemctl status call-analyzer-web"
echo ""

