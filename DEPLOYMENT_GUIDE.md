# Руководство по развертыванию Call Analyzer

## Подготовка к развертыванию

### Системные требования

**Минимальные требования:**
- Windows 10/11 или Windows Server 2016+
- Python 3.8+
- 4 GB RAM
- 10 GB свободного места на диске
- Стабильное интернет-соединение

**Рекомендуемые требования:**
- Windows Server 2019/2022
- Python 3.10+
- 8 GB RAM
- 50 GB свободного места на диске
- Выделенный сервер или виртуальная машина

### Установка Python

1. Скачайте Python с официального сайта: https://www.python.org/downloads/
2. Установите Python с опцией "Add Python to PATH"
3. Проверьте установку:
   ```bash
   python --version
   pip --version
   ```

## Установка системы

### 1. Клонирование проекта

```bash
git clone <repository_url> CallAnalyzer
cd CallAnalyzer
```

### 2. Создание виртуального окружения

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Установка зависимостей

```bash
# Основные зависимости
pip install -r web_interface/requirements.txt

# Дополнительные зависимости для основной системы
pip install watchdog APScheduler tenacity
```

### 4. Настройка конфигурации

1. Скопируйте файл конфигурации:
   ```bash
   copy config.txt.example config.txt
   ```

2. Отредактируйте `config.txt` с вашими настройками

3. Настройте API ключи через веб-интерфейс

## Настройка Windows Service

### Автоматический запуск

1. Создайте файл `install_service.bat`:
   ```batch
   @echo off
   echo Установка Call Analyzer как Windows Service...
   
   REM Установка NSSM (Non-Sucking Service Manager)
   if not exist "nssm.exe" (
       echo Скачивание NSSM...
       powershell -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile 'nssm.zip'"
       powershell -Command "Expand-Archive -Path 'nssm.zip' -DestinationPath '.'"
       copy "nssm-2.24\win64\nssm.exe" .
   )
   
   REM Установка сервиса
   nssm install CallAnalyzer "%~dp0venv\Scripts\python.exe" "%~dp0call_analyzer\main.py"
   nssm set CallAnalyzer AppDirectory "%~dp0"
   nssm set CallAnalyzer DisplayName "Call Analyzer Service"
   nssm set CallAnalyzer Description "Автоматический анализ телефонных звонков"
   
   echo Сервис установлен. Запуск...
   nssm start CallAnalyzer
   
   pause
   ```

2. Запустите установку:
   ```bash
   install_service.bat
   ```

### Ручная настройка сервиса

1. Скачайте NSSM: https://nssm.cc/download
2. Распакуйте в папку проекта
3. Установите сервис:
   ```bash
   nssm install CallAnalyzer "E:\CallRecords\monv2_безRerTruck web\venv\Scripts\python.exe" "E:\CallRecords\monv2_безRerTruck web\call_analyzer\main.py"
   ```

## Настройка веб-интерфейса

### Развертывание на IIS

1. Установите IIS и модуль CGI
2. Создайте новое приложение в IIS
3. Настройте обработчик для Python:
   ```xml
   <handlers>
     <add name="PythonHandler" path="*.py" verb="*" modules="CgiModule" scriptProcessor="E:\CallRecords\monv2_безRerTruck web\venv\Scripts\python.exe" resourceType="File" />
   </handlers>
   ```

### Развертывание с Gunicorn (альтернатива)

1. Установите Gunicorn:
   ```bash
   pip install gunicorn
   ```

2. Создайте файл `gunicorn.conf.py`:
   ```python
   bind = "0.0.0.0:5000"
   workers = 4
   worker_class = "sync"
   worker_connections = 1000
   timeout = 30
   keepalive = 2
   max_requests = 1000
   max_requests_jitter = 100
   ```

3. Запустите с Gunicorn:
   ```bash
   gunicorn -c gunicorn.conf.py web_interface.app:app
   ```

## Настройка безопасности

### Firewall

1. Откройте порт 5000 для веб-интерфейса:
   ```bash
   netsh advfirewall firewall add rule name="Call Analyzer Web" dir=in action=allow protocol=TCP localport=5000
   ```

2. Ограничьте доступ по IP (если нужно):
   ```bash
   netsh advfirewall firewall add rule name="Call Analyzer Web Restricted" dir=in action=allow protocol=TCP localport=5000 remoteip=192.168.1.0/24
   ```

### SSL сертификат

