from __future__ import annotations

from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.interfaces.price_provider import PriceEntry, PriceLookupQuery, PriceProvider
from src.infrastructure.db.models import PriceCatalog

logger = structlog.get_logger(__name__)


class StaticPriceProvider(PriceProvider):
    """Price provider that reads from the price_catalog table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        """Fetch prices by code, kind, unit, and region. Tries city-level first if city is provided."""
        # City-level search (most specific)
        if query.region_code and query.city:
            stmt_city = select(PriceCatalog).where(
                PriceCatalog.code == query.code,
                PriceCatalog.kind == query.kind,
                PriceCatalog.unit == query.unit,
                PriceCatalog.country_code == query.country_code,
                PriceCatalog.region_code == query.region_code,
                PriceCatalog.city == query.city,
            )
            result_city = await self.session.execute(stmt_city)
            rows_city = result_city.scalars().all()
            if rows_city:
                return [
                    PriceEntry(
                        code=row.code,
                        kind=row.kind,
                        unit=row.unit,
                        unit_price=Decimal(str(row.unit_price)),
                        currency=row.currency,
                        country_code=row.country_code,
                        region_code=row.region_code,
                        city=row.city,
                        provider_name=row.provider_name,
                        category=row.category,
                    )
                    for row in rows_city
                ]

        stmt = select(PriceCatalog).where(
            PriceCatalog.code == query.code,
            PriceCatalog.kind == query.kind,
            PriceCatalog.unit == query.unit,
            PriceCatalog.country_code == query.country_code,
        )

        if query.region_code:
            stmt = stmt.where(PriceCatalog.region_code == query.region_code)

        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        return [
            PriceEntry(
                code=row.code,
                kind=row.kind,
                unit=row.unit,
                unit_price=Decimal(str(row.unit_price)),
                currency=row.currency,
                country_code=row.country_code,
                region_code=row.region_code,
                city=row.city,
                provider_name=row.provider_name,
                category=row.category,
            )
            for row in rows
        ]

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        """Fetch prices by category for fallback pricing."""
        stmt = select(PriceCatalog).where(
            PriceCatalog.category == query.category,
            PriceCatalog.kind == query.kind,
            PriceCatalog.country_code == query.country_code,
        )

        if query.region_code:
            stmt = stmt.where(PriceCatalog.region_code == query.region_code)

        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        return [
            PriceEntry(
                code=row.code,
                kind=row.kind,
                unit=row.unit,
                unit_price=Decimal(str(row.unit_price)),
                currency=row.currency,
                country_code=row.country_code,
                region_code=row.region_code,
                city=row.city,
                provider_name=row.provider_name,
                category=row.category,
            )
            for row in rows
        ]
