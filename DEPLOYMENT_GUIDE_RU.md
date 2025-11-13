# Руководство по деплою Call Analyzer на Ubuntu сервер

Это руководство описывает процесс развертывания Call Analyzer на Ubuntu сервере для продакшн-использования.

## Требования

- Ubuntu 20.04 или новее
- Минимум 2GB RAM
- Минимум 10GB свободного места на диске
- Доступ с правами root (sudo)

## Шаг 1: Первоначальная настройка сервера

### 1.1 Подключитесь к серверу

```bash
ssh user@your-server-ip
```

### 1.2 Запустите скрипт настройки

```bash
cd /path/to/project
sudo bash deploy/setup_ubuntu.sh
```

Скрипт установит:
- Python 3 и необходимые пакеты
- PostgreSQL
- Nginx
- Supervisor
- Создаст пользователя и директории

**⚠ ВАЖНО:** После установки измените пароль базы данных PostgreSQL!

## Шаг 2: Копирование проекта на сервер

### 2.1 Скопируйте проект на сервер

```bash
# На вашем локальном компьютере
scp -r /path/to/saasBW user@server:/opt/call-analyzer
```

Или используйте git:

```bash
# На сервере
cd /opt
git clone your-repository-url call-analyzer
chown -R callanalyzer:callanalyzer /opt/call-analyzer
```

## Шаг 3: Настройка переменных окружения

### 3.1 Создайте файл .env

```bash
cd /opt/call-analyzer
cp .env.example .env
nano .env
```

### 3.2 Заполните необходимые значения

Обязательно измените:
- `SECRET_KEY` - сгенерируйте случайную строку
- `DATABASE_URL` - пароль базы данных
- Все API ключи
- Пароль администратора

## Шаг 4: Установка systemd сервисов

### 4.1 Скопируйте файлы сервисов

```bash
sudo cp deploy/systemd/call-analyzer-service.service /etc/systemd/system/
sudo cp deploy/systemd/call-analyzer-web.service /etc/systemd/system/
```

### 4.2 Перезагрузите systemd

```bash
sudo systemctl daemon-reload
```

### 4.3 Включите автозапуск

```bash
sudo systemctl enable call-analyzer-service
sudo systemctl enable call-analyzer-web
```

## Шаг 5: Деплой приложения

### 5.1 Запустите скрипт деплоя

```bash
cd /opt/call-analyzer
sudo -u callanalyzer bash deploy/deploy.sh
```

Скрипт:
- Создаст виртуальное окружение
- Установит зависимости
- Инициализирует базу данных
- Мигрирует данные из JSON (если есть)

### 5.2 Запустите сервисы

```bash
sudo systemctl start call-analyzer-service
sudo systemctl start call-analyzer-web
```

### 5.3 Проверьте статус

```bash
sudo systemctl status call-analyzer-service
sudo systemctl status call-analyzer-web
```

## Шаг 6: Настройка Nginx

### 6.1 Скопируйте конфигурацию

```bash
sudo cp deploy/nginx/call-analyzer.conf /etc/nginx/sites-available/call-analyzer
```

### 6.2 Отредактируйте конфигурацию

```bash
sudo nano /etc/nginx/sites-available/call-analyzer
```

Измените `server_name` на ваш домен или IP.

### 6.3 Включите сайт

```bash
sudo ln -s /etc/nginx/sites-available/call-analyzer /etc/nginx/sites-enabled/
sudo nginx -t  # Проверка конфигурации
sudo systemctl restart nginx
```

## Шаг 7: Настройка SSL (опционально, но рекомендуется)

### 7.1 Установите Certbot

```bash
sudo apt-get install certbot python3-certbot-nginx
```

### 7.2 Получите сертификат

```bash
sudo certbot --nginx -d your-domain.com
```

### 7.3 Обновите .env

Установите в `.env`:
```
SESSION_COOKIE_SECURE=True
REMEMBER_COOKIE_SECURE=True
```

## Шаг 8: Первый вход

1. Откройте браузер и перейдите на `http://your-server-ip` или `https://your-domain.com`
2. Войдите с учетными данными администратора из `.env`
3. **Сразу смените пароль администратора!**

## Управление сервисами

### Просмотр логов

```bash
# Логи сервиса
sudo journalctl -u call-analyzer-service -f

# Логи веб-интерфейса
sudo journalctl -u call-analyzer-web -f

# Логи приложения
tail -f /var/log/call-analyzer/*.log
```

### Перезапуск сервисов

```bash
sudo systemctl restart call-analyzer-service
sudo systemctl restart call-analyzer-web
sudo systemctl restart nginx
```

### Остановка сервисов

```bash
sudo systemctl stop call-analyzer-service
sudo systemctl stop call-analyzer-web
```

## Обновление приложения

```bash
cd /opt/call-analyzer
sudo -u callanalyzer git pull  # Если используете git
sudo -u callanalyzer bash deploy/deploy.sh
sudo systemctl restart call-analyzer-service
sudo systemctl restart call-analyzer-web
```

## Резервное копирование

### База данных

```bash
# Создать бэкап
sudo -u postgres pg_dump call_analyzer > backup_$(date +%Y%m%d).sql

# Восстановить из бэкапа
sudo -u postgres psql call_analyzer < backup_20250101.sql
```

### Файлы конфигурации

```bash
# Бэкап конфигурации
tar -czf config_backup_$(date +%Y%m%d).tar.gz \
    /opt/call-analyzer/.env \
    /opt/call-analyzer/prompts.yaml \
    /opt/call-analyzer/additional_vocab.yaml
```

## Устранение неполадок

### Сервис не запускается

1. Проверьте логи: `sudo journalctl -u call-analyzer-service -n 50`
2. Проверьте .env файл: `cat /opt/call-analyzer/.env`
3. Проверьте права доступа: `ls -la /opt/call-analyzer`

### База данных не подключается

1. Проверьте статус PostgreSQL: `sudo systemctl status postgresql`
2. Проверьте подключение: `sudo -u postgres psql -d call_analyzer -U call_analyzer`
3. Проверьте DATABASE_URL в .env

### Веб-интерфейс недоступен

1. Проверьте статус веб-сервиса: `sudo systemctl status call-analyzer-web`
2. Проверьте Nginx: `sudo systemctl status nginx`
3. Проверьте логи Nginx: `sudo tail -f /var/log/nginx/error.log`

## Безопасность

1. **Всегда используйте HTTPS в продакшн**
2. **Измените все пароли по умолчанию**
3. **Ограничьте доступ к серверу через firewall**
4. **Регулярно обновляйте систему и зависимости**
5. **Настройте автоматические бэкапы базы данных**

## Поддержка

При возникновении проблем проверьте:
- Логи сервисов
- Логи приложения в `/var/log/call-analyzer/`
- Логи Nginx
- Статус всех сервисов

