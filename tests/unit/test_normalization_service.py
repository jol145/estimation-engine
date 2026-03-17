from __future__ import annotations

import pytest

from src.domain.services.normalization_service import (
    normalize_currency,
    normalize_region_codes,
    normalize_unit,
)
from src.shared.errors.app_errors import ValidationError


def test_canonical_unit_passthrough():
    assert normalize_unit("pcs") == "pcs"
    assert normalize_unit("m") == "m"
    assert normalize_unit("m2") == "m2"
    assert normalize_unit("m3") == "m3"
    assert normalize_unit("kg") == "kg"
    assert normalize_unit("t") == "t"
    assert normalize_unit("l") == "l"


def test_alias_normalization_russian_kg():
    assert normalize_unit("кг") == "kg"


def test_alias_normalization_piece():
    assert normalize_unit("piece") == "pcs"
    assert normalize_unit("pieces") == "pcs"
    assert normalize_unit("шт") == "pcs"


def test_alias_normalization_meter():
    assert normalize_unit("meter") == "m"
    assert normalize_unit("м") == "m"


def test_alias_normalization_sqm():
    assert normalize_unit("sq.m") == "m2"
    assert normalize_unit("sqm") == "m2"
    assert normalize_unit("м2") == "m2"


def test_alias_normalization_cum():
    assert normalize_unit("cu.m") == "m3"
    assert normalize_unit("м3") == "m3"


def test_alias_normalization_ton():
    assert normalize_unit("ton") == "t"
    assert normalize_unit("тонна") == "t"
    assert normalize_unit("т") == "t"


def test_invalid_unit_raises_error():
    with pytest.raises(ValidationError):
        normalize_unit("furlongs")


def test_invalid_unit_unknown_raises_error():
    with pytest.raises(ValidationError):
        normalize_unit("xyz_invalid")


def test_currency_validation_valid():
    assert normalize_currency("RUB") == "RUB"
    assert normalize_currency("USD") == "USD"
    assert normalize_currency("EUR") == "EUR"


def test_currency_validation_lowercase():
    assert normalize_currency("rub") == "RUB"
    assert normalize_currency("usd") == "USD"


def test_currency_validation_invalid():
    with pytest.raises(ValidationError):
        normalize_currency("XYZ")


def test_currency_validation_invalid_short():
    with pytest.raises(ValidationError):
        normalize_currency("ZZZ")


def test_region_normalization_uppercase():
    country, region = normalize_region_codes("ru", "ru-mow")
    assert country == "RU"
    assert region == "RU-MOW"


def test_region_normalization_already_upper():
    country, region = normalize_region_codes("RU", "RU-MOW")
    assert country == "RU"
    assert region == "RU-MOW"


def test_region_normalization_strips_spaces():
    country, region = normalize_region_codes("  RU  ", "  RU-MOW  ")
    assert country == "RU"
    assert region == "RU-MOW"


def test_machine_hour_aliases():
    assert normalize_unit("маш.час") == "machine_hour"
    assert normalize_unit("маш-час") == "machine_hour"
    assert normalize_unit("машино-час") == "machine_hour"
    assert normalize_unit("машиночас") == "machine_hour"
    assert normalize_unit("мч") == "machine_hour"


def test_trip_aliases():
    assert normalize_unit("рейс") == "trip"
    assert normalize_unit("рейсов") == "trip"
    assert normalize_unit("ездка") == "trip"


def test_t_km_aliases():
    assert normalize_unit("т.км") == "t_km"
    assert normalize_unit("ткм") == "t_km"
    assert normalize_unit("тонно-км") == "t_km"


def test_km_aliases():
    assert normalize_unit("км") == "km"
    assert normalize_unit("километр") == "km"


def test_earthwork_volume_aliases():
    assert normalize_unit("м3 рыхл") == "m3_loose"
    assert normalize_unit("м3 в массиве") == "m3_solid"
