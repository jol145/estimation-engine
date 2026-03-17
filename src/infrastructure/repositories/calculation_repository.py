from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models.calculation_job import CalculationJob as DomainJob
from src.domain.models.calculation_result import CalculationResult as DomainResult
from src.infrastructure.db.models import CalculationJob as DBJob
from src.infrastructure.db.models import CalculationResult as DBResult

logger = structlog.get_logger(__name__)


def _db_job_to_domain(db_job: DBJob) -> DomainJob:
    return DomainJob(
        id=db_job.id,
        status=db_job.status,
        input_payload=db_job.input_payload,
        idempotency_key=db_job.idempotency_key,
        celery_task_id=db_job.celery_task_id,
        progress_percent=db_job.progress_percent or 0,
        processed_items=db_job.processed_items or 0,
        total_items=db_job.total_items or 0,
        current_step=db_job.current_step,
        cancel_requested=db_job.cancel_requested or False,
        locked_by=db_job.locked_by,
        locked_at=db_job.locked_at,
        heartbeat_at=db_job.heartbeat_at,
        expires_at=db_job.expires_at,
        error_code=db_job.error_code,
        error_message=db_job.error_message,
        requested_at=db_job.requested_at,
        started_at=db_job.started_at,
        completed_at=db_job.completed_at,
        cancelled_at=db_job.cancelled_at,
        failed_at=db_job.failed_at,
        retry_count=db_job.retry_count or 0,
    )


class CalculationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_job(
        self,
        job_id: str,
        input_payload: dict[str, Any],
        idempotency_key: str | None = None,
        expires_at: datetime | None = None,
    ) -> DomainJob:
        db_job = DBJob(
            id=job_id,
            status="queued",
            input_payload=input_payload,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
            progress_percent=0,
            processed_items=0,
            total_items=0,
            cancel_requested=False,
            retry_count=0,
        )
        self.session.add(db_job)
        await self.session.commit()
        await self.session.refresh(db_job)
        return _db_job_to_domain(db_job)

    async def get_job(self, job_id: str) -> DomainJob | None:
        result = await self.session.execute(select(DBJob).where(DBJob.id == job_id))
        db_job = result.scalar_one_or_none()
        if db_job is None:
            return None
        return _db_job_to_domain(db_job)

    async def get_job_by_idempotency_key(self, key: str) -> DomainJob | None:
        result = await self.session.execute(select(DBJob).where(DBJob.idempotency_key == key))
        db_job = result.scalar_one_or_none()
        if db_job is None:
            return None
        return _db_job_to_domain(db_job)

    async def try_lock_job(self, job_id: str, worker_id: str) -> DomainJob | None:
        """Attempt to lock a queued job for processing using SELECT FOR UPDATE SKIP LOCKED."""
        from sqlalchemy import text

        result = await self.session.execute(
            select(DBJob)
            .where(DBJob.id == job_id, DBJob.status == "queued", DBJob.locked_by.is_(None))
            .with_for_update(skip_locked=True)
        )
        db_job = result.scalar_one_or_none()
        if db_job is None:
            return None

        now = datetime.now(timezone.utc)
        db_job.status = "running"
        db_job.locked_by = worker_id
        db_job.locked_at = now
        db_job.heartbeat_at = now
        db_job.started_at = now
        await self.session.commit()
        await self.session.refresh(db_job)
        return _db_job_to_domain(db_job)

    async def update_heartbeat(self, job_id: str) -> None:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(DBJob).where(DBJob.id == job_id).values(heartbeat_at=now)
        )
        await self.session.commit()

    async def update_progress(
        self,
        job_id: str,
        progress_percent: int,
        processed_items: int,
        total_items: int,
        current_step: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "progress_percent": progress_percent,
            "processed_items": processed_items,
            "total_items": total_items,
            "heartbeat_at": now,
        }
        if current_step is not None:
            values["current_step"] = current_step
        await self.session.execute(update(DBJob).where(DBJob.id == job_id).values(**values))
        await self.session.commit()

    async def update_status(
        self,
        job_id: str,
        status: str,
        **kwargs: Any,
    ) -> None:
        values: dict[str, Any] = {"status": status, **kwargs}
        await self.session.execute(update(DBJob).where(DBJob.id == job_id).values(**values))
        await self.session.commit()

    async def set_celery_task_id(self, job_id: str, celery_task_id: str) -> None:
        await self.session.execute(
            update(DBJob).where(DBJob.id == job_id).values(celery_task_id=celery_task_id)
        )
        await self.session.commit()

    async def request_cancel(self, job_id: str) -> DomainJob | None:
        job = await self.get_job(job_id)
        if job is None:
            return None
        await self.session.execute(
            update(DBJob).where(DBJob.id == job_id).values(cancel_requested=True)
        )
        await self.session.commit()
        return await self.get_job(job_id)

    async def save_result(
        self,
        calculation_id: str,
        summary: dict[str, Any],
        items: list[dict[str, Any]],
        assumptions: list[dict[str, Any]],
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        db_result = DBResult(
            calculation_id=calculation_id,
            summary=summary,
            items=items,
            assumptions=assumptions,
            diagnostics=diagnostics,
        )
        self.session.add(db_result)
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(DBJob)
            .where(DBJob.id == calculation_id)
            .values(
                status="completed",
                progress_percent=100,
                completed_at=now,
                locked_by=None,
                locked_at=None,
            )
        )
        await self.session.commit()

    async def get_result(self, calculation_id: str) -> DomainResult | None:
        result = await self.session.execute(
            select(DBResult).where(DBResult.calculation_id == calculation_id)
        )
        db_result = result.scalar_one_or_none()
        if db_result is None:
            return None
        return DomainResult(
            calculation_id=db_result.calculation_id,
            summary=db_result.summary,
            items=db_result.items,
            assumptions=db_result.assumptions,
            diagnostics=db_result.diagnostics,
            created_at=db_result.created_at,
        )

    async def get_stale_running_jobs(self, heartbeat_cutoff: datetime) -> list[DomainJob]:
        result = await self.session.execute(
            select(DBJob).where(
                DBJob.status == "running",
                DBJob.heartbeat_at < heartbeat_cutoff,
            )
        )
        return [_db_job_to_domain(j) for j in result.scalars().all()]

    async def get_expired_active_jobs(self, now: datetime) -> list[DomainJob]:
        result = await self.session.execute(
            select(DBJob).where(
                DBJob.status.in_(["queued", "running"]),
                DBJob.expires_at < now,
            )
        )
        return [_db_job_to_domain(j) for j in result.scalars().all()]
