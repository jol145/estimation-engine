from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

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
    ],
}


@pytest.mark.asyncio
async def test_cancel_queued_job_returns_200(client: AsyncClient, db_session):
    """Cancelling a queued job should succeed and return status=cancelled."""
    with patch("src.api.routes.calculations.run_calculation") as mock_task:
        mock_task.delay = MagicMock(return_value=MagicMock(id="task-cancel"))
        post_response = await client.post("/v1/calculations", json=SAMPLE_REQUEST)

    calculation_id = post_response.json()["calculation_id"]

    cancel_response = await client.post(f"/v1/calculations/{calculation_id}/cancel")
    assert cancel_response.status_code == 200
    data = cancel_response.json()
    assert data["status"] == "cancelled"
    assert data["calculation_id"] == calculation_id


@pytest.mark.asyncio
async def test_cancel_completed_job_returns_409(client: AsyncClient, db_session):
    """Cancelling a completed job should return 409 Conflict."""
    from src.domain.interfaces.price_provider import PriceEntry, PriceLookupQuery, PriceProvider
    from src.domain.services.calculation_service import CalculationService
    from decimal import Decimal
    import uuid

    class SimpleProvider(PriceProvider):
        async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
            return [
                PriceEntry(
                    code=query.code, kind=query.kind, unit=query.unit,
                    unit_price=Decimal("100"), currency="RUB",
                    country_code=query.country_code, region_code=query.region_code,
                    category=query.category or "",
                )
            ]

        async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
            return []

    with patch("src.api.routes.calculations.run_calculation") as mock_task:
        mock_task.delay = MagicMock(return_value=MagicMock(id="task-complete"))
        post_response = await client.post("/v1/calculations", json=SAMPLE_REQUEST)

    calculation_id = post_response.json()["calculation_id"]

    repo = CalculationRepository(db_session)
    worker_id = f"worker-test-{uuid.uuid4()}"
    await repo.try_lock_job(calculation_id, worker_id)

    service = CalculationService(repo, SimpleProvider())
    await service.run_pipeline(calculation_id)

    cancel_response = await client.post(f"/v1/calculations/{calculation_id}/cancel")
    assert cancel_response.status_code == 409


@pytest.mark.asyncio
async def test_cancel_nonexistent_job_returns_404(client: AsyncClient):
    response = await client.post("/v1/calculations/calc_nonexistent/cancel")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_already_cancelled_job_returns_409(client: AsyncClient, db_session):
    """Cancelling already cancelled job should return 409."""
    with patch("src.api.routes.calculations.run_calculation") as mock_task:
        mock_task.delay = MagicMock(return_value=MagicMock(id="task-already"))
        post_response = await client.post("/v1/calculations", json=SAMPLE_REQUEST)

    calculation_id = post_response.json()["calculation_id"]

    # First cancel
    await client.post(f"/v1/calculations/{calculation_id}/cancel")

    # Second cancel
    cancel_response = await client.post(f"/v1/calculations/{calculation_id}/cancel")
    assert cancel_response.status_code == 409
