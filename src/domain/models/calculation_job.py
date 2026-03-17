from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class CalculationJob:
    id: str
    status: str
    input_payload: dict[str, Any]
    idempotency_key: str | None = None
    celery_task_id: str | None = None
    progress_percent: int = 0
    processed_items: int = 0
    total_items: int = 0
    current_step: str | None = None
    cancel_requested: bool = False
    locked_by: str | None = None
    locked_at: datetime | None = None
    heartbeat_at: datetime | None = None
    expires_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    failed_at: datetime | None = None
    retry_count: int = 0
