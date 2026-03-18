from __future__ import annotations

from celery import Celery

from src.config import settings

celery_app = Celery(
    "estimation_engine",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["src.infrastructure.queue.tasks", "src.infrastructure.queue.cleanup"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_concurrency=settings.max_concurrent_jobs,
    beat_schedule={
        "recover-stale-jobs": {
            "task": "src.infrastructure.queue.cleanup.recover_stale_jobs",
            "schedule": 60.0,  # every 60 seconds
        },
        "cleanup-expired-jobs": {
            "task": "src.infrastructure.queue.cleanup.cleanup_expired_jobs",
            "schedule": 300.0,  # every 5 minutes
        },
    },
)
