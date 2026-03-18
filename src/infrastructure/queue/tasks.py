from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from src.infrastructure.queue.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="src.infrastructure.queue.tasks.run_calculation",
)
def run_calculation(self: Any, calculation_id: str) -> None:
    """Celery task to run a calculation pipeline.

    Uses asyncio.run() to bridge sync Celery with async code.
    """
    asyncio.run(_run_calculation_async(self, calculation_id))


async def _run_calculation_async(task: Any, calculation_id: str) -> None:
    from src.config import settings
    from src.domain.services.calculation_service import CalculationService
    from src.infrastructure.db.base import AsyncSessionLocal
    from src.infrastructure.providers.static_price_provider import StaticPriceProvider
    from src.infrastructure.repositories.calculation_repository import CalculationRepository

    worker_id = f"worker-{task.request.id or uuid.uuid4()}"

    logger.info("task_started", calculation_id=calculation_id, worker_id=worker_id)

    async with AsyncSessionLocal() as session:
        repo = CalculationRepository(session)

        # Check TTL first
        job = await repo.get_job(calculation_id)
        if job is None:
            logger.warning("task_job_not_found", calculation_id=calculation_id)
            return

        if job.expires_at and datetime.now(timezone.utc) > job.expires_at:
            logger.warning("task_ttl_expired", calculation_id=calculation_id)
            await repo.update_status(
                calculation_id,
                "failed",
                error_code="TTL_EXPIRED",
                error_message="Calculation TTL expired before processing",
                failed_at=datetime.now(timezone.utc),
            )
            return

        # Try to lock the job
        locked_job = await repo.try_lock_job(calculation_id, worker_id)
        if locked_job is None:
            logger.info("task_already_locked", calculation_id=calculation_id)
            return

    try:
        async with AsyncSessionLocal() as session:
            repo = CalculationRepository(session)
            from src.infrastructure.providers.price_aggregator import PriceAggregator
            static_provider = StaticPriceProvider(session)
            price_provider = PriceAggregator(providers=[static_provider])
            service = CalculationService(repo, price_provider)
            await service.run_pipeline(calculation_id)

    except Exception as exc:
        logger.error(
            "task_failed",
            calculation_id=calculation_id,
            error=str(exc),
            retry_count=task.request.retries,
        )

        async with AsyncSessionLocal() as session:
            repo = CalculationRepository(session)
            job = await repo.get_job(calculation_id)
            if job and job.retry_count < settings.max_job_retries:
                await repo.update_status(
                    calculation_id,
                    "queued",
                    retry_count=(job.retry_count or 0) + 1,
                    locked_by=None,
                    locked_at=None,
                    error_code=None,
                    error_message=None,
                )
                try:
                    raise task.retry(exc=exc, countdown=30)
                except Exception:
                    pass
            else:
                error_code = getattr(exc, "error_code", "UNKNOWN_ERROR")
                now = datetime.now(timezone.utc)
                await repo.update_status(
                    calculation_id,
                    "failed",
                    error_code=error_code,
                    error_message=str(exc),
                    failed_at=now,
                    locked_by=None,
                    locked_at=None,
                )
