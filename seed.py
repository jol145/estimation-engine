"""Seed script to populate price_catalog with sample data for Moscow (RU-MOW).

Each item gets 3-6 entries with ±15% price variation.
Also adds country-level (RU) entries with empty region_code.

Usage:
    python seed.py
"""
from __future__ import annotations

import asyncio
import random
from decimal import Decimal
from typing import Any

SEED_ITEMS = [
    # (code, kind, unit, base_price, category)
    ("aerated_concrete_block_300_d500", "material", "m3", 8200, "masonry"),
    ("thin_joint_mortar", "material", "kg", 18, "masonry"),
    ("rebar_d12", "material", "kg", 95, "steel"),
    ("rebar_d12", "material", "t", 95000, "steel"),
    ("concrete_b25", "material", "m3", 6500, "concrete"),
    ("insulation_mineral_wool_100", "material", "m2", 650, "insulation"),
    ("metal_roofing_sheet", "material", "m2", 850, "roofing"),
    ("waterproofing_membrane", "material", "m2", 320, "waterproofing"),
    ("window_block_pvc", "material", "pcs", 18500, "windows"),
    ("door_block_interior", "material", "pcs", 7200, "doors"),
    ("block_masonry", "work", "m2", 2100, "masonry"),
    ("foundation_concrete_work", "work", "m3", 4500, "foundation"),
    ("plastering_work", "work", "m2", 850, "finishing"),
    ("painting_work", "work", "m2", 450, "finishing"),
    ("electrical_installation", "work", "m2", 1200, "electrical"),
    ("plumbing_work", "work", "pcs", 3800, "plumbing"),
    ("material_delivery", "work", "t", 4500, "delivery"),
    ("crane_rental", "work", "shift", 35000, "equipment"),
    ("formwork_rental", "work", "m2", 280, "formwork"),
    ("temp_construction_fence", "work", "m", 1100, "site_preparation"),
    ("architectural_design", "work", "m2", 1800, "design"),
    ("construction_supervision", "work", "m2", 600, "supervision"),
    # --- earthwork materials ---
    ("sand_construction", "material", "m3", 1200, "earthwork"),
    ("crushed_stone_20_40", "material", "m3", 2100, "earthwork"),
    ("soil_fertile", "material", "m3", 1500, "earthwork"),
    ("geotextile_200", "material", "m2", 65, "earthwork"),
    # --- delivery ---
    ("material_delivery_trip", "work", "trip", 12000, "delivery"),
    ("material_delivery_distance", "work", "t_km", 35, "delivery"),
    ("concrete_pump_delivery", "work", "trip", 25000, "delivery"),
    ("crane_delivery", "work", "trip", 45000, "delivery"),
    ("small_cargo_delivery", "work", "trip", 5500, "delivery"),
    ("debris_removal", "work", "trip", 8500, "delivery"),
    ("debris_removal_volume", "work", "m3", 650, "delivery"),
    # --- earthwork ---
    ("excavation_mechanical", "work", "m3", 450, "earthwork"),
    ("excavation_manual", "work", "m3", 1800, "earthwork"),
    ("excavation_rock", "work", "m3", 3500, "earthwork"),
    ("trench_excavation", "work", "m3", 550, "earthwork"),
    ("backfill_compaction", "work", "m3", 380, "earthwork"),
    ("grading_leveling", "work", "m2", 120, "earthwork"),
    ("soil_removal_offsite", "work", "m3", 900, "earthwork"),
    ("soil_removal_offsite_trip", "work", "trip", 9500, "earthwork"),
    ("pit_excavation", "work", "m3", 500, "earthwork"),
    ("pile_driving", "work", "m", 2800, "earthwork"),
    ("drainage_trench", "work", "m", 1600, "earthwork"),
    ("dewatering", "work", "machine_hour", 2500, "earthwork"),
    # --- equipment rental ---
    ("excavator_rental", "work", "machine_hour", 3500, "equipment"),
    ("bulldozer_rental", "work", "machine_hour", 3200, "equipment"),
    ("concrete_pump_rental", "work", "machine_hour", 4500, "equipment"),
]

PROVIDERS = ["provider_a", "provider_b", "provider_c", "provider_d", "provider_e", "provider_f"]


def generate_prices(
    code: str,
    kind: str,
    unit: str,
    base_price: float,
    category: str,
    country_code: str,
    region_code: str | None,
    num_entries: int,
) -> list[dict[str, Any]]:
    """Generate price entries with ±15% variation."""
    entries = []
    for i in range(num_entries):
        variation = random.uniform(0.85, 1.15)
        price = round(base_price * variation, 2)
        entries.append(
            {
                "code": code,
                "kind": kind,
                "unit": unit,
                "unit_price": price,
                "currency": "RUB",
                "country_code": country_code,
                "region_code": region_code,
                "city": "Moscow" if region_code == "RU-MOW" else None,
                "provider_name": PROVIDERS[i % len(PROVIDERS)],
                "category": category,
            }
        )
    return entries


async def seed_database() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from src.config import settings
    from src.infrastructure.db.models import PriceCatalog

    engine = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    all_entries: list[dict[str, Any]] = []

    for code, kind, unit, base_price, category in SEED_ITEMS:
        # Regional entries (RU-MOW): 3-6 entries
        num_regional = random.randint(3, 6)
        regional_entries = generate_prices(
            code, kind, unit, base_price, category, "RU", "RU-MOW", num_regional
        )
        all_entries.extend(regional_entries)

        # Country-level entries (RU, no region): 2-4 entries
        num_country = random.randint(2, 4)
        country_entries = generate_prices(
            code, kind, unit, base_price, category, "RU", None, num_country
        )
        all_entries.extend(country_entries)

    async with SessionLocal() as session:
        # Clear existing data
        from sqlalchemy import delete
        await session.execute(delete(PriceCatalog))
        await session.commit()

        # Insert new data
        for entry_data in all_entries:
            entry = PriceCatalog(**entry_data)
            session.add(entry)

        await session.commit()
        print(f"Seeded {len(all_entries)} price entries")

    await engine.dispose()


if __name__ == "__main__":
    random.seed(42)  # Deterministic seed
    asyncio.run(seed_database())
