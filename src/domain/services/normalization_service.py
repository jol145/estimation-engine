from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from src.shared.errors.app_errors import ValidationError
from src.shared.units.canonical_units import CANONICAL_UNITS, UNIT_ALIASES

logger = structlog.get_logger(__name__)

VALID_CURRENCIES = {
    "RUB", "USD", "EUR", "GBP", "CNY", "JPY", "CHF", "CAD", "AUD", "SEK", "NOK", "DKK",
    "PLN", "CZK", "HUF", "RON", "BGN", "HRK", "TRY", "UAH", "KZT", "BYN",
}


def normalize_unit(unit: str) -> str:
    """Normalize a unit string to its canonical form.

    Raises ValidationError if the unit is not recognized.
    """
    unit_lower = unit.lower().strip()

    # Check if already canonical
    if unit_lower in CANONICAL_UNITS:
        return unit_lower

    # Check aliases
    if unit_lower in UNIT_ALIASES:
        return UNIT_ALIASES[unit_lower]

    # Also check original casing in canonical units
    if unit in CANONICAL_UNITS:
        return unit

    raise ValidationError(
        f"Unknown unit '{unit}'. Supported units: {', '.join(sorted(CANONICAL_UNITS))} "
        f"and their aliases."
    )


def normalize_currency(currency: str) -> str:
    """Normalize and validate currency code.

    Raises ValidationError for unsupported currencies.
    """
    currency_upper = currency.upper().strip()
    if currency_upper not in VALID_CURRENCIES:
        raise ValidationError(
            f"Unsupported currency '{currency}'. "
            f"Supported currencies: {', '.join(sorted(VALID_CURRENCIES))}"
        )
    return currency_upper


def normalize_region_codes(country_code: str, region_code: str) -> tuple[str, str]:
    """Normalize region codes to uppercase."""
    return country_code.upper().strip(), region_code.upper().strip()
