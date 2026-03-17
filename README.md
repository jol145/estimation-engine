# Estimation Engine

Микросервис расчёта стоимости строительных спецификаций.

## Что делает

- Принимает спецификацию материалов и работ с указанием региона
- Асинхронно рассчитывает стоимость каждой позиции
- Находит среднюю рыночную цену по региону (6-уровневый pricing pipeline)
- Возвращает детальный результат с диагностикой по каждой строке

## API

- POST /v1/calculations — запуск расчёта
- GET /v1/calculations/{id} — получение результата
- GET /v1/calculations/{id}/status — статус расчёта
- POST /v1/calculations/{id}/cancel — отмена расчёта

## Запуск

docker-compose up --build

API доступен на http://localhost:8000/docs

## Стек

Python, FastAPI, PostgreSQL, Redis, Celery, SQLAlchemy, Alembic, Docker