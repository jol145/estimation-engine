from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RegionInput(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=2)
    region_code: str = Field(..., min_length=1)
    city: str | None = None


class SpecificationItemInput(BaseModel):
    id: str = Field(..., min_length=1)
    kind: Literal["material", "work"]
    code: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)
    unit: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    metadata: dict[str, Any] | None = None

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, v: str) -> str:
        from src.shared.units.canonical_units import CANONICAL_UNITS, UNIT_ALIASES
        unit_lower = v.lower().strip()
        if unit_lower in CANONICAL_UNITS or unit_lower in UNIT_ALIASES or v in CANONICAL_UNITS:
            return v
        supported = ", ".join(sorted(CANONICAL_UNITS))
        raise ValueError(
            f"Unsupported unit '{v}'. Supported units: {supported} (and their aliases)."
        )


class CalculationRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
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
                        "code": "aerated_concrete_block_300_d500",
                        "name": "Газобетонный блок D500 300мм",
                        "quantity": 9,
                        "unit": "m3",
                        "category": "masonry",
                    },
                    {
                        "id": "item-2",
                        "kind": "work",
                        "code": "block_masonry",
                        "name": "Кладка газобетонных блоков",
                        "quantity": 30,
                        "unit": "m2",
                        "category": "masonry",
                    },
                ],
            }
        }
    )

    project_id: str | None = None
    source_id: str | None = None
    region: RegionInput
    currency: str = Field(..., min_length=3, max_length=3)
    items: list[SpecificationItemInput] = Field(..., min_length=1)
    request_meta: dict[str, Any] | None = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        from src.domain.services.normalization_service import VALID_CURRENCIES
        if v.upper().strip() not in VALID_CURRENCIES:
            supported = ", ".join(sorted(VALID_CURRENCIES))
            raise ValueError(
                f"Unsupported currency '{v}'. Supported currencies: {supported}"
            )
        return v

    @field_validator("items")
    @classmethod
    def validate_items_count(cls, v: list[SpecificationItemInput]) -> list[SpecificationItemInput]:
        from src.config import settings
        if len(v) > settings.max_items_per_calculation:
            raise ValueError(
                f"Too many items: {len(v)}. Maximum allowed: {settings.max_items_per_calculation}"
            )
        return v

    @model_validator(mode="after")
    def validate_unique_item_ids(self) -> CalculationRequest:
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate item IDs are not allowed")
        return self
