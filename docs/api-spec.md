# API Specification — Estimation Engine

## Базовый URL

```
http://localhost:8000
```

## Аутентификация

Аутентификация не требуется. Для идемпотентности используется заголовок `Idempotency-Key`.

---

## Эндпоинты

### 1. POST /v1/calculations — Создать задачу расчёта

Принимает спецификацию и создаёт задачу расчёта в очереди. Возвращает идентификатор задачи немедленно (HTTP 202), расчёт выполняется асинхронно.

**Метод:** `POST`
**URL:** `/v1/calculations`
**Content-Type:** `application/json`

**Заголовки (опциональные):**

| Заголовок        | Тип    | Описание                                           |
|------------------|--------|----------------------------------------------------|
| Idempotency-Key  | string | Уникальный ключ для предотвращения дублей запросов |

**Request body:**

```json
{
  "project_id": "proj-123",
  "region": {
    "country_code": "RU",
    "region_code": "RU-MOW",
    "city": "Moscow"
  },
  "currency": "RUB",
  "items": [
    {
      "id": "item-1",
      "kind": "material",
      "code": "aerated_concrete_block_300_d500",
      "name": "Газобетонный блок D500 300мм",
      "quantity": 9,
      "unit": "m3",
      "category": "masonry"
    },
    {
      "id": "item-2",
      "kind": "work",
      "code": "block_masonry",
      "name": "Кладка газобетонных блоков",
      "quantity": 30,
      "unit": "m2",
      "category": "masonry"
    }
  ],
  "request_meta": {}
}
```

**Поля items:**

| Поле     | Тип                  | Обязательное | Описание                     |
|----------|----------------------|--------------|------------------------------|
| id       | string               | да           | Уникальный ID строки          |
| kind     | "material" \| "work" | да           | Тип позиции                  |
| code     | string               | да           | Артикул / код позиции        |
| name     | string               | да           | Наименование                 |
| quantity | float (>0)           | да           | Количество                   |
| unit     | string               | да           | Единица измерения (canonical)|
| category | string               | да           | Категория для fallback       |
| metadata | object               | нет          | Произвольные метаданные      |

**Коды ответа:**

| Код | Описание                                      |
|-----|-----------------------------------------------|
| 202 | Задача создана и поставлена в очередь         |
| 400 | Ошибка валидации (неверная единица, валюта)   |
| 409 | Idempotency-Key уже существует (возвращает существующую задачу) |
| 413 | Превышен допустимый размер payload            |
| 422 | Ошибка валидации Pydantic                     |

**Пример ответа (202):**

```json
{
  "calculation_id": "01HXYZ1234567890ABCDEFGHIJ",
  "status": "queued",
  "progress_percent": 0,
  "processed_items": 0,
  "total_items": 2,
  "current_step": null,
  "requested_at": "2024-01-15T12:00:00Z"
}
```

---

### 2. GET /v1/calculations/{id} — Получить результат расчёта

Возвращает полный результат расчёта (если завершён) или текущий прогресс.

**Метод:** `GET`
**URL:** `/v1/calculations/{calculation_id}`

**Path параметры:**

| Параметр       | Тип    | Описание             |
|----------------|--------|----------------------|
| calculation_id | string | ULID идентификатор   |

**Коды ответа:**

| Код | Описание                    |
|-----|-----------------------------|
| 200 | Успешно                     |
| 404 | Задача не найдена           |

**Пример ответа (200, статус completed):**

