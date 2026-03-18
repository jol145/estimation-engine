from __future__ import annotations

import pytest
from decimal import Decimal
from typing import Any

from src.domain.interfaces.price_provider import PriceEntry, PriceLookupQuery, PriceProvider
from src.domain.models.region import Region
from src.domain.models.specification_item import SpecificationItem
from src.domain.services.pricing_service import PricingService


class MockPriceProviderForPricing(PriceProvider):
    """Configurable mock price provider for pricing tests."""

    def __init__(self, prices: list[PriceEntry], category_prices: list[PriceEntry] | None = None):
        self._prices = prices
        self._category_prices = category_prices or []

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        results = []
        for entry in self._prices:
            if entry.code != query.code:
                continue
            if entry.kind != query.kind:
                continue
            if entry.unit != query.unit:
                continue
            if entry.country_code != query.country_code:
                continue
            if query.region_code is not None and entry.region_code != query.region_code:
                continue
            if query.region_code is None and entry.region_code is not None:
                continue
            results.append(entry)
        return results

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        return [
            e for e in self._category_prices
            if e.category == query.category
            and e.kind == query.kind
            and e.country_code == query.country_code
        ]


def make_item(code: str = "test_code", kind: str = "material", unit: str = "pcs",
              category: str = "test_cat", quantity: float = 10.0) -> SpecificationItem:
    return SpecificationItem(
        id="item-1",
        kind=kind,
        code=code,
        name="Test Item",
        quantity=Decimal(str(quantity)),
        unit=unit,
        category=category,
    )


def make_region(country: str = "RU", region: str = "RU-MOW") -> Region:
    return Region(country_code=country, region_code=region)


@pytest.mark.asyncio
async def test_exact_match_level1_confidence_high():
    """Level 1: exact match gives confidence=high."""
    prices = [
        PriceEntry(
            code="test_code", kind="material", unit="pcs",
            unit_price=Decimal("100"), currency="RUB",
            country_code="RU", region_code="RU-MOW",
            category="test_cat",
        )
    ]
    service = PricingService(MockPriceProviderForPricing(prices))
    item = make_item()
    region = make_region()

    result = await service.price_item(item, region, "RUB")

    assert result.confidence == "high"
    assert result.pricing_method == "exact_match"
    assert result.average_unit_price == Decimal("100")
    assert result.line_total == Decimal("1000")


@pytest.mark.asyncio
async def test_country_fallback_level2_confidence_medium():
    """Level 2: country fallback gives confidence=medium."""
    prices = [
        PriceEntry(
            code="test_code", kind="material", unit="pcs",
            unit_price=Decimal("90"), currency="RUB",
            country_code="RU", region_code=None,
            category="test_cat",
        )
    ]
    service = PricingService(MockPriceProviderForPricing(prices))
    item = make_item()
    region = make_region()

    result = await service.price_item(item, region, "RUB")

    assert result.confidence == "medium"
    assert result.pricing_method == "country_fallback"
    assert result.average_unit_price == Decimal("90")


@pytest.mark.asyncio
async def test_unit_conversion_level3_confidence_medium():
    """Level 3: unit conversion gives confidence=medium."""
    prices = [
        PriceEntry(
            code="test_code", kind="material", unit="t",
            unit_price=Decimal("95000"), currency="RUB",
            country_code="RU", region_code=None,
            category="test_cat",
        )
    ]
    service = PricingService(MockPriceProviderForPricing(prices))
    # Item is in kg, price only in t
    item = make_item(unit="kg", quantity=1000.0)
    region = make_region()

    result = await service.price_item(item, region, "RUB")

    assert result.confidence == "medium"
    assert result.pricing_method == "unit_conversion"
    assert result.unit_converted is True
    assert result.original_unit == "t"
    # 95000 RUB/t = 95 RUB/kg
    assert result.average_unit_price == Decimal("95")


