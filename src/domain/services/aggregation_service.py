from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class AggregationSummary:
    grand_total: Decimal
    materials_total: Decimal
    works_total: Decimal
    currency: str
    total_items: int
    priced_items: int
    fallback_items: int
    unpriced_items: int


def aggregate_results(priced_items: list[dict[str, Any]]) -> AggregationSummary:
    """Aggregate pricing results into summary totals."""
    materials_total = Decimal("0")
    works_total = Decimal("0")
    priced_count = 0
    fallback_count = 0
    unpriced_count = 0
    currency = ""

    for item in priced_items:
        pricing = item.get("pricing", {})
        totals = item.get("totals", {})
        line_total = Decimal(str(totals.get("line_total", 0)))
        confidence = pricing.get("confidence", "none")
        pricing_method = pricing.get("pricing_method", "unpriced")
        kind = item.get("kind", "material")

        if not currency and pricing.get("currency"):
            currency = pricing["currency"]

        if pricing_method == "unpriced":
            unpriced_count += 1
        elif confidence == "high":
            priced_count += 1
        else:
            fallback_count += 1
            priced_count += 1  # still has a price

        if kind == "material":
            materials_total += line_total
        else:
            works_total += line_total

    grand_total = materials_total + works_total

    return AggregationSummary(
        grand_total=grand_total,
        materials_total=materials_total,
        works_total=works_total,
        currency=currency,
        total_items=len(priced_items),
        priced_items=priced_count,
        fallback_items=fallback_count,
        unpriced_items=unpriced_count,
    )
