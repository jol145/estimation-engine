from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class CalculationResult:
    calculation_id: str
    summary: dict[str, Any]
    items: list[dict[str, Any]]
    assumptions: list[dict[str, Any]]
    diagnostics: dict[str, Any] | None = None
    created_at: datetime | None = None
