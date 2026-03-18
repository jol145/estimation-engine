from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class PricingInfoOutput(BaseModel):
    average_unit_price: float
    currency: str
    price_unit: str
    sources_count: int
    min_unit_price: float | None = None
    max_unit_price: float | None = None
    pricing_method: Literal[
        "exact_match",
        "country_fallback",
        "unit_conversion",
        "category_fallback",
        "coefficient_fallback",
        "unpriced",
        "requires_manual_review",
    ]
    confidence: Literal["high", "medium", "low", "none"]
    match_path: str | None = None
    fallback_reason: str | None = None
    unit_converted: bool = False
    original_unit: str | None = None
    resolution_level: str | None = None
    sources_queried: list[str] | None = None


class TotalsOutput(BaseModel):
    line_total: float


class PricedItemOutput(BaseModel):
    id: str
    kind: Literal["material", "work"]
    code: str
    name: str
    quantity: float
    unit: str
    pricing: PricingInfoOutput
    totals: TotalsOutput


class SummaryOutput(BaseModel):
    grand_total: float
    materials_total: float
    works_total: float
    currency: str
    total_items: int
    priced_items: int
    fallback_items: int
    unpriced_items: int


class CalculationJobResponse(BaseModel):
    calculation_id: str
    status: str
    progress_percent: int = 0
    processed_items: int = 0
    total_items: int = 0
    current_step: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    failed_at: datetime | None = None


class CalculationResultResponse(BaseModel):
    calculation_id: str
    status: str
    summary: SummaryOutput | None = None
    items: list[PricedItemOutput] | None = None
    region: dict | None = None
    currency: str | None = None
    assumptions: list[str] | None = None
    diagnostics: dict[str, Any] | None = None
    progress_percent: int = 0
    current_step: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    failed_at: datetime | None = None


class CalculationStatusResponse(BaseModel):
    calculation_id: str
    status: str
    progress_percent: int = 0
    current_step: str | None = None
    error_code: str | None = None
