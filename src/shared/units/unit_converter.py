from __future__ import annotations

from decimal import Decimal

from src.shared.errors.app_errors import UnitConversionError

UNIT_CONVERSIONS: dict[tuple[str, str], Decimal] = {
    ("kg", "t"): Decimal("0.001"),
    ("t", "kg"): Decimal("1000"),
    ("m3", "l"): Decimal("1000"),
    ("l", "m3"): Decimal("0.001"),
    # Earthwork volumes (average soil loosening factor ~1.2)
    ("m3_solid", "m3_loose"): Decimal("1.2"),
    ("m3_loose", "m3_solid"): Decimal("0.833"),
    ("m3", "m3_solid"): Decimal("1"),
    ("m3_solid", "m3"): Decimal("1"),
    ("m3", "m3_loose"): Decimal("1.2"),
    ("m3_loose", "m3"): Decimal("0.833"),
}


def can_convert(from_unit: str, to_unit: str) -> bool:
    """Check if a conversion between two units is possible."""
    return (from_unit, to_unit) in UNIT_CONVERSIONS


def convert(quantity: Decimal, from_unit: str, to_unit: str) -> Decimal:
    """Convert a quantity from one unit to another.

    Raises UnitConversionError if the conversion is not supported.
    """
    if from_unit == to_unit:
        return quantity

    key = (from_unit, to_unit)
    if key not in UNIT_CONVERSIONS:
        raise UnitConversionError(
            f"Cannot convert from '{from_unit}' to '{to_unit}': no conversion factor defined"
        )

    factor = UNIT_CONVERSIONS[key]
    return quantity * factor


def get_convertible_units(from_unit: str) -> list[str]:
    """Return all units that the given unit can be converted to."""
    return [to_unit for (fu, to_unit) in UNIT_CONVERSIONS if fu == from_unit]
