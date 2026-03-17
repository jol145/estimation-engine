from __future__ import annotations

import asyncio
from decimal import Decimal

import structlog

from src.config import settings
from src.domain.interfaces.price_provider import PriceEntry, PriceLookupQuery, PriceProvider

logger = structlog.get_logger(__name__)


class PriceAggregator:
    """Aggregates prices from multiple providers with concurrency control."""

    def __init__(self, providers: list[PriceProvider]) -> None:
        self.providers = providers
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_provider_requests)

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        """Fetch prices from all providers with semaphore-limited concurrency."""
        tasks = [self._fetch_from_provider(provider, query, "prices") for provider in self.providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_entries: list[PriceEntry] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("provider_error", error=str(result))
                continue
            all_entries.extend(result)

        return all_entries

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        """Fetch prices by category from all providers."""
        tasks = [self._fetch_from_provider(provider, query, "category") for provider in self.providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_entries: list[PriceEntry] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("provider_category_error", error=str(result))
                continue
            all_entries.extend(result)

        return all_entries

    async def _fetch_from_provider(
        self, provider: PriceProvider, query: PriceLookupQuery, fetch_type: str
    ) -> list[PriceEntry]:
        async with self._semaphore:
            try:
                if fetch_type == "prices":
                    return await asyncio.wait_for(
                        provider.get_prices(query),
                        timeout=settings.price_provider_timeout_seconds,
                    )
                else:
                    return await asyncio.wait_for(
                        provider.get_prices_by_category(query),
                        timeout=settings.price_provider_timeout_seconds,
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "provider_timeout",
                    provider=type(provider).__name__,
                    timeout=settings.price_provider_timeout_seconds,
                )
                return []
