from __future__ import annotations

import json
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

import structlog

logger = structlog.get_logger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Middleware to handle idempotency keys on POST requests."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only handle POST requests
        if request.method != "POST":
            return await call_next(request)

        idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not idempotency_key:
            return await call_next(request)

        # Only apply to calculation creation endpoint
        if not request.url.path.endswith("/calculations"):
            return await call_next(request)

        # Check if a job with this idempotency key already exists
        try:
            from src.infrastructure.db.base import AsyncSessionLocal
            from src.infrastructure.repositories.calculation_repository import CalculationRepository

            async with AsyncSessionLocal() as session:
                repo = CalculationRepository(session)
                existing_job = await repo.get_job_by_idempotency_key(idempotency_key)

                if existing_job is not None:
                    logger.info(
                        "idempotency_hit",
                        key=idempotency_key,
                        calculation_id=existing_job.id,
                    )
                    return JSONResponse(
                        status_code=202,
                        content={
                            "calculation_id": existing_job.id,
                            "status": existing_job.status,
                            "progress_percent": existing_job.progress_percent,
                            "requested_at": existing_job.requested_at.isoformat()
                            if existing_job.requested_at
                            else None,
                        },
                    )
        except Exception as exc:
            logger.error("idempotency_check_failed", error=str(exc))
            # Continue without idempotency check on error
            pass

        response = await call_next(request)
        return response
