from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal


@dataclass
class SpecificationItem:
    id: str
    kind: Literal["material", "work"]
    code: str
    name: str
    quantity: Decimal
    unit: str
    category: str
    metadata: dict[str, Any] | None = None
