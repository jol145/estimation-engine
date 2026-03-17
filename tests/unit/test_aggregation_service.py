from __future__ import annotations

from decimal import Decimal

import pytest

from src.domain.services.aggregation_service import aggregate_results


def make_priced_item(
    id: str = "item-1",
    kind: str = "material",
    line_total: float = 1000.0,
    pricing_method: str = "exact_match",
    confidence: str = "high",
    currency: str = "RUB",
) -> dict:
    return {
        "id": id,
        "kind": kind,
        "code": "test_code",
        "name": "Test",
        "quantity": 10.0,
        "unit": "pcs",
        "pricing": {
            "average_unit_price": line_total / 10,
            "currency": currency,
            "price_unit": "pcs",
            "sources_count": 1,
            "pricing_method": pricing_method,
            "confidence": confidence,
            "match_path": None,
            "fallback_reason": None,
            "unit_converted": False,
            "original_unit": None,
        },
        "totals": {
            "line_total": line_total,
        },
    }


def test_materials_total_sum():
    items = [
        make_priced_item("m1", "material", 1000.0),
        make_priced_item("m2", "material", 2000.0),
    ]
    result = aggregate_results(items)
    assert result.materials_total == Decimal("3000.0")


def test_works_total_sum():
    items = [
        make_priced_item("w1", "work", 500.0),
        make_priced_item("w2", "work", 750.0),
    ]
    result = aggregate_results(items)
    assert result.works_total == Decimal("1250.0")


def test_grand_total_equals_materials_plus_works():
    items = [
        make_priced_item("m1", "material", 1000.0),
        make_priced_item("w1", "work", 500.0),
    ]
    result = aggregate_results(items)
    assert result.grand_total == result.materials_total + result.works_total
    assert result.grand_total == Decimal("1500.0")


def test_priced_items_count():
    items = [
        make_priced_item("m1", "material", 1000.0, "exact_match", "high"),
        make_priced_item("m2", "material", 2000.0, "country_fallback", "medium"),
        make_priced_item("m3", "material", 0.0, "unpriced", "none"),
    ]
    result = aggregate_results(items)
    assert result.total_items == 3
    assert result.unpriced_items == 1
    assert result.priced_items == 2


def test_fallback_items_count():
    items = [
        make_priced_item("m1", "material", 1000.0, "exact_match", "high"),
        make_priced_item("m2", "material", 800.0, "category_fallback", "low"),
        make_priced_item("m3", "material", 900.0, "country_fallback", "medium"),
    ]
    result = aggregate_results(items)
    assert result.fallback_items == 2
    assert result.priced_items == 3


def test_empty_items():
    result = aggregate_results([])
    assert result.grand_total == Decimal("0")
    assert result.materials_total == Decimal("0")
    assert result.works_total == Decimal("0")
    assert result.total_items == 0
    assert result.unpriced_items == 0


def test_unpriced_zero_total():
    items = [
        make_priced_item("m1", "material", 0.0, "unpriced", "none"),
    ]
    result = aggregate_results(items)
    assert result.grand_total == Decimal("0")
    assert result.unpriced_items == 1
    assert result.priced_items == 0


def test_currency_from_first_item():
    items = [
        make_priced_item("m1", "material", 1000.0, currency="USD"),
    ]
    result = aggregate_results(items)
    assert result.currency == "USD"
