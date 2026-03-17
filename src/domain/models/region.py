from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Region:
    country_code: str
    region_code: str
    city: str | None = None

    def __post_init__(self) -> None:
        self.country_code = self.country_code.upper()
        self.region_code = self.region_code.upper()
