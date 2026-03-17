from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass
class PriceLookupQuery:
    code: str
    kind: str
    unit: str
    country_code: str
    region_code: str | None = None
    city: str | None = None
    category: str | None = None


@dataclass
class PriceEntry:
    code: str
    kind: str
    unit: str
    unit_price: Decimal
    currency: str
    country_code: str
    region_code: str | None = None
    city: str | None = None
    provider_name: str = ""
    category: str = ""


class PriceProvider(ABC):
    """Abstract interface for price data providers."""

    @abstractmethod
    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        """Fetch prices matching the given query."""
        ...

    @abstractmethod
    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        """Fetch prices by category for fallback pricing."""
        ...
