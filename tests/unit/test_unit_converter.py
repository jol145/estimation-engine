from __future__ import annotations

import pytest
from decimal import Decimal

from src.shared.units.unit_converter import convert, can_convert
from src.shared.errors.app_errors import UnitConversionError


def test_kg_to_t_conversion():
    result = convert(Decimal("1000"), "kg", "t")
    assert result == Decimal("1")


def test_t_to_kg_conversion():
    result = convert(Decimal("1"), "t", "kg")
    assert result == Decimal("1000")


def test_m3_to_l_conversion():
    result = convert(Decimal("2"), "m3", "l")
    assert result == Decimal("2000")


def test_l_to_m3_conversion():
    result = convert(Decimal("500"), "l", "m3")
    assert result == Decimal("0.5")


def test_impossible_conversion_raises_error():
    with pytest.raises(UnitConversionError):
        convert(Decimal("1"), "m", "kg")


def test_impossible_conversion_pcs_to_m():
    with pytest.raises(UnitConversionError):
        convert(Decimal("5"), "pcs", "m")


def test_same_unit_returns_same_value():
    result = convert(Decimal("42"), "kg", "kg")
    assert result == Decimal("42")


def test_decimal_precision():
    result = convert(Decimal("1"), "kg", "t")
    assert result == Decimal("0.001")


def test_can_convert_returns_true_for_valid():
    assert can_convert("kg", "t") is True
    assert can_convert("t", "kg") is True
    assert can_convert("m3", "l") is True


def test_can_convert_returns_false_for_invalid():
    assert can_convert("m", "kg") is False
    assert can_convert("pcs", "m2") is False


def test_large_quantity_conversion():
    result = convert(Decimal("1000000"), "kg", "t")
    assert result == Decimal("1000")


def test_solid_to_loose_conversion():
    result = convert(Decimal("100"), "m3_solid", "m3_loose")
    assert result == Decimal("120")


def test_loose_to_solid_conversion():
    result = convert(Decimal("120"), "m3_loose", "m3_solid")
    assert result == Decimal("120") * Decimal("0.833")


def test_m3_to_m3_solid_identity():
    result = convert(Decimal("50"), "m3", "m3_solid")
    assert result == Decimal("50")


def test_m3_to_m3_loose():
    result = convert(Decimal("10"), "m3", "m3_loose")
    assert result == Decimal("12")


def test_can_convert_earthwork():
    assert can_convert("m3_solid", "m3_loose") is True
    assert can_convert("m3_loose", "m3_solid") is True
    assert can_convert("m3", "m3_loose") is True


def test_cannot_convert_trip():
    assert can_convert("trip", "t") is False
    assert can_convert("machine_hour", "kg") is False
