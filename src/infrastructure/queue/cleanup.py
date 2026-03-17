from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog

from src.config import settings
from src.infrastructure.queue.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="src.infrastructure.queue.cleanup.recover_stale_jobs")
def recover_stale_jobs() -> None:
    """Find running jobs with stale heartbeat and requeue or mark as failed."""
    asyncio.run(_recover_stale_jobs_async())


@celery_app.task(name="src.infrastructure.queue.cleanup.cleanup_expired_jobs")
def cleanup_expired_jobs() -> None:
    """Mark expired active jobs as failed and delete old completed/failed jobs."""
    asyncio.run(_cleanup_expired_jobs_async())


async def _recover_stale_jobs_async() -> None:
    from src.infrastructure.db.base import AsyncSessionLocal
    from src.infrastructure.repositories.calculation_repository import CalculationRepository

    now = datetime.now(timezone.utc)
    heartbeat_cutoff = now - timedelta(seconds=settings.heartbeat_timeout_seconds)

    async with AsyncSessionLocal() as session:
        repo = CalculationRepository(session)
        stale_jobs = await repo.get_stale_running_jobs(heartbeat_cutoff)

        for job in stale_jobs:
            logger.warning(
                "stale_job_found",
                calculation_id=job.id,
                heartbeat_at=str(job.heartbeat_at),
                retry_count=job.retry_count,
            )

            if (job.retry_count or 0) < settings.max_job_retries:
                # Requeue
                await repo.update_status(
                    job.id,
                    "queued",
                    retry_count=(job.retry_count or 0) + 1,
                    locked_by=None,
                    locked_at=None,
                    error_code=None,
                    error_message=None,
                )
                # Re-dispatch task
                from src.infrastructure.queue.tasks import run_calculation
                run_calculation.delay(job.id)
                logger.info("stale_job_requeued", calculation_id=job.id)
            else:
                await repo.update_status(
                    job.id,
                    "failed",
                    error_code="WORKER_TIMEOUT",
                    error_message="Worker heartbeat timeout exceeded max retries",
                    failed_at=now,
                    locked_by=None,
                    locked_at=None,
                )
                logger.warning("stale_job_failed", calculation_id=job.id)


async def _cleanup_expired_jobs_async() -> None:
    from src.infrastructure.db.base import AsyncSessionLocal
    from src.infrastructure.repositories.calculation_repository import CalculationRepository

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        repo = CalculationRepository(session)
        expired_jobs = await repo.get_expired_active_jobs(now)

        for job in expired_jobs:
            logger.info("expiring_job", calculation_id=job.id, status=job.status)
            await repo.update_status(
                job.id,
                "failed",
                error_code="TTL_EXPIRED",
                error_message="Calculation TTL expired",
                failed_at=now,
                locked_by=None,
                locked_at=None,
            )
