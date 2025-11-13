#!/bin/bash
# setup_ubuntu.sh
# Скрипт первоначальной настройки сервера Ubuntu для Call Analyzer

set -e

echo "=========================================="
echo "  Настройка Ubuntu сервера для Call Analyzer"
echo "=========================================="
echo ""

# Проверка прав root
if [ "$EUID" -ne 0 ]; then 
    echo "Пожалуйста, запустите скрипт с правами root (sudo)"
    exit 1
fi

# Обновление системы
echo "Обновление системы..."
apt-get update
apt-get upgrade -y

# Установка базовых пакетов
echo "Установка базовых пакетов..."
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    postgresql \
    postgresql-contrib \
    nginx \
    supervisor \
    git \
    curl \
    wget \
    build-essential \
    libpq-dev \
    python3-dev \
    ffmpeg \
    libsndfile1

# Настройка PostgreSQL
echo "Настройка PostgreSQL..."
sudo -u postgres psql <<EOF
-- Создаем базу данных и пользователя
CREATE DATABASE call_analyzer;
CREATE USER call_analyzer WITH PASSWORD 'change_this_password_in_production';
ALTER ROLE call_analyzer SET client_encoding TO 'utf8';
ALTER ROLE call_analyzer SET default_transaction_isolation TO 'read committed';
ALTER ROLE call_analyzer SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE call_analyzer TO call_analyzer;
\q
EOF

echo "✓ PostgreSQL настроен"
echo "⚠ ВАЖНО: Смените пароль базы данных в production!"

# Создание пользователя для приложения
APP_USER="callanalyzer"
if ! id "$APP_USER" &>/dev/null; then
    echo "Создание пользователя $APP_USER..."
    useradd -m -s /bin/bash $APP_USER
    echo "✓ Пользователь создан"
else
    echo "✓ Пользователь $APP_USER уже существует"
fi

# Создание директорий
echo "Создание директорий..."
mkdir -p /var/calls
mkdir -p /opt/call-analyzer
mkdir -p /var/log/call-analyzer
chown -R $APP_USER:$APP_USER /var/calls
chown -R $APP_USER:$APP_USER /opt/call-analyzer
chown -R $APP_USER:$APP_USER /var/log/call-analyzer

echo ""
echo "=========================================="
echo "  Настройка завершена!"
echo "=========================================="
echo ""
echo "Следующие шаги:"
echo "1. Скопируйте проект в /opt/call-analyzer"
echo "2. Настройте переменные окружения в /opt/call-analyzer/.env"
echo "3. Запустите deploy/deploy.sh для установки приложения"
echo ""