1. Получите SSL сертификат (Let's Encrypt или коммерческий)
2. Настройте HTTPS в веб-интерфейсе:
   ```python
   if __name__ == '__main__':
       app.run(host='0.0.0.0', port=5000, ssl_context=('cert.pem', 'key.pem'))
   ```

### Аутентификация

1. Установите Flask-Login:
   ```bash
   pip install Flask-Login
   ```

2. Настройте аутентификацию в `web_interface/app.py`

## Мониторинг и логирование

### Настройка логирования

1. Создайте папку для логов:
   ```bash
   mkdir logs
   ```

2. Настройте ротацию логов в `config.py`:
   ```python
   LOGGING_CONFIG = {
       'version': 1,
       'disable_existing_loggers': False,
       'formatters': {
           'standard': {
               'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
           },
       },
       'handlers': {
           'default': {
               'level': 'INFO',
               'formatter': 'standard',
               'class': 'logging.handlers.RotatingFileHandler',
               'filename': 'logs/call_analyzer.log',
               'maxBytes': 10485760,  # 10MB
               'backupCount': 5,
           },
       },
       'loggers': {
           '': {
               'handlers': ['default'],
               'level': 'INFO',
               'propagate': False
           }
       }
   }
   ```

### Мониторинг системы

1. Создайте скрипт мониторинга `monitor.bat`:
   ```batch
   @echo off
   echo Проверка статуса Call Analyzer...
   
   REM Проверка основного сервиса
   sc query CallAnalyzer | find "RUNNING" >nul
   if errorlevel 1 (
       echo ОШИБКА: Основной сервис не запущен!
       nssm start CallAnalyzer
   ) else (
       echo Основной сервис работает
   )
   
   REM Проверка веб-интерфейса
   curl -s http://localhost:5000/api/status >nul
   if errorlevel 1 (
       echo ОШИБКА: Веб-интерфейс недоступен!
       start_web_interface.bat
   ) else (
       echo Веб-интерфейс работает
   )
   
   echo Проверка завершена
   ```

2. Настройте задачу в планировщике Windows для запуска каждые 5 минут

## Резервное копирование

### Автоматическое резервное копирование

1. Создайте скрипт `backup.bat`:
   ```batch
   @echo off
   set BACKUP_DIR=E:\Backups\CallAnalyzer
   set DATE=%date:~-4,4%%date:~-10,2%%date:~-7,2%
   
   mkdir "%BACKUP_DIR%\%DATE%" 2>nul
   
   REM Копирование конфигурации
   copy config.txt "%BACKUP_DIR%\%DATE%\"
   copy *.yaml "%BACKUP_DIR%\%DATE%\"
   copy *.json "%BACKUP_DIR%\%DATE%\"
   
   REM Копирование логов
   xcopy logs "%BACKUP_DIR%\%DATE%\logs\" /E /I
   
   REM Копирование отчетов
   xcopy reports "%BACKUP_DIR%\%DATE%\reports\" /E /I
   
   echo Резервное копирование завершено: %BACKUP_DIR%\%DATE%
   ```

2. Настройте задачу в планировщике Windows для ежедневного резервного копирования

## Обновление системы

### Процедура обновления

1. Остановите сервисы:
   ```bash
   stop_service.bat
   stop_web_interface.bat
   ```

2. Создайте резервную копию:
   ```bash
   backup.bat
   ```

3. Обновите код:
   ```bash
   git pull origin main
   ```

4. Обновите зависимости:
   ```bash
   pip install -r web_interface/requirements.txt --upgrade
   ```

5. Запустите сервисы:
   ```bash
   start_service.bat
   start_web_interface.bat
   ```

6. Проверьте работу системы

## Устранение неполадок

### Частые проблемы

1. **Сервис не запускается:**
   - Проверьте логи в Event Viewer
   - Убедитесь что Python установлен правильно
   - Проверьте пути в конфигурации

2. **Веб-интерфейс недоступен:**
   - Проверьте что порт 5000 свободен
   - Убедитесь что firewall не блокирует соединения
   - Проверьте логи веб-интерфейса

3. **Ошибки API:**
   - Проверьте правильность API ключей
   - Убедитесь что интернет-соединение стабильно
   - Проверьте квоты API

### Логи для диагностики

- **Основная система:** `logs/call_analyzer.log`
- **Веб-интерфейс:** `logs/web_interface.log`
- **Windows Service:** Event Viewer → Windows Logs → Application
- **IIS (если используется):** `C:\inetpub\logs\LogFiles\`

## Производительность

### Оптимизация

1. **Настройка количества воркеров:**
   ```python
   # В gunicorn.conf.py
   workers = min(4, (os.cpu_count() * 2) + 1)
   ```

2. **Кэширование:**
   ```python
   # Установка Redis для кэширования
   pip install redis Flask-Caching
   ```

3. **Оптимизация базы данных:**
   - Использование индексов
   - Регулярная очистка старых данных
   - Архивация логов

### Масштабирование

1. **Горизонтальное масштабирование:**
   - Разделение по станциям
   - Балансировка нагрузки
   - Микросервисная архитектура

2. **Вертикальное масштабирование:**
   - Увеличение RAM
   - Использование SSD
   - Оптимизация Python кода


