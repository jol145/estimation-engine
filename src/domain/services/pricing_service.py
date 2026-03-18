from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

import structlog

from src.config import settings
from src.domain.interfaces.price_provider import PriceLookupQuery, PriceProvider
from src.domain.models.region import Region
from src.domain.models.specification_item import SpecificationItem
from src.shared.units.unit_converter import UNIT_CONVERSIONS, can_convert, convert

logger = structlog.get_logger(__name__)

EXCHANGE_RATES: dict[tuple[str, str], Decimal] = {
    ("USD", "RUB"): Decimal("92.50"),
    ("EUR", "RUB"): Decimal("100.20"),
    ("RUB", "USD"): Decimal("0.0108"),
    ("RUB", "EUR"): Decimal("0.00998"),
    ("USD", "EUR"): Decimal("0.923"),
    ("EUR", "USD"): Decimal("1.083"),
}


def _convert_currency(price: Decimal, from_currency: str, to_currency: str) -> Decimal | None:
    if from_currency == to_currency:
        return price
    key = (from_currency.upper(), to_currency.upper())
    rate = EXCHANGE_RATES.get(key)
    if rate is None:
        return None
    return price * rate


REGIONAL_COEFFICIENTS: dict[str, Decimal] = {
    "RU-MOW": Decimal("1.15"),  # Moscow — prices ~15% above country average
    "RU-SPE": Decimal("1.10"),  # St Petersburg
    "RU-KDA": Decimal("1.05"),  # Krasnodar
    "RU-SVE": Decimal("0.95"),  # Sverdlovsk (Ekaterinburg)
    "RU-NSO": Decimal("0.90"),  # Novosibirsk
}

PricingMethod = Literal[
    "exact_match",
    "country_fallback",
    "unit_conversion",
    "category_fallback",
    "coefficient_fallback",
    "unpriced",
    "requires_manual_review",
]

Confidence = Literal["high", "medium", "low", "none"]


@dataclass
class PricingResult:
    average_unit_price: Decimal
    currency: str
    price_unit: str
    sources_count: int
    min_unit_price: Decimal | None
    max_unit_price: Decimal | None
    pricing_method: PricingMethod
    confidence: Confidence
    match_path: str | None
    fallback_reason: str | None
    unit_converted: bool
    original_unit: str | None
    line_total: Decimal
    resolution_level: str | None = None
    sources_queried: list[str] | None = None


