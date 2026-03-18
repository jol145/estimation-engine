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


# ---------------------------------------------------------------------------
# Helpers shared by the new integration tests
# ---------------------------------------------------------------------------

async def _run_pipeline_with_provider(
    client: AsyncClient,
    db_session,
    request_body: dict,
    provider: PriceProvider,
) -> dict:
    """POST a calculation, run the pipeline synchronously, return GET result."""
    import uuid

    with patch("src.api.routes.calculations.run_calculation") as mock_task:
        mock_task.delay = MagicMock(return_value=MagicMock(id="task-helper"))
        post_resp = await client.post("/v1/calculations", json=request_body)

    assert post_resp.status_code == 202
    calc_id = post_resp.json()["calculation_id"]

    repo = CalculationRepository(db_session)
    worker_id = f"worker-test-{uuid.uuid4()}"
    locked = await repo.try_lock_job(calc_id, worker_id)
    assert locked is not None

    service = CalculationService(repo, provider)
    await service.run_pipeline(calc_id)

    get_resp = await client.get(f"/v1/calculations/{calc_id}")
    assert get_resp.status_code == 200
    return get_resp.json()


# ---------------------------------------------------------------------------
# Test 3: country-level fallback integration
# ---------------------------------------------------------------------------

class CountryOnlyPriceProvider(PriceProvider):
    """Returns prices only when region_code is None (country-level)."""

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        if query.region_code is not None:
            return []
        return [
            PriceEntry(
                code=query.code,
                kind=query.kind,
                unit=query.unit,
                unit_price=Decimal("3000"),
                currency="RUB",
                country_code=query.country_code,
                region_code=None,
                category=query.category or "",
                provider_name="country_only",
            )
        ]

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        return []


@pytest.mark.asyncio
async def test_country_fallback_integration(client: AsyncClient, db_session):
    """Full pipeline: provider only has country-level prices → country_fallback."""
    data = await _run_pipeline_with_provider(client, db_session, SAMPLE_REQUEST, CountryOnlyPriceProvider())

    assert data["status"] == "completed"
    assert data["items"] is not None
    methods = {item["pricing"]["pricing_method"] for item in data["items"]}
    assert "country_fallback" in methods


# ---------------------------------------------------------------------------
# Test 4: unit conversion integration
# ---------------------------------------------------------------------------

REBAR_REQUEST = {
    "region": {"country_code": "RU", "region_code": "RU-MOW"},
    "currency": "RUB",
    "items": [
        {
            "id": "r1",
            "kind": "material",
            "code": "rebar_d12",
            "name": "Арматура D12",
            "quantity": 500.0,
            "unit": "kg",
            "category": "reinforcement",
        }
    ],
}


class TonOnlyPriceProvider(PriceProvider):
    """Returns price for rebar_d12 only in tonnes."""

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        if query.code == "rebar_d12" and query.unit == "t":
            return [
                PriceEntry(
                    code=query.code,
                    kind=query.kind,
                    unit="t",
                    unit_price=Decimal("85000"),
                    currency="RUB",
                    country_code=query.country_code,
                    region_code=None,
                    category=query.category or "",
                    provider_name="ton_only",
                )
            ]
        return []

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        return []


@pytest.mark.asyncio
async def test_unit_conversion_integration(client: AsyncClient, db_session):
    """Full pipeline: price only in tonnes, item in kg → unit_conversion."""
    data = await _run_pipeline_with_provider(client, db_session, REBAR_REQUEST, TonOnlyPriceProvider())

    assert data["status"] == "completed"
    assert data["items"] is not None
    item = data["items"][0]
    assert item["pricing"]["pricing_method"] == "unit_conversion"
    assert item["pricing"]["unit_converted"] is True
    assert item["pricing"]["original_unit"] == "t"
    # 85000 RUB/t * 0.001 (kg->t factor) = 85 RUB/kg
    assert abs(item["pricing"]["average_unit_price"] - 85.0) < 0.01


# ---------------------------------------------------------------------------
# Test 5: provider timeout integration
# ---------------------------------------------------------------------------

class AlwaysSlowPriceProvider(PriceProvider):
    """Simulates a hung provider — always sleeps longer than the timeout."""

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        await asyncio.sleep(10)
        return []

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        await asyncio.sleep(10)
        return []


@pytest.mark.asyncio
async def test_provider_timeout_integration(client: AsyncClient, db_session):
    """Full pipeline with a slow provider — job must finish (not hang forever)."""
    data = await _run_pipeline_with_provider(client, db_session, SAMPLE_REQUEST, AlwaysSlowPriceProvider())

    # Job must reach a terminal state (completed with unpriced items, or failed)
    assert data["status"] in ("completed", "failed")
    if data["status"] == "completed":
        assert data["items"] is not None
        for item in data["items"]:
            assert item["pricing"]["pricing_method"] in ("unpriced", "requires_manual_review")


# ---------------------------------------------------------------------------
# Test 6: currency conversion integration
# ---------------------------------------------------------------------------

class UsdPriceProvider(PriceProvider):
    """Returns all prices in USD."""

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        return [
            PriceEntry(
                code=query.code,
                kind=query.kind,
                unit=query.unit,
                unit_price=Decimal("100"),
                currency="USD",
                country_code=query.country_code,
                region_code=query.region_code,
                category=query.category or "",
                provider_name="usd_provider",
            )
        ]

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        return []


@pytest.mark.asyncio
async def test_currency_conversion_integration(client: AsyncClient, db_session):
    """Provider returns USD prices; request in RUB → price auto-converted via EXCHANGE_RATES."""
    data = await _run_pipeline_with_provider(client, db_session, SAMPLE_REQUEST, UsdPriceProvider())

    assert data["status"] == "completed"
    assert data["currency"] == "RUB"
    for item in data["items"]:
        pricing = item["pricing"]
        assert pricing["currency"] == "RUB"
        # 100 USD * 92.50 = 9250 RUB
        assert abs(pricing["average_unit_price"] - 9250.0) < 0.01


# ---------------------------------------------------------------------------
# Test 7: city-level pricing integration
# ---------------------------------------------------------------------------

CITY_REQUEST = {
    "region": {
        "country_code": "RU",
        "region_code": "RU-MOW",
        "city": "Moscow",
    },
    "currency": "RUB",
    "items": [
        {
            "id": "c1",
            "kind": "material",
            "code": "concrete_b25",
            "name": "Concrete B25",
            "quantity": 1.0,
            "unit": "m3",
            "category": "concrete",
        }
    ],
}


class CityOnlyPriceProvider(PriceProvider):
    """Returns prices only when query.city == 'Moscow'."""

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        if query.city != "Moscow":
            return []
        return [
            PriceEntry(
                code=query.code,
                kind=query.kind,
                unit=query.unit,
                unit_price=Decimal("7500"),
                currency="RUB",
                country_code=query.country_code,
                region_code=query.region_code,
                city=query.city,
                category=query.category or "",
                provider_name="city_provider",
            )
        ]

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        return []


@pytest.mark.asyncio
async def test_city_level_pricing_integration(client: AsyncClient, db_session):
    """Provider returns prices only for city=Moscow → resolution_level=city-level."""
    data = await _run_pipeline_with_provider(client, db_session, CITY_REQUEST, CityOnlyPriceProvider())

    assert data["status"] == "completed"
    assert data["items"] is not None
    item = data["items"][0]
    assert item["pricing"]["pricing_method"] == "exact_match"
    assert item["pricing"]["resolution_level"] == "city-level"
    assert abs(item["pricing"]["average_unit_price"] - 7500.0) < 0.01
