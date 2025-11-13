# Подробная инструкция по развертыванию проекта на VPS 217.114.0.58

## Краткое резюме

Эта инструкция описывает полный процесс развертывания Call Analyzer на Ubuntu VPS сервере с IP адресом **217.114.0.58**.

**Основные шаги:**
1. Подготовка сервера (обновление, установка пакетов)
2. Копирование проекта на сервер
3. Установка зависимостей Python
4. **⚠️ Установка и настройка PostgreSQL базы данных (ОБЯЗАТЕЛЬНО!)**
5. Настройка переменных окружения (.env)
6. Настройка systemd сервисов
7. Настройка Nginx (с IP адресом вместо домена)
8. Инициализация базы данных
9. Запуск и проверка работы

**Чек-лист критических шагов:**
- ✅ PostgreSQL установлен и запущен
- ✅ База данных `call_analyzer` создана
- ✅ Пользователь `call_analyzer` создан с паролем
- ✅ Файл `.env` настроен с правильным `DATABASE_URL`
- ✅ База данных инициализирована (таблицы созданы)

**Время выполнения:** примерно 30-60 минут (в зависимости от скорости интернета и сервера)

**Требования:**
- Ubuntu 20.04 или новее
- Минимум 2GB RAM
- Минимум 10GB свободного места
- Доступ с правами root или sudo

---

