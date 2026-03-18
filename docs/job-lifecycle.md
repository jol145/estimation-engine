# Жизненный цикл задачи расчёта

## Статусы задачи

| Статус    | Описание                                              |
|-----------|-------------------------------------------------------|
| queued    | Задача создана и ожидает захвата воркером             |
| running   | Захвачена воркером, выполняется расчёт               |
| completed | Расчёт завершён, результат сохранён в БД             |
| failed    | Расчёт завершился с ошибкой (с кодом и сообщением)  |
| cancelled | Задача отменена клиентом или системой                 |

## Диаграмма переходов статусов

```
                       ┌─────────┐
         POST /v1/     │         │
         calculations  │ queued  │
         ──────────►   │         │
                       └────┬────┘
                            │ воркер захватывает задачу
                            │ (SELECT FOR UPDATE SKIP LOCKED)
                            ▼
                       ┌─────────┐
                       │         │◄──────────────────┐
                       │ running │                   │ stale recovery
                       │         │──────────────────►│ (heartbeat timeout)
                       └────┬────┘
                            │
               ┌────────────┼────────────┐
               │            │            │
               ▼            ▼            ▼
          ┌─────────┐  ┌────────┐  ┌──────────┐
          │completed│  │ failed │  │cancelled │
          └─────────┘  └────────┘  └──────────┘

  queued ──► cancelled  (немедленно, через POST /{id}/cancel)
```

---

## Locking механизм

Воркеры конкурентно борются за задачи через атомарный SQL-запрос:

```sql
SELECT * FROM calculation_jobs
WHERE status = 'queued'
  AND expires_at > NOW()
ORDER BY requested_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

- `FOR UPDATE` — блокирует строку на время транзакции
- `SKIP LOCKED` — другие воркеры не ждут, а пропускают заблокированные строки
- Это гарантирует, что каждую задачу возьмёт ровно один воркер
- После захвата статус обновляется до `running` в той же транзакции

---

## Heartbeat механизм

Во время расчёта воркер периодически обновляет поле `heartbeat_at`:

```
воркер           БД
  │               │
  │──── heartbeat_at = NOW() ────►│  (после каждого шага pipeline)
  │               │
  │──── heartbeat_at = NOW() ────►│  (после следующего шага)
  │               │
```

- Обновление происходит после каждого шага pricing pipeline (по одной позиции)
- Если воркер падает — `heartbeat_at` перестаёт обновляться

---

## Stale Job Recovery

Celery Beat каждые **60 секунд** запускает задачу `recover_stale_jobs`:

1. Находит все задачи в статусе `running`, у которых `heartbeat_at < NOW() - stale_threshold`
2. Сбрасывает их статус обратно в `queued` для повторного захвата

```
Celery Beat
    │
    │ каждые 60 сек
    ▼
recover_stale_jobs
    │
    │ UPDATE calculation_jobs
    │ SET status = 'queued'
    │ WHERE status = 'running'
    │   AND heartbeat_at < NOW() - interval '5 minutes'
    ▼
  Задача снова доступна для воркеров
```

Порог устарения (`stale_threshold`) настраивается через `settings.stale_job_threshold_seconds` (по умолчанию 300 секунд).

---

## Retry Policy

- Максимальное количество повторных попыток: **2** (итого до 3 попыток)
- Повторная попытка инициируется через Celery при исключении в задаче
- После исчерпания всех попыток — статус `failed`, записывается `error_code` и `error_message`
- При stale recovery — попытки не тратятся (задача просто переходит в `queued`)

---

## Cancellation Semantics

### Задача в статусе `queued`:
- Отмена **немедленная**
- Статус обновляется в `cancelled` напрямую, без участия воркера
- Celery задача никогда не будет исполнена (воркер пропустит `cancelled` задачи)

### Задача в статусе `running`:
- Устанавливается флаг `cancel_requested = true` в БД
- Воркер проверяет этот флаг **между шагами** pipeline (не прерывает текущий шаг)
- Когда флаг обнаружен — воркер завершает работу, статус переходит в `cancelled`
- Гарантируется атомарность: частично посчитанные результаты не сохраняются

### Нельзя отменить:
- `completed`, `failed`, `cancelled` — возвращается HTTP 409

---

## TTL и Expiration

- Каждая задача создаётся с полем `expires_at = NOW() + TTL`
- TTL по умолчанию: **86400 секунд (24 часа)**
- Задачи с истёкшим TTL не берутся воркерами (`WHERE expires_at > NOW()`)
- Celery Beat каждые **5 минут** запускает `cleanup_expired_jobs`:
  - Удаляет задачи в статусе `queued`/`failed`/`cancelled` с `expires_at < NOW()`
  - Задачи `completed` хранятся до истечения TTL, затем тоже удаляются

```
Celery Beat
    │
    │ каждые 300 сек
    ▼
cleanup_expired_jobs
    │
    │ DELETE FROM calculation_jobs
    │ WHERE expires_at < NOW()
    │   AND status IN ('queued', 'failed', 'cancelled', 'completed')
    ▼
  Устаревшие записи удалены
```
