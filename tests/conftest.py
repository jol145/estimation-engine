from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.config import Settings
from src.domain.interfaces.price_provider import PriceEntry, PriceLookupQuery, PriceProvider
from src.infrastructure.db.base import Base
from src.main import create_app

# Override settings for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        database_url=TEST_DB_URL,
        sync_database_url="sqlite:///./test.db",
        celery_broker_url="memory://",
        celery_result_backend="cache+memory://",
        calculation_ttl_seconds=3600,
        heartbeat_timeout_seconds=60,
        max_items_per_calculation=500,
        max_concurrent_jobs=4,
        max_concurrent_provider_requests=10,
        price_provider_timeout_seconds=3.0,
        max_job_retries=2,
    )


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)

    # Patch JSONB to use JSON for SQLite compatibility
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import JSON

    async with engine.begin() as conn:
        # Create tables using JSON instead of JSONB for SQLite
        await conn.run_sync(_create_tables_sqlite)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


def _create_tables_sqlite(conn: Any) -> None:
    """Create tables with SQLite-compatible types."""
    from sqlalchemy import (
        Boolean, Column, DateTime, ForeignKey, Integer, Numeric, Text, JSON,
        MetaData, Table, func
    )
    from sqlalchemy import create_engine

    metadata = MetaData()

    Table(
        "calculation_jobs",
        metadata,
        Column("id", Text, primary_key=True),
        Column("idempotency_key", Text, unique=True, nullable=True),
        Column("celery_task_id", Text, nullable=True),
        Column("status", Text, nullable=False),
        Column("progress_percent", Integer, default=0),
        Column("processed_items", Integer, default=0),
        Column("total_items", Integer, default=0),
        Column("current_step", Text, nullable=True),
        Column("input_payload", JSON, nullable=False),
        Column("cancel_requested", Boolean, default=False),
        Column("locked_by", Text, nullable=True),
        Column("locked_at", DateTime(timezone=True), nullable=True),
        Column("heartbeat_at", DateTime(timezone=True), nullable=True),
        Column("expires_at", DateTime(timezone=True), nullable=True),
        Column("error_code", Text, nullable=True),
        Column("error_message", Text, nullable=True),
        Column("requested_at", DateTime(timezone=True), nullable=True),
        Column("started_at", DateTime(timezone=True), nullable=True),
        Column("completed_at", DateTime(timezone=True), nullable=True),
        Column("cancelled_at", DateTime(timezone=True), nullable=True),
        Column("failed_at", DateTime(timezone=True), nullable=True),
        Column("retry_count", Integer, default=0),
    )

    Table(
        "calculation_results",
        metadata,
        Column("calculation_id", Text, ForeignKey("calculation_jobs.id"), primary_key=True),
        Column("summary", JSON, nullable=False),
        Column("items", JSON, nullable=False),
        Column("assumptions", JSON, nullable=False),
        Column("diagnostics", JSON, nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=True),
    )

    metadata.create_all(conn)


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    TestSessionLocal = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture
def mock_price_provider() -> PriceProvider:
    """Mock price provider for unit tests with predefined prices."""

    class MockPriceProvider(PriceProvider):
        def __init__(self) -> None:
            self.prices: dict[str, list[PriceEntry]] = {
                "material_pcs_RU_RU-MOW": [
                    PriceEntry(
                        code="test_material",
                        kind="material",
                        unit="pcs",
                        unit_price=Decimal("100.00"),
                        currency="RUB",
                        country_code="RU",
                        region_code="RU-MOW",
                        provider_name="test",
                        category="test_category",
                    )
                ],
                "material_pcs_RU_None": [
                    PriceEntry(
                        code="country_material",
                        kind="material",
                        unit="pcs",
                        unit_price=Decimal("90.00"),
                        currency="RUB",
                        country_code="RU",
                        region_code=None,
                        provider_name="test",
                        category="test_category",
                    )
                ],
            }

        async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
            key = f"{query.code}_{query.unit}_{query.country_code}_{query.region_code}"
            # Exact match with region
            if query.region_code:
                result = [
                    e for k, entries in self.prices.items()
                    for e in entries
                    if e.code == query.code
                    and e.kind == query.kind
                    and e.unit == query.unit
                    and e.country_code == query.country_code
                    and e.region_code == query.region_code
                ]
                if result:
                    return result
            # Country-level match (no region)
            else:
                return [
                    e for k, entries in self.prices.items()
                    for e in entries
                    if e.code == query.code
                    and e.kind == query.kind
                    and e.unit == query.unit
                    and e.country_code == query.country_code
                    and e.region_code is None
                ]
            return []

        async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
            return [
                e for k, entries in self.prices.items()
                for e in entries
                if e.category == query.category
                and e.kind == query.kind
                and e.country_code == query.country_code
            ]

    return MockPriceProvider()


@pytest_asyncio.fixture
async def app(db_engine):
    """Create test FastAPI app with test database."""
    from src.infrastructure.db import base as db_base
    from src.infrastructure.db.base import AsyncSessionLocal

    TestSessionLocal = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    fastapi_app = create_app()

    # Override the database session dependency
    from src.api.dependencies import get_db_session
    from src.infrastructure.repositories.calculation_repository import CalculationRepository

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with TestSessionLocal() as session:
            yield session

    fastapi_app.dependency_overrides[get_db_session] = override_get_db

    yield fastapi_app


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
