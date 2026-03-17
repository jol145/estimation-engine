from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

from src.domain.interfaces.price_provider import PriceEntry, PriceLookupQuery, PriceProvider
from src.domain.services.calculation_service import CalculationService
from src.infrastructure.repositories.calculation_repository import CalculationRepository


SAMPLE_REQUEST = {
    "region": {
        "country_code": "RU",
        "region_code": "RU-MOW",
    },
    "currency": "RUB",
    "items": [
        {
            "id": "m1",
            "kind": "material",
            "code": "concrete_b25",
            "name": "Concrete B25",
            "quantity": 5.0,
            "unit": "m3",
            "category": "concrete",
        },
        {
            "id": "w1",
            "kind": "work",
            "code": "foundation_work",
            "name": "Foundation Work",
            "quantity": 5.0,
            "unit": "m3",
            "category": "foundation",
        },
    ],
}


class SimpleTestPriceProvider(PriceProvider):
    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        price_map = {
            ("concrete_b25", "material", "m3", "RU", "RU-MOW"): Decimal("6500"),
            ("foundation_work", "work", "m3", "RU", "RU-MOW"): Decimal("4500"),
        }
        key = (query.code, query.kind, query.unit, query.country_code, query.region_code)
        if key in price_map:
            return [
                PriceEntry(
                    code=query.code,
                    kind=query.kind,
                    unit=query.unit,
                    unit_price=price_map[key],
                    currency="RUB",
                    country_code=query.country_code,
                    region_code=query.region_code,
                    category=query.category or "",
                )
            ]
        return []

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        return []


@pytest.mark.asyncio
async def test_post_calculation_returns_202(client: AsyncClient, db_session):
    with patch("src.api.routes.calculations.run_calculation") as mock_task:
        mock_task.delay = MagicMock(return_value=MagicMock(id="task-123"))
        response = await client.post("/v1/calculations", json=SAMPLE_REQUEST)

    assert response.status_code == 202
    data = response.json()
    assert "calculation_id" in data
    assert data["calculation_id"].startswith("calc_")
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_get_nonexistent_calculation_returns_404(client: AsyncClient):
    response = await client.get("/v1/calculations/calc_nonexistent123")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_calculation_status_returns_200(client: AsyncClient, db_session):
    with patch("src.api.routes.calculations.run_calculation") as mock_task:
        mock_task.delay = MagicMock(return_value=MagicMock(id="task-456"))
        post_response = await client.post("/v1/calculations", json=SAMPLE_REQUEST)

    calculation_id = post_response.json()["calculation_id"]

    response = await client.get(f"/v1/calculations/{calculation_id}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["calculation_id"] == calculation_id
    assert "status" in data
    assert "progress_percent" in data


@pytest.mark.asyncio
async def test_idempotency_key_deduplication(client: AsyncClient, db_session):
    """Same Idempotency-Key should return existing job."""
    headers = {"Idempotency-Key": "test-key-unique-123"}

    with patch("src.api.routes.calculations.run_calculation") as mock_task:
        mock_task.delay = MagicMock(return_value=MagicMock(id="task-789"))
        response1 = await client.post("/v1/calculations", json=SAMPLE_REQUEST, headers=headers)
        response2 = await client.post("/v1/calculations", json=SAMPLE_REQUEST, headers=headers)

    assert response1.status_code == 202
    assert response2.status_code == 202
    assert response1.json()["calculation_id"] == response2.json()["calculation_id"]


@pytest.mark.asyncio
async def test_get_completed_calculation(client: AsyncClient, db_session):
    """After running pipeline, GET should return completed result."""
    provider = SimpleTestPriceProvider()

    with patch("src.api.routes.calculations.run_calculation") as mock_task:
        mock_task.delay = MagicMock(return_value=MagicMock(id="task-run"))
        post_response = await client.post("/v1/calculations", json=SAMPLE_REQUEST)

    calculation_id = post_response.json()["calculation_id"]

    # Run pipeline directly (bypassing Celery)
    from src.infrastructure.repositories.calculation_repository import CalculationRepository
    from src.infrastructure.db.base import AsyncSessionLocal

    # We need to use the test session
    repo = CalculationRepository(db_session)

    # Lock the job manually for running
    import uuid
    from datetime import datetime, timezone
    worker_id = f"worker-test-{uuid.uuid4()}"
    locked = await repo.try_lock_job(calculation_id, worker_id)
    assert locked is not None

    service = CalculationService(repo, provider)
    await service.run_pipeline(calculation_id)

    response = await client.get(f"/v1/calculations/{calculation_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["summary"] is not None
    assert data["items"] is not None


@pytest.mark.asyncio
async def test_grand_total_equals_materials_plus_works(client: AsyncClient, db_session):
    """grand_total should equal materials_total + works_total."""
    provider = SimpleTestPriceProvider()

    with patch("src.api.routes.calculations.run_calculation") as mock_task:
        mock_task.delay = MagicMock(return_value=MagicMock(id="task-totals"))
        post_response = await client.post("/v1/calculations", json=SAMPLE_REQUEST)

    calculation_id = post_response.json()["calculation_id"]

    repo = CalculationRepository(db_session)
    import uuid
    worker_id = f"worker-test-{uuid.uuid4()}"
    await repo.try_lock_job(calculation_id, worker_id)

    service = CalculationService(repo, provider)
    await service.run_pipeline(calculation_id)

    response = await client.get(f"/v1/calculations/{calculation_id}")
    data = response.json()
    summary = data["summary"]

    assert abs(summary["grand_total"] - (summary["materials_total"] + summary["works_total"])) < 0.001
