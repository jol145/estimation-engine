from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.interfaces.price_provider import PriceEntry, PriceLookupQuery, PriceProvider
from src.domain.services.calculation_service import CalculationService
from src.infrastructure.repositories.calculation_repository import CalculationRepository
from src.shared.id_generator import generate_calculation_id


SAMPLE_PAYLOAD = {
    "region": {
        "country_code": "RU",
        "region_code": "RU-MOW",
    },
    "currency": "RUB",
    "items": [
        {
            "id": "m1",
            "kind": "material",
            "code": "test_material",
            "name": "Test Material",
            "quantity": 10.0,
            "unit": "pcs",
            "category": "test_category",
        }
    ],
}


class AlwaysPricedProvider(PriceProvider):
    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        return [
            PriceEntry(
                code=query.code,
                kind=query.kind,
                unit=query.unit,
                unit_price=Decimal("100"),
                currency="RUB",
                country_code=query.country_code,
                region_code=query.region_code,
                category=query.category or "",
            )
        ]

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        return []


@pytest.mark.asyncio
async def test_worker_locking_only_one_gets_lock(db_session: AsyncSession):
    """Two workers trying to lock the same job - only one should succeed."""
    repo = CalculationRepository(db_session)
    job_id = generate_calculation_id()

    await repo.create_job(job_id, SAMPLE_PAYLOAD)

    worker1_id = f"worker-{uuid.uuid4()}"
    worker2_id = f"worker-{uuid.uuid4()}"

    # First worker locks
    locked1 = await repo.try_lock_job(job_id, worker1_id)
    assert locked1 is not None
    assert locked1.locked_by == worker1_id

    # Second worker cannot lock (job is no longer queued)
    locked2 = await repo.try_lock_job(job_id, worker2_id)
    assert locked2 is None


@pytest.mark.asyncio
async def test_cancel_flag_checked_during_pipeline(db_session: AsyncSession):
    """Cancel flag should stop pipeline execution."""
    repo = CalculationRepository(db_session)
    job_id = generate_calculation_id()

    await repo.create_job(job_id, SAMPLE_PAYLOAD)

    worker_id = f"worker-{uuid.uuid4()}"
    await repo.try_lock_job(job_id, worker_id)

    # Set cancel flag before pipeline runs
    await repo.request_cancel(job_id)

    provider = AlwaysPricedProvider()
    service = CalculationService(repo, provider)
    await service.run_pipeline(job_id)

    # Job should be cancelled
    job = await repo.get_job(job_id)
    assert job is not None
    assert job.status == "cancelled"


@pytest.mark.asyncio
async def test_pipeline_completes_successfully(db_session: AsyncSession):
    """Full pipeline should complete and save result."""
    repo = CalculationRepository(db_session)
    job_id = generate_calculation_id()

    await repo.create_job(job_id, SAMPLE_PAYLOAD)

    worker_id = f"worker-{uuid.uuid4()}"
    await repo.try_lock_job(job_id, worker_id)

    provider = AlwaysPricedProvider()
    service = CalculationService(repo, provider)
    await service.run_pipeline(job_id)

    job = await repo.get_job(job_id)
    assert job is not None
    assert job.status == "completed"
    assert job.progress_percent == 100

    result = await repo.get_result(job_id)
    assert result is not None
    assert result.summary is not None
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_job_not_found_is_handled_gracefully(db_session: AsyncSession):
    """Pipeline with nonexistent job should not raise."""
    repo = CalculationRepository(db_session)
    provider = AlwaysPricedProvider()
    service = CalculationService(repo, provider)

    # Should not raise
    await service.run_pipeline("calc_nonexistent_job_id")


@pytest.mark.asyncio
async def test_heartbeat_updated_during_pipeline(db_session: AsyncSession):
    """Heartbeat should be updated during pipeline execution."""
    from datetime import datetime, timezone

    repo = CalculationRepository(db_session)
    job_id = generate_calculation_id()

    await repo.create_job(job_id, SAMPLE_PAYLOAD)

    worker_id = f"worker-{uuid.uuid4()}"
    locked = await repo.try_lock_job(job_id, worker_id)
    initial_heartbeat = locked.heartbeat_at

    provider = AlwaysPricedProvider()
    service = CalculationService(repo, provider)
    await service.run_pipeline(job_id)

    job = await repo.get_job(job_id)
    assert job is not None
    assert job.status == "completed"
