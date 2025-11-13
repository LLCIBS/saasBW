# API документация Call Analyzer Web Interface

## Обзор

Веб-интерфейс Call Analyzer предоставляет REST API для управления конфигурацией и мониторинга системы.

## Базовый URL

```
http://localhost:5000
```

## Аутентификация

В текущей версии аутентификация не реализована. Все эндпоинты доступны без авторизации.

## Эндпоинты

### Конфигурация

#### GET /api/config
Получить текущую конфигурацию системы.

**Ответ:**
```json
{
  "speechmatics_api_key": "***",
  "thebai_api_key": "***",
  "telegram_bot_token": "***",
  "base_records_path": "E:/CallRecords",
  "prompts_file": "prompts.yaml",
  "additional_vocab_file": "additional_vocab.yaml"
}
```

#### POST /api/config
Обновить конфигурацию системы.

**Тело запроса:**
```json
{
  "speechmatics_api_key": "new_key",
  "thebai_api_key": "new_key",
  "telegram_bot_token": "new_token",
  "base_records_path": "E:/CallRecords",
  "prompts_file": "prompts.yaml",
  "additional_vocab_file": "additional_vocab.yaml"
}
```

**Ответ:**
```json
{
  "success": true,
  "message": "Конфигурация обновлена"
}
```

### Станции

#### GET /api/stations
Получить список всех станций.

**Ответ:**
```json
{
  "stations": [
    {
      "code": "NN01",
      "name": "Нижний Новгород - Центр",
      "chat_id": "-1001234567890",
      "channel": "nizhniy",
      "keywords": ["центр", "нижний новгород"]
    }
  ]
}
```

#### POST /api/stations
Добавить новую станцию.

**Тело запроса:**
```json
{
  "code": "NN02",
  "name": "Нижний Новгород - Сормово",
  "chat_id": "-1001234567891",
  "channel": "nizhniy",
  "keywords": ["сормово", "нижний новгород"]
}
```

#### PUT /api/stations/<station_code>
Обновить существующую станцию.

#### DELETE /api/stations/<station_code>
Удалить станцию.

### Промпты

#### GET /api/prompts
Получить все промпты.

**Ответ:**
```json
{
  "prompts": {
    "nizhniy": "Промпт для станции Нижний Новгород",
    "s_perevodom": "Промпт для станций с переводами",
    "bez_perevoda": "Промпт для станций без переводов",
    "default": "Промпт по умолчанию"
  }
}
```

#### POST /api/prompts
Обновить промпты.

**Тело запроса:**
```json
{
  "prompts": {
    "nizhniy": "Новый промпт для Нижнего Новгорода",
    "default": "Новый промпт по умолчанию"
  }
}
```

### Словари

#### GET /api/vocabulary
Получить дополнительную лексику.

**Ответ:**
```json
{
  "additional_vocab": [
    "специальный термин 1",
    "специальный термин 2",
    "название компании"
  ],
  "legal_entity_keywords": [
    "ооо",
    "ип",
    "компания",
    "организация"
  ]
}
```

#### POST /api/vocabulary
Обновить словари.

**Тело запроса:**
```json
{
  "additional_vocab": [
    "новый термин 1",
    "новый термин 2"
  ],
  "legal_entity_keywords": [
    "ооо",
    "ип",
    "компания"
  ]
}
```

### Отчеты

#### GET /api/reports
Получить список отчетов.

**Ответ:**
```json
{
  "reports": [
    {
      "id": "weekly_2024_01_15",
      "type": "weekly",
      "date": "2024-01-15",
      "status": "completed",
      "file_path": "reports/weekly_2024_01_15.xlsx"
    }
  ]
}
```

#### POST /api/reports/generate
Сгенерировать новый отчет.

**Тело запроса:**
```json
{
  "type": "weekly",
  "date": "2024-01-15",
  "stations": ["NN01", "NN02"]
}
```