class PricingService:
    """6-level pricing pipeline."""

    def __init__(self, price_provider: PriceProvider) -> None:
        self.price_provider = price_provider

    async def _get_prices(self, query: PriceLookupQuery) -> list:
        try:
            return await asyncio.wait_for(
                self.price_provider.get_prices(query),
                timeout=settings.price_provider_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("price_provider_timeout", query=query)
            return []

    async def _get_prices_by_category(self, query: PriceLookupQuery) -> list:
        try:
            return await asyncio.wait_for(
                self.price_provider.get_prices_by_category(query),
                timeout=settings.price_provider_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("price_provider_timeout_category", query=query)
            return []

    async def price_item(
        self,
        item: SpecificationItem,
        region: Region,
        currency: str,
    ) -> PricingResult:
        """Run the 6-level pricing pipeline for a single item."""

        # Level 1a: City-level exact match (most specific)
        if region.city:
            entries = await self._get_prices(
                PriceLookupQuery(
                    code=item.code,
                    kind=item.kind,
                    unit=item.unit,
                    country_code=region.country_code,
                    region_code=region.region_code,
                    city=region.city,
                    category=item.category,
                )
            )
            if entries:
                return self._compute_result(
                    entries,
                    item,
                    currency,
                    method="exact_match",
                    confidence="high",
                    match_path=f"{region.country_code}/{region.region_code}/{region.city}/{item.unit}",
                    fallback_reason=None,
                    unit_converted=False,
                    original_unit=None,
                    resolution_level="city-level",
                )

        # Level 1b: Region-level exact match
        entries = await self._get_prices(
            PriceLookupQuery(
                code=item.code,
                kind=item.kind,
                unit=item.unit,
                country_code=region.country_code,
                region_code=region.region_code,
                category=item.category,
            )
        )
        if entries:
            return self._compute_result(
                entries,
                item,
                currency,
                method="exact_match",
                confidence="high",
                match_path=f"{region.country_code}/{region.region_code}/{item.unit}",
                fallback_reason=None,
                unit_converted=False,
                original_unit=None,
                resolution_level="region-level",
            )

        # Level 2: Country match - code + country_code + unit (no region filter)
        entries = await self._get_prices(
            PriceLookupQuery(
                code=item.code,
                kind=item.kind,
                unit=item.unit,
                country_code=region.country_code,
                region_code=None,
                category=item.category,
            )
        )
        if entries:
            return self._compute_result(
                entries,
                item,
                currency,
                method="country_fallback",
                confidence="medium",
                match_path=f"{region.country_code}/{item.unit}",
                fallback_reason="no_regional_price",
                unit_converted=False,
                original_unit=None,
                resolution_level="country-level",
            )

        # Level 3: Unit conversion - try convertible units
        for (from_unit, to_unit), factor in UNIT_CONVERSIONS.items():
            if from_unit == item.unit:
                # Try region-level with converted unit
                entries = await self._get_prices(
                    PriceLookupQuery(
                        code=item.code,
                        kind=item.kind,
                        unit=to_unit,
                        country_code=region.country_code,
                        region_code=region.region_code,
                        city=region.city,
                        category=item.category,
                    )
                )
                if not entries:
                    entries = await self._get_prices(
                        PriceLookupQuery(
                            code=item.code,
                            kind=item.kind,
                            unit=to_unit,
                            country_code=region.country_code,
                            region_code=None,
                            category=item.category,
                        )
                    )
                if entries:
                    # Convert price back to original unit
                    converted_entries = []
                    for e in entries:
                        from copy import copy

                        new_entry = copy(e)
                        # price_in_original_unit = price_in_to_unit * factor
                        # e.g. price in t (95000 RUB/t), factor (kg->t) = 0.001
                        # price_in_kg = 95000 * 0.001 = 95 RUB/kg
                        new_entry.unit_price = e.unit_price * factor
                        new_entry.unit = item.unit
                        converted_entries.append(new_entry)
                    return self._compute_result(
                        converted_entries,
                        item,
                        currency,
                        method="unit_conversion",
                        confidence="medium",
                        match_path=f"{region.country_code}/{to_unit}->converted_to_{item.unit}",
                        fallback_reason="unit_converted",
                        unit_converted=True,
                        original_unit=to_unit,
                        resolution_level="country-level",
                    )

        # Level 4: Category fallback - same category in same region
        entries = await self._get_prices_by_category(
            PriceLookupQuery(
                code=item.code,
                kind=item.kind,
                unit=item.unit,
                country_code=region.country_code,
                region_code=region.region_code,
                city=region.city,
                category=item.category,
            )
        )
        if entries:
            return self._compute_result(
                entries,
                item,
                currency,
                method="category_fallback",
                confidence="low",
                match_path=f"{region.country_code}/{region.region_code}/category:{item.category}",
                fallback_reason="no_exact_code_match",
                unit_converted=False,
                original_unit=None,
                resolution_level="region-level",
            )

        # Level 5: Coefficient fallback — country-average price * regional coefficient
        coefficient = REGIONAL_COEFFICIENTS.get(region.region_code, Decimal("1.0"))
        country_category_entries = await self._get_prices_by_category(
            PriceLookupQuery(
                code=item.code,
                kind=item.kind,
                unit=item.unit,
                country_code=region.country_code,
                region_code=None,
                category=item.category,
            )
        )
        if country_category_entries:
            from copy import copy
            adjusted = []
            for e in country_category_entries:
                new_e = copy(e)
                new_e.unit_price = e.unit_price * coefficient
                adjusted.append(new_e)
            return self._compute_result(
                adjusted,
                item,
                currency,
                method="coefficient_fallback",
                confidence="low",
                match_path=f"{region.country_code}/category:{item.category}*coeff:{coefficient}",
                fallback_reason="regional_coefficient_applied",
                unit_converted=False,
                original_unit=None,
                resolution_level="coefficient-based",
            )

        # Level 6: Unpriced (or requires_manual_review for non-convertible exotic units)
        basic_units = {"pcs", "m", "m2", "m3", "kg", "t", "l"}
        has_conversions = any(fu == item.unit for (fu, _) in UNIT_CONVERSIONS)
        if not has_conversions and item.unit not in basic_units:
            return PricingResult(
                average_unit_price=Decimal("0"),
                currency=currency,
                price_unit=item.unit,
                sources_count=0,
                min_unit_price=None,
                max_unit_price=None,
                pricing_method="requires_manual_review",
                confidence="none",
                match_path=None,
                fallback_reason="unit_not_convertible",
                unit_converted=False,
                original_unit=None,
                line_total=Decimal("0"),
                resolution_level=None,
                sources_queried=[],
            )

        return PricingResult(
            average_unit_price=Decimal("0"),
            currency=currency,
            price_unit=item.unit,
            sources_count=0,
            min_unit_price=None,
            max_unit_price=None,
            pricing_method="unpriced",
            confidence="none",
            match_path=None,
            fallback_reason="no_price_found",
            unit_converted=False,
            original_unit=None,
            line_total=Decimal("0"),
            resolution_level=None,
            sources_queried=[],
        )

    def _compute_result(
        self,
        entries: list,
        item: SpecificationItem,
        currency: str,
        method: PricingMethod,
        confidence: Confidence,
        match_path: str | None,
        fallback_reason: str | None,
        unit_converted: bool,
        original_unit: str | None,
        resolution_level: str | None = None,
    ) -> PricingResult:
        prices = [e.unit_price for e in entries]
        avg_price = sum(prices) / len(prices)
        line_total = avg_price * item.quantity

        # Use currency from entries if available, else use requested currency
        result_currency = entries[0].currency if entries else currency

        # Convert currency if provider returned a different currency
        if result_currency != currency:
            converted = _convert_currency(avg_price, result_currency, currency)
            if converted is not None:
                avg_price = converted
                line_total = avg_price * item.quantity
                result_currency = currency

        return PricingResult(
            average_unit_price=avg_price,
            currency=result_currency,
            price_unit=item.unit,
            sources_count=len(entries),
            min_unit_price=min(prices),
            max_unit_price=max(prices),
            pricing_method=method,
            confidence=confidence,
            match_path=match_path,
            fallback_reason=fallback_reason,
            unit_converted=unit_converted,
            original_unit=original_unit,
            line_total=line_total,
            resolution_level=resolution_level,
            sources_queried=[e.provider_name for e in entries if hasattr(e, "provider_name")],
        )
