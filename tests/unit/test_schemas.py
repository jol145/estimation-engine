from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.schemas.calculation_input import CalculationRequest, RegionInput, SpecificationItemInput


def make_valid_request_data() -> dict:
    return {
        "region": {
            "country_code": "RU",
            "region_code": "RU-MOW",
            "city": "Moscow",
        },
        "currency": "RUB",
        "items": [
            {
                "id": "item-1",
                "kind": "material",
                "code": "concrete_b25",
                "name": "Concrete B25",
                "quantity": 10.0,
                "unit": "m3",
                "category": "concrete",
            }
        ],
    }


def test_valid_calculation_request():
    data = make_valid_request_data()
    req = CalculationRequest(**data)
    assert req.currency == "RUB"
    assert len(req.items) == 1
    assert req.items[0].id == "item-1"


def test_empty_items_raises_validation_error():
    data = make_valid_request_data()
    data["items"] = []
    with pytest.raises(ValidationError) as exc_info:
        CalculationRequest(**data)
    assert "items" in str(exc_info.value).lower() or "min_length" in str(exc_info.value).lower()


def test_quantity_zero_raises_validation_error():
    data = make_valid_request_data()
    data["items"][0]["quantity"] = 0
    with pytest.raises(ValidationError):
        CalculationRequest(**data)


def test_quantity_negative_raises_validation_error():
    data = make_valid_request_data()
    data["items"][0]["quantity"] = -5.0
    with pytest.raises(ValidationError):
        CalculationRequest(**data)


def test_duplicate_item_ids_raises_validation_error():
    data = make_valid_request_data()
    data["items"] = [
        {
            "id": "item-1",
            "kind": "material",
            "code": "concrete_b25",
            "name": "Concrete B25",
            "quantity": 10.0,
            "unit": "m3",
            "category": "concrete",
        },
        {
            "id": "item-1",  # duplicate
            "kind": "work",
            "code": "masonry_work",
            "name": "Masonry Work",
            "quantity": 5.0,
            "unit": "m2",
            "category": "masonry",
        },
    ]
    with pytest.raises(ValidationError) as exc_info:
        CalculationRequest(**data)
    assert "duplicate" in str(exc_info.value).lower()


def test_items_over_500_raises_validation_error():
    data = make_valid_request_data()
    data["items"] = [
        {
            "id": f"item-{i}",
            "kind": "material",
            "code": f"code-{i}",
            "name": f"Item {i}",
            "quantity": 1.0,
            "unit": "pcs",
            "category": "test",
        }
        for i in range(501)
    ]
    with pytest.raises(ValidationError) as exc_info:
        CalculationRequest(**data)
    assert "500" in str(exc_info.value)


def test_region_country_code_too_short():
    with pytest.raises(ValidationError):
        RegionInput(country_code="R", region_code="RU-MOW")


def test_region_country_code_too_long():
    with pytest.raises(ValidationError):
        RegionInput(country_code="RUS", region_code="RU-MOW")


def test_valid_item_kinds():
    item_material = SpecificationItemInput(
        id="m1", kind="material", code="code1", name="Item",
        quantity=1.0, unit="pcs", category="cat"
    )
    assert item_material.kind == "material"

    item_work = SpecificationItemInput(
        id="w1", kind="work", code="code1", name="Item",
        quantity=1.0, unit="pcs", category="cat"
    )
    assert item_work.kind == "work"


def test_invalid_item_kind():
    with pytest.raises(ValidationError):
        SpecificationItemInput(
            id="x1", kind="invalid", code="code1", name="Item",
            quantity=1.0, unit="pcs", category="cat"
        )