#### GET /api/reports/<report_id>/download
Скачать отчет.

### Переводы

#### GET /api/transfers
Получить активные переводы.

**Ответ:**
```json
{
  "transfers": [
    {
      "id": "transfer_001",
      "client_phone": "+79001234567",
      "from_station": "NN01",
      "to_station": "NN02",
      "created_at": "2024-01-15T10:00:00",
      "deadline": "2024-01-15T18:00:00",
      "status": "pending"
    }
  ]
}
```

#### POST /api/transfers
Добавить новый перевод.

#### PUT /api/transfers/<transfer_id>
Обновить перевод.

#### DELETE /api/transfers/<transfer_id>
Удалить перевод.

### Отзывы

#### GET /api/recalls
Получить активные отзывы.

**Ответ:**
```json
{
  "recalls": [
    {
      "id": "recall_001",
      "client_phone": "+79001234567",
      "station": "NN01",
      "created_at": "2024-01-15T10:00:00",
      "deadline": "2024-01-15T18:00:00",
      "status": "pending"
    }
  ]
}
```

#### POST /api/recalls
Добавить новый отзыв.

#### PUT /api/recalls/<recall_id>
Обновить отзыв.

#### DELETE /api/recalls/<recall_id>
Удалить отзыв.

### Логи

#### GET /api/logs
Получить логи системы.

**Параметры запроса:**
- `level` - уровень лога (debug, info, warning, error)
- `limit` - количество записей (по умолчанию 100)
- `offset` - смещение для пагинации

**Ответ:**
```json
{
  "logs": [
    {
      "timestamp": "2024-01-15T10:00:00",
      "level": "INFO",
      "message": "Обработка нового звонка",
      "module": "call_handler"
    }
  ],
  "total": 1000,
  "offset": 0,
  "limit": 100
}
```

### Система

#### GET /api/status
Получить статус системы.

**Ответ:**
```json
{
  "status": "running",
  "uptime": "2 days, 5 hours",
  "last_call_processed": "2024-01-15T09:45:00",
  "total_calls_processed": 1250,
  "active_transfers": 5,
  "active_recalls": 3
}
```

#### POST /api/system/restart
Перезапустить систему.

#### POST /api/system/stop
Остановить систему.

#### POST /api/system/start
Запустить систему.

## Коды ошибок

### HTTP статус коды
- `200` - Успешный запрос
- `400` - Неверный запрос
- `404` - Ресурс не найден
- `500` - Внутренняя ошибка сервера

### Формат ошибок
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Неверные данные в запросе",
    "details": {
      "field": "station_code",
      "reason": "Код станции уже существует"
    }
  }
}
```

## Примеры использования

### Получение конфигурации
```bash
curl -X GET http://localhost:5000/api/config
```

### Обновление конфигурации
```bash
curl -X POST http://localhost:5000/api/config \
  -H "Content-Type: application/json" \
  -d '{"speechmatics_api_key": "new_key"}'
```

### Добавление станции
```bash
curl -X POST http://localhost:5000/api/stations \
  -H "Content-Type: application/json" \
  -d '{
    "code": "NN03",
    "name": "Нижний Новгород - Автозавод",
    "chat_id": "-1001234567892",
    "channel": "nizhniy",
    "keywords": ["автозавод", "нижний новгород"]
  }'
```

### Генерация отчета
```bash
curl -X POST http://localhost:5000/api/reports/generate \
  -H "Content-Type: application/json" \
  -d '{
    "type": "weekly",
    "date": "2024-01-15",
    "stations": ["NN01", "NN02"]
  }'
```

## Ограничения

- Максимальный размер запроса: 10MB
- Максимальное количество станций: 100
- Максимальная длина промпта: 10000 символов
- Максимальное количество записей в логах за запрос: 1000

## Версионирование

Текущая версия API: `v1`

Для будущих версий будет использоваться префикс версии в URL:
```
http://localhost:5000/api/v2/config
```