## Оглавление
1. [Подготовка сервера](#1-подготовка-сервера)
2. [Копирование проекта на сервер](#2-копирование-проекта-на-сервер)
3. [Установка зависимостей](#3-установка-зависимостей)
4. [Настройка базы данных PostgreSQL](#4-настройка-базы-данных-postgresql)
5. [Настройка переменных окружения](#5-настройка-переменных-окружения)
6. [Установка и настройка systemd сервисов](#6-установка-и-настройка-systemd-сервисов)
7. [Настройка Nginx](#7-настройка-nginx)
8. [Инициализация базы данных](#8-инициализация-базы-данных)
9. [Запуск сервисов](#9-запуск-сервисов)
10. [Проверка работы](#10-проверка-работы)
11. [Управление сервисами](#11-управление-сервисами)
12. [Устранение неполадок](#12-устранение-неполадок)

---

## 1. Подготовка сервера

### 1.1 Подключение к серверу

Подключитесь к серверу по SSH:

```bash
ssh root@217.114.0.58
```

Или, если у вас есть пользователь с sudo правами:

```bash
ssh ваш_пользователь@217.114.0.58
```

### 1.2 Обновление системы

```bash
sudo apt update
sudo apt upgrade -y
```

### 1.3 Установка базовых пакетов

**⚠️ ВАЖНО: PostgreSQL будет установлен и настроен в разделе 4. Здесь мы устанавливаем только пакеты.**

Запустите скрипт настройки (если он есть в проекте):

```bash
# Если вы уже скопировали проект
cd /opt/call-analyzer
sudo bash deploy/setup_ubuntu.sh
```

Или установите вручную:

```bash
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    postgresql \
    postgresql-contrib \
    nginx \
    git \
    curl \
    wget \
    build-essential \
    libpq-dev \
    python3-dev \
    ffmpeg \
    libsndfile1 \
    supervisor
```

**Примечание:** PostgreSQL установится здесь, но его настройка (создание БД и пользователя) выполняется в разделе 4. Не пропускайте раздел 4!

### 1.4 Создание пользователя для приложения

```bash
# Создаем пользователя callanalyzer
sudo useradd -m -s /bin/bash callanalyzer

# ВАЖНО: Пользователь создается БЕЗ пароля
# Это означает, что вход через SSH с паролем будет недоступен
# Доступ возможен только через sudo от root или через SSH ключи

# Добавляем пользователя в группу sudo (для выполнения административных команд)
sudo usermod -aG sudo callanalyzer

# Настраиваем sudo без пароля для пользователя callanalyzer (рекомендуется)
# Это позволит выполнять sudo команды без ввода пароля
echo "callanalyzer ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/callanalyzer
sudo chmod 0440 /etc/sudoers.d/callanalyzer

# Альтернатива: Если нужен пароль для пользователя (менее безопасно)
# sudo passwd callanalyzer
# Введите новый пароль дважды

# Создаем необходимые директории
sudo mkdir -p /opt/call-analyzer
sudo mkdir -p /var/calls
sudo mkdir -p /var/log/call-analyzer

# Устанавливаем права доступа
sudo chown -R callanalyzer:callanalyzer /opt/call-analyzer
sudo chown -R callanalyzer:callanalyzer /var/calls
sudo chown -R callanalyzer:callanalyzer /var/log/call-analyzer
```

**Примечание о пароле и sudo для пользователя callanalyzer:**
- По умолчанию пользователь создается **БЕЗ пароля**
- Пользователь добавлен в группу `sudo` для выполнения административных команд
- Настроен `NOPASSWD` для sudo (можно выполнять sudo без пароля)
- Если вы хотите использовать пароль для sudo, установите его: `sudo passwd callanalyzer`
- Рекомендуется использовать SSH-ключи вместо пароля для безопасности

---

## 2. Копирование проекта на сервер

### 2.1 Способ 1: Через SCP (с локального компьютера)

На вашем локальном компьютере (Windows PowerShell):

```powershell
# Перейдите в директорию проекта
cd "D:\ООО ИБС\Бествей\Система чек листов коммерция BW\saasBW"

# Скопируйте проект на сервер
scp -r . root@217.114.0.58:/opt/call-analyzer
```

### 2.2 Способ 2: Через Git (если проект в репозитории)

На сервере:

```bash
cd /opt
sudo git clone ваш-репозиторий-url call-analyzer
sudo chown -R callanalyzer:callanalyzer /opt/call-analyzer
```

### 2.3 Способ 3: Через архив

На локальном компьютере:

```powershell
# Создайте архив проекта (исключая venv и __pycache__)
# Используйте WinRAR, 7-Zip или tar
```

Затем скопируйте архив на сервер и распакуйте:

```bash
# На сервере
cd /opt
sudo tar -xzf call-analyzer.tar.gz
sudo mv saasBW call-analyzer
sudo chown -R callanalyzer:callanalyzer /opt/call-analyzer
```

---

## 3. Установка зависимостей

### 3.1 Автоматическая установка (рекомендуется)

Если в проекте есть скрипт `deploy/deploy.sh`, используйте его:

```bash
sudo su - callanalyzer
cd /opt/call-analyzer
bash deploy/deploy.sh
```

Скрипт автоматически:
- Создаст виртуальное окружение
- Установит все зависимости
- Установит Tinkoff VoiceKit
- Инициализирует базу данных

**Примечание:** Скрипт может попытаться перезапустить сервисы. Если сервисы еще не настроены, это нормально.

### 3.2 Ручная установка (если скрипт не работает)

#### 3.2.1 Переключение на пользователя приложения

```bash
sudo su - callanalyzer
cd /opt/call-analyzer
```

#### 3.2.2 Создание виртуального окружения

```bash
python3 -m venv venv
source venv/bin/activate
```

#### 3.2.3 Обновление pip

```bash
pip install --upgrade pip
```

#### 3.2.4 Установка зависимостей

```bash
pip install -r requirements.txt
```

#### 3.2.5 Установка Tinkoff VoiceKit (если требуется)

```bash
# Установка без зависимостей (чтобы избежать конфликтов)
pip install --no-deps tinkoff-voicekit-client==0.3.3
pip install "boto3==1.40.49" "botocore==1.40.49" "aiobotocore==2.25.0" "aioboto3==15.4.0"
```

---

## 4. Установка и настройка базы данных PostgreSQL

**⚠️ ВАЖНО: Этот шаг обязателен! Без PostgreSQL приложение не будет работать.**

### 4.1 Проверка установки PostgreSQL

Сначала проверьте, установлен ли PostgreSQL:

```bash
# Проверка версии PostgreSQL
psql --version
```

Если PostgreSQL не установлен, установите его:

```bash
# Установка PostgreSQL и необходимых пакетов
sudo apt update
sudo apt install -y postgresql postgresql-contrib

# Проверка статуса службы
sudo systemctl status postgresql
```

Если служба не запущена, запустите её:

```bash
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

### 4.2 Проверка работы PostgreSQL

Убедитесь, что PostgreSQL работает:

```bash
# Проверка статуса
sudo systemctl status postgresql

# Должен показать "active (running)"
```

### 4.3 Подключение к PostgreSQL

Подключитесь к PostgreSQL от имени пользователя postgres:

```bash
sudo -u postgres psql
```

Вы должны увидеть приглашение `postgres=#`

### 4.4 Создание базы данных и пользователя

В консоли PostgreSQL выполните следующие команды (скопируйте и вставьте по очереди):

```sql
-- Создаем базу данных
CREATE DATABASE call_analyzer;

-- Создаем пользователя (ЗАМЕНИТЕ 'ваш_безопасный_пароль' на реальный пароль!)
-- Пример безопасного пароля: MyStr0ng!P@ssw0rd
CREATE USER call_analyzer WITH PASSWORD 'BestWayCalls!';

-- Настраиваем кодировку и параметры
ALTER ROLE call_analyzer SET client_encoding TO 'utf8';
ALTER ROLE call_analyzer SET default_transaction_isolation TO 'read committed';
ALTER ROLE call_analyzer SET timezone TO 'UTC';

-- Предоставляем права на базу данных
GRANT ALL PRIVILEGES ON DATABASE call_analyzer TO call_analyzer;

-- Предоставляем права на схему public (для создания таблиц)
\c call_analyzer
GRANT ALL ON SCHEMA public TO call_analyzer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO call_analyzer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO call_analyzer;

-- Выходим из psql
\q
```

**⚠️ ВАЖНО:** Запомните пароль, который вы установили! Он понадобится в следующем разделе для настройки `.env` файла.

### 4.5 Проверка создания базы данных

Проверьте, что база данных создана успешно:

**Способ 1: Проверка с паролем через переменную окружения (рекомендуется)**

```bash
# Замените 'ваш_пароль' на пароль, который вы установили в разделе 4.4
# Например: 'BestWayCalls!' или 'change_this_password_in_production'
PGPASSWORD='ваш_пароль' psql -h localhost -U call_analyzer -d call_analyzer -c "SELECT version();"
```

Если команда выполнилась успешно и показала версию PostgreSQL, значит подключение работает!

**Способ 2: Интерактивное подключение с паролем**

```bash
# Подключение к базе данных с новым пользователем
psql -h localhost -U call_analyzer -d call_analyzer

# Система запросит пароль - введите пароль, который вы установили
# Должно показать приглашение call_analyzer=>

# Проверка версии PostgreSQL
SELECT version();

# Проверка списка баз данных
\l

# Проверка текущей базы данных
SELECT current_database();

# Выход
\q
```

**Способ 3: Проверка через sudo (без пароля, но требует прав postgres)**

```bash
# Этот способ работает только если вы под root или через sudo
sudo -u postgres psql -d call_analyzer -c "\du" | grep call_analyzer
```

**Примеры проверки:**

```bash
# Проверка 1: Версия PostgreSQL
PGPASSWORD='BestWayCalls!' psql -h localhost -U call_analyzer -d call_analyzer -c "SELECT version();"

# Проверка 2: Список таблиц (после инициализации БД)
PGPASSWORD='BestWayCalls!' psql -h localhost -U call_analyzer -d call_analyzer -c "\dt"

# Проверка 3: Информация о пользователе
PGPASSWORD='BestWayCalls!' psql -h localhost -U call_analyzer -d call_analyzer -c "\du call_analyzer"
```

Если подключение не работает, проверьте настройки доступа (см. следующий раздел).

### 4.6 Настройка доступа PostgreSQL

Отредактируйте файл конфигурации доступа:

```bash
# Найдем версию PostgreSQL
sudo -u postgres psql -c "SELECT version();"

# Обычно это 12, 13, 14, 15 или 16
# Замените XX на вашу версию в следующей команде
sudo nano /etc/postgresql/XX/main/pg_hba.conf
```

Или используйте автопоиск:

```bash
sudo find /etc/postgresql -name pg_hba.conf
# Затем откройте найденный файл
sudo nano /etc/postgresql/16/main/pg_hba.conf
```

Убедитесь, что есть следующие строки (для локальных подключений):

**Для PostgreSQL 16 (используется scram-sha-256):**
```
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     peer
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
```

**Для PostgreSQL 12-15 (может использоваться md5):**
```
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     peer
host    all             all             127.0.0.1/32            md5
host    all             all             ::1/128                 md5
```

**✅ Важно:** 
- В PostgreSQL 16 используется `scram-sha-256` (более безопасный метод)
- В более старых версиях может быть `md5`
- Оба метода работают с паролями
- Если вы видите `scram-sha-256` в вашем файле - это правильно и не нужно менять!

Если нужных строк нет, добавьте их в конец файла (используйте `scram-sha-256` для PostgreSQL 16).

Сохраните файл (Ctrl+O, Enter, Ctrl+X в nano).

### 4.7 Перезапуск PostgreSQL

После изменения конфигурации перезапустите PostgreSQL:

```bash
sudo systemctl restart postgresql
```

### 4.8 Финальная проверка подключения

Проверьте подключение с паролем:

```bash
# Этот запрос должен запросить пароль
PGPASSWORD='ваш_безопасный_пароль' psql -h localhost -U call_analyzer -d call_analyzer -c "SELECT version();"
```

Если команда выполнилась успешно и показала версию PostgreSQL, значит всё настроено правильно!

**✅ PostgreSQL готов к использованию!**

---

## 5. Настройка переменных окружения

**⚠️ ВАЖНО: Перед настройкой .env убедитесь, что вы выполнили раздел 4 и создали базу данных PostgreSQL!**

### 5.1 Создание файла .env

```bash
cd /opt/call-analyzer
cp .env.example .env
nano .env
```

### 5.2 Заполнение .env файла

**⚠️ ВАЖНО: Используйте пароль PostgreSQL, который вы установили в разделе 4.4!**

Отредактируйте файл `.env` со следующими значениями:

```bash
# Окружение
FLASK_ENV=production

# Секретный ключ Flask (сгенерируйте случайную строку)
# Можно использовать: python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=сгенерируйте_случайную_строку_здесь

# База данных PostgreSQL
# ⚠️ ЗАМЕНИТЕ 'ваш_безопасный_пароль' на пароль, который вы установили в разделе 4.4!
# Пример: DATABASE_URL=postgresql://call_analyzer:BestWayCalls!@localhost/call_analyzer
DATABASE_URL=postgresql://call_analyzer:ваш_безопасный_пароль@localhost/call_analyzer

# Или используйте отдельные параметры (если DATABASE_URL не работает):
DB_HOST=localhost
DB_PORT=5432
DB_USER=call_analyzer
DB_PASSWORD=ваш_безопасный_пароль
DB_NAME=call_analyzer

# ⚠️ ВАЖНО: 
# - Пользователь БД: call_analyzer (НЕ postgres!)
# - База данных: call_analyzer (НЕ saas!)
# - Пароль: тот, который вы установили в разделе 4.4

# Пути к файлам
BASE_RECORDS_PATH=/var/calls
PROMPTS_FILE=/opt/call-analyzer/prompts.yaml
ADDITIONAL_VOCAB_FILE=/opt/call-analyzer/additional_vocab.yaml

# API ключи (заполните своими значениями)
SPEECHMATICS_API_KEY=ваш_ключ_здесь
TBANK_API_KEY=ваш_ключ_здесь
TBANK_SECRET_KEY=ваш_секретный_ключ_здесь
TBANK_STEREO_ENABLED=True

THEBAI_API_KEY=ваш_ключ_здесь
THEBAI_URL=https://api.deepseek.com/v1/chat/completions
THEBAI_MODEL=deepseek-reasoner

# Telegram (заполните своими значениями)
TELEGRAM_BOT_TOKEN=ваш_токен_здесь
ALERT_CHAT_ID=ваш_chat_id
LEGAL_ENTITY_CHAT_ID=ваш_chat_id
TG_CHANNEL_NIZH=ваш_chat_id
TG_CHANNEL_OTHER=ваш_chat_id

# Логирование
LOG_LEVEL=INFO
LOG_FILE=/var/log/call-analyzer/app.log

# Администратор (для первого входа - ОБЯЗАТЕЛЬНО СМЕНИТЕ!)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=измените_этот_пароль

# Flask настройки
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
```

### 5.3 Установка прав доступа на .env

```bash
sudo chmod 600 /opt/call-analyzer/.env
sudo chown callanalyzer:callanalyzer /opt/call-analyzer/.env
```

---

## 6. Установка и настройка systemd сервисов

### 6.1 Копирование файлов сервисов

```bash
sudo cp /opt/call-analyzer/deploy/systemd/call-analyzer-service.service /etc/systemd/system/
sudo cp /opt/call-analyzer/deploy/systemd/call-analyzer-web.service /etc/systemd/system/
```

### 6.2 Проверка и редактирование сервисов

Проверьте пути в файлах сервисов:

```bash
sudo nano /etc/systemd/system/call-analyzer-service.service
sudo nano /etc/systemd/system/call-analyzer-web.service
```

Убедитесь, что пути правильные:
- `WorkingDirectory=/opt/call-analyzer`
- `ExecStart=/opt/call-analyzer/venv/bin/python /opt/call-analyzer/call_analyzer/main.py` (для service)
- `ExecStart=/opt/call-analyzer/venv/bin/python /opt/call-analyzer/web_interface/app.py` (для web)

**Альтернативный вариант:** Если вы хотите использовать единый `app.py` в корне (который запускает и веб, и сервис), создайте один сервис:

```bash
sudo nano /etc/systemd/system/call-analyzer.service
```

Содержимое:

```ini
[Unit]
Description=Call Analyzer (Web + Service)
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=callanalyzer
Group=callanalyzer
WorkingDirectory=/opt/call-analyzer
Environment="PATH=/opt/call-analyzer/venv/bin"
EnvironmentFile=/opt/call-analyzer/.env
ExecStart=/opt/call-analyzer/venv/bin/python /opt/call-analyzer/app.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/call-analyzer/app.log
StandardError=append:/var/log/call-analyzer/app.error.log

[Install]
WantedBy=multi-user.target
```

Тогда используйте только этот сервис вместо двух отдельных.

### 6.3 Перезагрузка systemd

```bash
sudo systemctl daemon-reload
```

### 6.4 Включение автозапуска

```bash
sudo systemctl enable call-analyzer-service
sudo systemctl enable call-analyzer-web
```

---

## 7. Настройка Nginx

**⚠️ ВАЖНО: Перед настройкой Nginx убедитесь, что он установлен!**

### 7.0 Проверка установки Nginx

Проверьте, установлен ли Nginx:

```bash
# Проверка версии Nginx
nginx -v
```

Если команда показывает версию (например, `nginx version: nginx/1.18.0`), значит Nginx установлен.

**Если Nginx НЕ установлен**, установите его:

```bash
# Обновление списка пакетов
sudo apt update

# Установка Nginx
sudo apt install -y nginx

# Проверка статуса
sudo systemctl status nginx
```

Если служба не запущена, запустите её:

```bash
sudo systemctl start nginx
sudo systemctl enable nginx
```

**Проверка работы Nginx:**

```bash
# Проверка статуса
sudo systemctl status nginx

# Должен показать "active (running)"
```

Если Nginx работает, вы можете открыть в браузере `http://217.114.0.58` и увидеть страницу приветствия Nginx (до настройки проксирования).

### 7.1 Копирование конфигурации

```bash
sudo cp /opt/call-analyzer/deploy/nginx/call-analyzer.conf /etc/nginx/sites-available/call-analyzer
```

### 7.2 Редактирование конфигурации для IP адреса

```bash
sudo nano /etc/nginx/sites-available/call-analyzer
```

Измените конфигурацию следующим образом:

```nginx
upstream call_analyzer_web {
    server 127.0.0.1:5000;
    keepalive 32;
}

server {
    listen 80;
    server_name 217.114.0.58;  # Используем IP адрес вместо домена

    # Логи
    access_log /var/log/nginx/call-analyzer-access.log;
    error_log /var/log/nginx/call-analyzer-error.log;

    # Максимальный размер загружаемых файлов
    client_max_body_size 100M;

    # Проксирование на Flask приложение
    location / {
        proxy_pass http://call_analyzer_web;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Таймауты для долгих запросов (генерация отчетов)
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    # Статические файлы (если есть)
    location /static {
        alias /opt/call-analyzer/web_interface/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

### 7.3 Включение сайта

```bash
# Создаем симлинк
sudo ln -s /etc/nginx/sites-available/call-analyzer /etc/nginx/sites-enabled/

# Удаляем дефолтный сайт (опционально)
sudo rm /etc/nginx/sites-enabled/default

# Проверяем конфигурацию
sudo nginx -t
```

Если проверка прошла успешно, перезапустите Nginx:

```bash
sudo systemctl restart nginx
```

### 7.4 Настройка firewall (если используется)

```bash
# Разрешаем HTTP трафик
sudo ufw allow 80/tcp
sudo ufw allow 22/tcp  # SSH
sudo ufw enable
```

---

## 8. Инициализация базы данных

**Примечание:** Если вы использовали `deploy/deploy.sh` в разделе 3, инициализация базы данных уже выполнена. Пропустите этот раздел или выполните только миграцию JSON (если нужно).

### 8.1 Переключение на пользователя приложения

```bash
sudo su - callanalyzer
cd /opt/call-analyzer
source venv/bin/activate
```

### 8.2 Инициализация базы данных

```bash
# Проверьте, что .env файл настроен правильно
python3 scripts/init_db.py
```

Или, если используется другой скрипт:

```bash
python3 init_db_fixed.py
```

### 8.3 Миграция данных из JSON (если есть)

Если у вас есть файлы `transfer_cases.json` или `recall_cases.json`:

```bash
python3 scripts/migrate_json_to_db.py
```

---

## 9. Запуск сервисов

### 9.1 Запуск systemd сервисов

**Вариант 1: Два отдельных сервиса (как в конфигах по умолчанию)**

```bash
sudo systemctl start call-analyzer-service
sudo systemctl start call-analyzer-web
```

**Вариант 2: Единый сервис (если вы создали call-analyzer.service)**

```bash
sudo systemctl start call-analyzer
```

### 9.2 Проверка статуса

**Для двух сервисов:**
```bash
sudo systemctl status call-analyzer-service
sudo systemctl status call-analyzer-web
sudo systemctl status nginx
```

**Для единого сервиса:**
```bash
sudo systemctl status call-analyzer
sudo systemctl status nginx
```

Если сервисы не запускаются, проверьте логи:

**Для двух сервисов:**
```bash
sudo journalctl -u call-analyzer-service -n 50
sudo journalctl -u call-analyzer-web -n 50
```

**Для единого сервиса:**
```bash
sudo journalctl -u call-analyzer -n 50
```

---

## 10. Проверка работы

### 10.1 Проверка через браузер

Откройте в браузере:

```
http://217.114.0.58
```

Вы должны увидеть страницу входа в систему.

### 10.2 Первый вход

Используйте учетные данные администратора из файла `.env`:
- **Логин:** `admin` (или значение из `ADMIN_USERNAME`)
- **Пароль:** пароль из `ADMIN_PASSWORD` в `.env`

**ВАЖНО:** Сразу после первого входа смените пароль администратора!

### 10.3 Проверка логов

```bash
# Логи сервисов
sudo journalctl -u call-analyzer-service -f
sudo journalctl -u call-analyzer-web -f

# Логи приложения
tail -f /var/log/call-analyzer/*.log

# Логи Nginx
sudo tail -f /var/log/nginx/call-analyzer-access.log
sudo tail -f /var/log/nginx/call-analyzer-error.log
```

---

## 11. Управление сервисами

### 11.1 Просмотр статуса

**Для двух сервисов:**
```bash
sudo systemctl status call-analyzer-service
sudo systemctl status call-analyzer-web
sudo systemctl status nginx
```

**Для единого сервиса:**
```bash
sudo systemctl status call-analyzer
sudo systemctl status nginx
```

### 11.2 Перезапуск сервисов

**Для двух сервисов:**
```bash
sudo systemctl restart call-analyzer-service
sudo systemctl restart call-analyzer-web
sudo systemctl restart nginx
```

**Для единого сервиса:**
```bash
sudo systemctl restart call-analyzer
sudo systemctl restart nginx
```

### 11.3 Остановка сервисов

**Для двух сервисов:**
```bash
sudo systemctl stop call-analyzer-service
sudo systemctl stop call-analyzer-web
```

**Для единого сервиса:**
```bash
sudo systemctl stop call-analyzer
```

### 11.4 Просмотр логов

**Для двух сервисов:**
```bash
# Логи сервиса анализа
sudo journalctl -u call-analyzer-service -f

# Логи веб-интерфейса
sudo journalctl -u call-analyzer-web -f

# Логи приложения
tail -f /var/log/call-analyzer/*.log

# Логи Nginx
sudo tail -f /var/log/nginx/call-analyzer-error.log
```

**Для единого сервиса:**
```bash
# Логи приложения
sudo journalctl -u call-analyzer -f

# Логи приложения (файлы)
tail -f /var/log/call-analyzer/*.log

# Логи Nginx
sudo tail -f /var/log/nginx/call-analyzer-error.log
```

---

## 12. Устранение неполадок

### 12.1 Сервис не запускается

**Проблема:** Сервис не стартует или сразу падает.

**Решение:**

1. Проверьте логи:
```bash
sudo journalctl -u call-analyzer-web -n 100
```

2. Проверьте файл `.env`:
```bash
cat /opt/call-analyzer/.env
```

3. Проверьте права доступа:
```bash
ls -la /opt/call-analyzer
ls -la /opt/call-analyzer/.env
```

4. Проверьте виртуальное окружение:
```bash
sudo su - callanalyzer
cd /opt/call-analyzer
source venv/bin/activate
python --version
which python
```

5. Попробуйте запустить вручную:
```bash
sudo su - callanalyzer
cd /opt/call-analyzer
source venv/bin/activate
python web_interface/app.py
```

### 12.2 База данных не подключается

**Проблема:** Ошибки подключения к PostgreSQL.

**Решение:**

1. **Проверьте, установлен ли PostgreSQL:**
```bash
psql --version
sudo systemctl status postgresql
```

Если PostgreSQL не установлен, вернитесь к разделу 4 и выполните установку.

2. **Проверьте, создана ли база данных:**
```bash
sudo -u postgres psql -c "\l" | grep call_analyzer
```

Если база данных не существует, вернитесь к разделу 4.4 и создайте её.

3. **Проверьте, создан ли пользователь:**
```bash
sudo -u postgres psql -c "\du" | grep call_analyzer
```

Если пользователь не существует, вернитесь к разделу 4.4 и создайте его.

4. **Проверьте подключение:**
```bash
# Попробуйте подключиться с паролем
PGPASSWORD='ваш_пароль' psql -h localhost -U call_analyzer -d call_analyzer -c "SELECT 1;"
```

5. **Проверьте `DATABASE_URL` в `.env`:**
```bash
grep DATABASE_URL /opt/call-analyzer/.env
```

Убедитесь, что пароль в `.env` совпадает с паролем, который вы установили в разделе 4.4.

6. **Проверьте права пользователя:**
```bash
sudo -u postgres psql -d call_analyzer -c "\dn"
sudo -u postgres psql -d call_analyzer -c "SELECT * FROM information_schema.role_table_grants WHERE grantee='call_analyzer';"
```

7. **Если ничего не помогло, пересоздайте базу данных:**
```bash
# ВНИМАНИЕ: Это удалит все данные!
sudo -u postgres psql <<EOF
DROP DATABASE IF EXISTS call_analyzer;
DROP USER IF EXISTS call_analyzer;
CREATE DATABASE call_analyzer;
CREATE USER call_analyzer WITH PASSWORD 'новый_пароль';
ALTER ROLE call_analyzer SET client_encoding TO 'utf8';
ALTER ROLE call_analyzer SET default_transaction_isolation TO 'read committed';
ALTER ROLE call_analyzer SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE call_analyzer TO call_analyzer;
\c call_analyzer
GRANT ALL ON SCHEMA public TO call_analyzer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO call_analyzer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO call_analyzer;
\q
EOF

# Обновите .env с новым паролем
nano /opt/call-analyzer/.env
```

### 12.3 Веб-интерфейс недоступен

**Проблема:** Страница не открывается в браузере.

**Решение:**

1. Проверьте статус веб-сервиса:
```bash
sudo systemctl status call-analyzer-web
```

2. Проверьте, слушает ли приложение порт 5000:
```bash
sudo netstat -tlnp | grep 5000
# или
sudo ss -tlnp | grep 5000
```

3. Проверьте статус Nginx:
```bash
sudo systemctl status nginx
```

4. Проверьте логи Nginx:
```bash
sudo tail -f /var/log/nginx/call-analyzer-error.log
```

5. Проверьте конфигурацию Nginx:
```bash
sudo nginx -t
```

6. Проверьте firewall:
```bash
sudo ufw status
```

### 12.4 Ошибки при установке зависимостей

**Проблема:** Ошибки при `pip install`.

**Решение:**

1. Обновите pip:
```bash
pip install --upgrade pip
```

2. Установите системные зависимости:
```bash
sudo apt install -y python3-dev libpq-dev build-essential
```

3. Попробуйте установить зависимости по одной:
```bash
pip install Flask==3.0.0
pip install psycopg2-binary
# и т.д.
```

### 12.5 Проблемы с правами доступа

**Проблема:** Ошибки доступа к файлам или директориям.

**Решение:**

```bash
# Установите правильные права
sudo chown -R callanalyzer:callanalyzer /opt/call-analyzer
sudo chown -R callanalyzer:callanalyzer /var/calls
sudo chown -R callanalyzer:callanalyzer /var/log/call-analyzer

# Установите права на .env
sudo chmod 600 /opt/call-analyzer/.env
sudo chown callanalyzer:callanalyzer /opt/call-analyzer/.env
```

---

## Дополнительные настройки

### Настройка автоматических бэкапов

Создайте скрипт для бэкапа базы данных:

```bash
sudo nano /opt/call-analyzer/backup_db.sh
```

Содержимое:

```bash
#!/bin/bash
BACKUP_DIR="/opt/call-analyzer/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
sudo -u postgres pg_dump call_analyzer > $BACKUP_DIR/backup_$DATE.sql
# Удаляем бэкапы старше 7 дней
find $BACKUP_DIR -name "backup_*.sql" -mtime +7 -delete
```

Сделайте скрипт исполняемым:

```bash
sudo chmod +x /opt/call-analyzer/backup_db.sh
```

Добавьте в crontab:

```bash
sudo crontab -e
```

Добавьте строку (бэкап каждый день в 2:00):

```
0 2 * * * /opt/call-analyzer/backup_db.sh
```

### Мониторинг ресурсов

Установите утилиты для мониторинга:

```bash
sudo apt install -y htop iotop
```

---

## Контакты и поддержка

При возникновении проблем:

1. Проверьте логи всех сервисов
2. Проверьте статус всех сервисов
3. Убедитесь, что все переменные окружения настроены правильно
4. Проверьте права доступа к файлам и директориям

---

## Быстрая справка команд

**Для двух сервисов:**
```bash
# Статус всех сервисов
sudo systemctl status call-analyzer-service call-analyzer-web nginx postgresql

# Перезапуск всех сервисов
sudo systemctl restart call-analyzer-service call-analyzer-web nginx

# Просмотр логов
sudo journalctl -u call-analyzer-web -f
tail -f /var/log/call-analyzer/*.log

# Проверка портов
sudo netstat -tlnp | grep -E '5000|80|5432'

# Проверка подключения к БД
sudo -u postgres psql -d call_analyzer -U call_analyzer
```

**Для единого сервиса:**
```bash
# Статус всех сервисов
sudo systemctl status call-analyzer nginx postgresql

# Перезапуск всех сервисов
sudo systemctl restart call-analyzer nginx

# Просмотр логов
sudo journalctl -u call-analyzer -f
tail -f /var/log/call-analyzer/*.log

# Проверка портов
sudo netstat -tlnp | grep -E '5000|80|5432'

# Проверка подключения к БД
sudo -u postgres psql -d call_analyzer -U call_analyzer
```

---

**Успешного развертывания!**