@pytest.mark.asyncio
async def test_category_fallback_level4_confidence_low():
    """Level 4: category fallback gives confidence=low."""
    category_prices = [
        PriceEntry(
            code="other_code", kind="material", unit="pcs",
            unit_price=Decimal("80"), currency="RUB",
            country_code="RU", region_code="RU-MOW",
            category="test_cat",
        )
    ]
    service = PricingService(MockPriceProviderForPricing([], category_prices))
    item = make_item(code="nonexistent_code")
    region = make_region()

    result = await service.price_item(item, region, "RUB")

    assert result.confidence == "low"
    assert result.pricing_method == "category_fallback"


@pytest.mark.asyncio
async def test_unpriced_level6_confidence_none():
    """Level 6: unpriced gives confidence=none and line_total=0."""
    service = PricingService(MockPriceProviderForPricing([]))
    item = make_item(code="totally_unknown_code", category="unknown_category")
    region = make_region()

    result = await service.price_item(item, region, "RUB")

    assert result.confidence == "none"
    assert result.pricing_method == "unpriced"
    assert result.line_total == Decimal("0")
    assert result.average_unit_price == Decimal("0")


class MockProviderCoefficient(PriceProvider):
    """Mock that returns country-level category prices only (simulates coefficient fallback)."""

    def __init__(self, country_price: Decimal):
        self._country_price = country_price

    async def get_prices(self, query: PriceLookupQuery) -> list[PriceEntry]:
        return []

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list[PriceEntry]:
        if query.region_code is not None:
            return []
        return [
            PriceEntry(
                code="other_code", kind=query.kind, unit=query.unit,
                unit_price=self._country_price, currency="RUB",
                country_code=query.country_code, region_code=None,
                category=query.category,
            )
        ]


@pytest.mark.asyncio
async def test_coefficient_fallback_level5():
    """Level 5: coefficient fallback applies regional coefficient to country-average price."""
    service = PricingService(MockProviderCoefficient(Decimal("1000")))
    item = make_item(code="unknown_code", category="test_cat")
    region = make_region(country="RU", region="RU-MOW")

    result = await service.price_item(item, region, "RUB")

    assert result.pricing_method == "coefficient_fallback"
    assert result.confidence == "low"
    # RU-MOW coefficient = 1.15, so 1000 * 1.15 = 1150
    assert result.average_unit_price == Decimal("1150")


class SlowProvider(PriceProvider):
    """Mock provider that always times out."""

    async def get_prices(self, query: PriceLookupQuery) -> list:
        import asyncio
        await asyncio.sleep(10)
        return []

    async def get_prices_by_category(self, query: PriceLookupQuery) -> list:
        import asyncio
        await asyncio.sleep(10)
        return []


@pytest.mark.asyncio
async def test_price_provider_timeout():
    """Slow provider should result in unpriced (timeout treated as no price found)."""
    service = PricingService(SlowProvider())
    item = make_item(code="any_code", unit="pcs", category="any_cat")
    region = make_region()

    result = await service.price_item(item, region, "RUB")

    # All levels time out → unpriced (pcs is a basic unit, no requires_manual_review)
    assert result.pricing_method == "unpriced"
    assert result.confidence == "none"
    assert result.line_total == 0


@pytest.mark.asyncio
async def test_multiple_sources_averages_price():
    """Multiple price entries should be averaged."""
    prices = [
        PriceEntry(
            code="test_code", kind="material", unit="pcs",
            unit_price=Decimal("100"), currency="RUB",
            country_code="RU", region_code="RU-MOW",
            category="test_cat",
        ),
        PriceEntry(
            code="test_code", kind="material", unit="pcs",
            unit_price=Decimal("120"), currency="RUB",
            country_code="RU", region_code="RU-MOW",
            category="test_cat",
        ),
    ]
    service = PricingService(MockPriceProviderForPricing(prices))
    item = make_item(quantity=1.0)
    region = make_region()

    result = await service.price_item(item, region, "RUB")

    assert result.average_unit_price == Decimal("110")
    assert result.sources_count == 2
    assert result.min_unit_price == Decimal("100")
    assert result.max_unit_price == Decimal("120")
