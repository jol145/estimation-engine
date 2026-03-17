from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from src.api.dependencies import get_repository
from src.api.schemas.calculation_input import CalculationRequest
from src.api.schemas.calculation_output import (
    CalculationJobResponse,
    CalculationResultResponse,
    CalculationStatusResponse,
    PricedItemOutput,
    SummaryOutput,
)
from src.config import settings
from src.infrastructure.queue.tasks import run_calculation
from src.infrastructure.repositories.calculation_repository import CalculationRepository
from src.shared.id_generator import generate_calculation_id

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/calculations", tags=["calculations"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=CalculationJobResponse)
async def create_calculation(
    request: Request,
    body: CalculationRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    repo: CalculationRepository = Depends(get_repository),
) -> Any:
    """Create a new calculation job."""

    # Validate payload size
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_payload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Payload too large",
        )

    # Check idempotency key before creating
    if idempotency_key:
        existing_job = await repo.get_job_by_idempotency_key(idempotency_key)
        if existing_job is not None:
            logger.info(
                "idempotency_hit", key=idempotency_key, calculation_id=existing_job.id
            )
            return CalculationJobResponse(
                calculation_id=existing_job.id,
                status=existing_job.status,
                progress_percent=existing_job.progress_percent,
                processed_items=existing_job.processed_items,
                total_items=existing_job.total_items,
                current_step=existing_job.current_step,
                requested_at=existing_job.requested_at,
            )

    calculation_id = generate_calculation_id()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.calculation_ttl_seconds)

    payload = body.model_dump()

    job = await repo.create_job(
        job_id=calculation_id,
        input_payload=payload,
        idempotency_key=idempotency_key,
        expires_at=expires_at,
    )

    # Dispatch Celery task
    try:
        task = run_calculation.delay(calculation_id)
        await repo.set_celery_task_id(calculation_id, task.id)
        logger.info("calculation_queued", calculation_id=calculation_id, task_id=task.id)
    except Exception as exc:
        logger.warning("celery_dispatch_failed", calculation_id=calculation_id, error=str(exc))

    return CalculationJobResponse(
        calculation_id=job.id,
        status=job.status,
        progress_percent=job.progress_percent,
        processed_items=job.processed_items,
        total_items=job.total_items,
        current_step=job.current_step,
        requested_at=job.requested_at,
    )


@router.get("/{calculation_id}", response_model=CalculationResultResponse)
async def get_calculation(
    calculation_id: str,
    repo: CalculationRepository = Depends(get_repository),
) -> Any:
    """Get full calculation result or progress."""
    job = await repo.get_job(calculation_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Calculation '{calculation_id}' not found",
        )

    response = CalculationResultResponse(
        calculation_id=job.id,
        status=job.status,
        progress_percent=job.progress_percent,
        current_step=job.current_step,
        error_code=job.error_code,
        error_message=job.error_message,
        requested_at=job.requested_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        cancelled_at=job.cancelled_at,
        failed_at=job.failed_at,
    )

    if job.status == "completed":
        result = await repo.get_result(calculation_id)
        if result is not None:
            response.summary = SummaryOutput(**result.summary)
            response.items = [PricedItemOutput(**item) for item in result.items]
            response.assumptions = result.assumptions
            response.diagnostics = result.diagnostics

    return response


@router.get("/{calculation_id}/status", response_model=CalculationStatusResponse)
async def get_calculation_status(
    calculation_id: str,
    repo: CalculationRepository = Depends(get_repository),
) -> Any:
    """Lightweight polling endpoint for calculation status."""
    job = await repo.get_job(calculation_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Calculation '{calculation_id}' not found",
        )

    return CalculationStatusResponse(
        calculation_id=job.id,
        status=job.status,
        progress_percent=job.progress_percent,
        current_step=job.current_step,
        error_code=job.error_code,
    )


@router.post("/{calculation_id}/cancel", response_model=CalculationJobResponse)
async def cancel_calculation(
    calculation_id: str,
    repo: CalculationRepository = Depends(get_repository),
) -> Any:
    """Request cancellation of a calculation job."""
    job = await repo.get_job(calculation_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Calculation '{calculation_id}' not found",
        )

    # Cannot cancel completed/failed/cancelled jobs
    terminal_statuses = {"completed", "failed", "cancelled"}
    if job.status in terminal_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel calculation in status '{job.status}'",
        )

    # If queued, cancel immediately
    if job.status == "queued":
        now = datetime.now(timezone.utc)
        await repo.update_status(
            calculation_id,
            "cancelled",
            cancelled_at=now,
        )
        job = await repo.get_job(calculation_id)
    else:
        # If running, set cancel_requested flag
        job = await repo.request_cancel(calculation_id)

    logger.info("calculation_cancel_requested", calculation_id=calculation_id)

    return CalculationJobResponse(
        calculation_id=job.id,
        status=job.status,
        progress_percent=job.progress_percent,
        requested_at=job.requested_at,
        cancelled_at=job.cancelled_at,
    )
