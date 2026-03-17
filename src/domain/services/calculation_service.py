from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog

from src.domain.interfaces.price_provider import PriceProvider
from src.domain.models.region import Region
from src.domain.models.specification_item import SpecificationItem
from src.domain.services.aggregation_service import aggregate_results
from src.domain.services.normalization_service import (
    normalize_currency,
    normalize_region_codes,
    normalize_unit,
)
from src.domain.services.pricing_service import PricingService
from src.infrastructure.repositories.calculation_repository import CalculationRepository
from src.shared.errors.app_errors import AppError, TtlExpiredError

logger = structlog.get_logger(__name__)


def _is_expired(dt: datetime) -> bool:
    """Check if a datetime has passed, handling both naive and aware datetimes."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        # SQLite returns naive datetimes; treat as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return now > dt


PIPELINE_STEPS = [
    "validating_input",
    "normalizing_units",
    "resolving_region",
    "pricing_material_items",
    "pricing_work_items",
    "aggregating_totals",
    "finalizing_result",
]


class CalculationService:
    def __init__(
        self,
        repository: CalculationRepository,
        price_provider: PriceProvider,
    ) -> None:
        self.repository = repository
        self.pricing_service = PricingService(price_provider)

    async def run_pipeline(self, calculation_id: str) -> None:
        """Execute the full calculation pipeline."""
        job = await self.repository.get_job(calculation_id)
        if job is None:
            logger.error("job_not_found", calculation_id=calculation_id)
            return

        total_steps = len(PIPELINE_STEPS)

        async def update_step(step_name: str, step_idx: int) -> None:
            progress = int((step_idx / total_steps) * 100)
            await self.repository.update_progress(
                calculation_id,
                progress_percent=progress,
                processed_items=0,
                total_items=0,
                current_step=step_name,
            )

        async def check_cancel() -> bool:
            current = await self.repository.get_job(calculation_id)
            if current and current.cancel_requested:
                now = datetime.now(timezone.utc)
                await self.repository.update_status(
                    calculation_id,
                    "cancelled",
                    cancelled_at=now,
                    locked_by=None,
                    locked_at=None,
                )
                return True
            return False

        try:
            payload = job.input_payload

            # Step 0: Check TTL
            if job.expires_at is not None and _is_expired(job.expires_at):
                raise TtlExpiredError("Calculation TTL expired before processing started")


            # Step 1: validating_input
            await update_step("validating_input", 0)
            await self.repository.update_heartbeat(calculation_id)
            if await check_cancel():
                return

            # Step 2: normalizing_units
            await update_step("normalizing_units", 1)
            items_data = payload.get("items", [])
            currency = payload.get("currency", "RUB")
            currency = normalize_currency(currency)

            normalized_items: list[SpecificationItem] = []
            for item_data in items_data:
                raw_unit = item_data.get("unit", "pcs")
                norm_unit = normalize_unit(raw_unit)
                normalized_items.append(
                    SpecificationItem(
                        id=item_data["id"],
                        kind=item_data["kind"],
                        code=item_data["code"],
                        name=item_data["name"],
                        quantity=Decimal(str(item_data["quantity"])),
                        unit=norm_unit,
                        category=item_data.get("category", ""),
                        metadata=item_data.get("metadata"),
                    )
                )

            await self.repository.update_heartbeat(calculation_id)
            if await check_cancel():
                return

            # Step 3: resolving_region
            await update_step("resolving_region", 2)
            region_data = payload.get("region", {})
            country_code, region_code = normalize_region_codes(
                region_data.get("country_code", ""),
                region_data.get("region_code", ""),
            )
            region = Region(
                country_code=country_code,
                region_code=region_code,
                city=region_data.get("city"),
            )

            await self.repository.update_heartbeat(calculation_id)
            if await check_cancel():
                return

            # Step 4: pricing_material_items
            await update_step("pricing_material_items", 3)
            material_items = [i for i in normalized_items if i.kind == "material"]
            material_results: list[dict[str, Any]] = []

            for idx, item in enumerate(material_items):
                pricing_result = await self.pricing_service.price_item(item, region, currency)
                material_results.append(_build_priced_item(item, pricing_result))
                await self.repository.update_progress(
                    calculation_id,
                    progress_percent=int(30 + (idx + 1) / max(len(material_items), 1) * 25),
                    processed_items=idx + 1,
                    total_items=len(material_items),
                    current_step="pricing_material_items",
                )

            await self.repository.update_heartbeat(calculation_id)
            if await check_cancel():
                return

            # Step 5: pricing_work_items
            await update_step("pricing_work_items", 4)
            work_items = [i for i in normalized_items if i.kind == "work"]
            work_results: list[dict[str, Any]] = []

            for idx, item in enumerate(work_items):
                pricing_result = await self.pricing_service.price_item(item, region, currency)
                work_results.append(_build_priced_item(item, pricing_result))
                await self.repository.update_progress(
                    calculation_id,
                    progress_percent=int(55 + (idx + 1) / max(len(work_items), 1) * 25),
                    processed_items=idx + 1,
                    total_items=len(work_items),
                    current_step="pricing_work_items",
                )

            await self.repository.update_heartbeat(calculation_id)
            if await check_cancel():
                return

            # Step 6: aggregating_totals
            await update_step("aggregating_totals", 5)
            all_priced = material_results + work_results
            summary_data = aggregate_results(all_priced)

            await self.repository.update_heartbeat(calculation_id)
            if await check_cancel():
                return

            # Step 7: finalizing_result
            await update_step("finalizing_result", 6)

            summary = {
                "grand_total": float(summary_data.grand_total),
                "materials_total": float(summary_data.materials_total),
                "works_total": float(summary_data.works_total),
                "currency": summary_data.currency or currency,
                "total_items": summary_data.total_items,
                "priced_items": summary_data.priced_items,
                "fallback_items": summary_data.fallback_items,
                "unpriced_items": summary_data.unpriced_items,
            }

            assumptions: list[dict[str, Any]] = []
            for item in all_priced:
                pricing = item.get("pricing", {})
                if pricing.get("pricing_method") != "exact_match":
                    assumptions.append(
                        {
                            "item_id": item["id"],
                            "method": pricing.get("pricing_method"),
                            "reason": pricing.get("fallback_reason"),
                            "confidence": pricing.get("confidence"),
                        }
                    )

            await self.repository.save_result(
                calculation_id=calculation_id,
                summary=summary,
                items=all_priced,
                assumptions=assumptions,
                diagnostics={
                    "pipeline_steps": PIPELINE_STEPS,
                    "region": {
                        "country_code": region.country_code,
                        "region_code": region.region_code,
                        "city": region.city,
                    },
                },
            )

            logger.info("calculation_completed", calculation_id=calculation_id, summary=summary)

        except Exception as exc:
            logger.error(
                "calculation_failed",
                calculation_id=calculation_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            error_code = getattr(exc, "error_code", "UNKNOWN_ERROR")
            now = datetime.now(timezone.utc)
            await self.repository.update_status(
                calculation_id,
                "failed",
                error_code=error_code,
                error_message=str(exc),
                failed_at=now,
                locked_by=None,
                locked_at=None,
            )
            raise


def _build_priced_item(item: SpecificationItem, pricing_result: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "code": item.code,
        "name": item.name,
        "quantity": float(item.quantity),
        "unit": item.unit,
        "pricing": {
            "average_unit_price": float(pricing_result.average_unit_price),
            "currency": pricing_result.currency,
            "price_unit": pricing_result.price_unit,
            "sources_count": pricing_result.sources_count,
            "min_unit_price": float(pricing_result.min_unit_price) if pricing_result.min_unit_price is not None else None,
            "max_unit_price": float(pricing_result.max_unit_price) if pricing_result.max_unit_price is not None else None,
            "pricing_method": pricing_result.pricing_method,
            "confidence": pricing_result.confidence,
            "match_path": pricing_result.match_path,
            "fallback_reason": pricing_result.fallback_reason,
            "unit_converted": pricing_result.unit_converted,
            "original_unit": pricing_result.original_unit,
        },
        "totals": {
            "line_total": float(pricing_result.line_total),
        },
    }