```json
{
  "calculation_id": "01HXYZ1234567890ABCDEFGHIJ",
  "status": "completed",
  "progress_percent": 100,
  "current_step": null,
  "error_code": null,
  "error_message": null,
  "requested_at": "2024-01-15T12:00:00Z",
  "started_at": "2024-01-15T12:00:01Z",
  "completed_at": "2024-01-15T12:00:03Z",
  "cancelled_at": null,
  "failed_at": null,
  "summary": {
    "total": "1350000.00",
    "currency": "RUB",
    "priced_count": 2,
    "unpriced_count": 0,
    "high_confidence_count": 1,
    "medium_confidence_count": 1,
    "low_confidence_count": 0
  },
  "items": [
    {
      "id": "item-1",
      "code": "aerated_concrete_block_300_d500",
      "name": "Газобетонный блок D500 300мм",
      "quantity": 9,
      "unit": "m3",
      "unit_price": "125000.00",
      "line_total": "1125000.00",
      "currency": "RUB",
      "pricing_method": "exact_match",
      "confidence": "high",
      "match_path": "RU/RU-MOW/m3",
      "fallback_reason": null,
      "unit_converted": false,
      "original_unit": null
    }
  ],
  "assumptions": [],
  "diagnostics": {}
}
```

**Пример ответа (200, статус running):**

```json
{
  "calculation_id": "01HXYZ1234567890ABCDEFGHIJ",
  "status": "running",
  "progress_percent": 50,
  "current_step": "pricing",
  "error_code": null,
  "error_message": null,
  "requested_at": "2024-01-15T12:00:00Z",
  "started_at": "2024-01-15T12:00:01Z",
  "completed_at": null,
  "cancelled_at": null,
  "failed_at": null,
  "summary": null,
  "items": null
}
```

---

### 3. GET /v1/calculations/{id}/status — Lightweight статус

Лёгкий эндпоинт для polling. Возвращает только статус и прогресс без полных данных.

**Метод:** `GET`
**URL:** `/v1/calculations/{calculation_id}/status`

**Коды ответа:**

| Код | Описание          |
|-----|-------------------|
| 200 | Успешно           |
| 404 | Задача не найдена |

**Пример ответа (200):**

```json
{
  "calculation_id": "01HXYZ1234567890ABCDEFGHIJ",
  "status": "running",
  "progress_percent": 75,
  "current_step": "pricing",
  "error_code": null
}
```

**Возможные значения `status`:**

| Значение  | Описание                              |
|-----------|---------------------------------------|
| queued    | Задача в очереди, ожидает воркера     |
| running   | Выполняется воркером                  |
| completed | Расчёт завершён успешно              |
| failed    | Расчёт завершён с ошибкой            |
| cancelled | Задача отменена                       |

---

### 4. POST /v1/calculations/{id}/cancel — Отменить задачу

Запрашивает отмену задачи. Поведение зависит от текущего статуса:
- `queued` → отмена немедленная, статус сразу `cancelled`
- `running` → устанавливается флаг `cancel_requested`, воркер завершит текущий шаг и остановится

**Метод:** `POST`
**URL:** `/v1/calculations/{calculation_id}/cancel`

**Коды ответа:**

| Код | Описание                                             |
|-----|------------------------------------------------------|
| 200 | Запрос на отмену принят                              |
| 404 | Задача не найдена                                    |
| 409 | Нельзя отменить задачу в статусе completed/failed/cancelled |

**Пример ответа (200):**

```json
{
  "calculation_id": "01HXYZ1234567890ABCDEFGHIJ",
  "status": "cancelled",
  "progress_percent": 0,
  "requested_at": "2024-01-15T12:00:00Z",
  "cancelled_at": "2024-01-15T12:00:05Z"
}
```

---

## Экспорт OpenAPI JSON

Для получения машиночитаемой спецификации запустите сервис и выполните:

```bash
curl http://localhost:8000/openapi.json -o docs/openapi.json
```

Или используйте скрипт `scripts/export_openapi.py`:

```python
# scripts/export_openapi.py
import json
from src.api.app import create_app

app = create_app()
schema = app.openapi()
with open("docs/openapi.json", "w", encoding="utf-8") as f:
    json.dump(schema, f, ensure_ascii=False, indent=2)
print("OpenAPI schema written to docs/openapi.json")
```

Swagger UI доступен по адресу: `http://localhost:8000/docs`
ReDoc доступен по адресу: `http://localhost:8000/redoc`
