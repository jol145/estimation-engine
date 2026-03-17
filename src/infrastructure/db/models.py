from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.infrastructure.db.base import Base


class CalculationJob(Base):
    __tablename__ = "calculation_jobs"

    id = Column(Text, primary_key=True)
    idempotency_key = Column(Text, unique=True, nullable=True)
    celery_task_id = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="queued")
    progress_percent = Column(Integer, default=0)
    processed_items = Column(Integer, default=0)
    total_items = Column(Integer, default=0)
    current_step = Column(Text, nullable=True)
    input_payload = Column(JSONB, nullable=False)
    cancel_requested = Column(Boolean, default=False)
    locked_by = Column(Text, nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    error_code = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, default=0)


class CalculationResult(Base):
    __tablename__ = "calculation_results"

    calculation_id = Column(Text, ForeignKey("calculation_jobs.id"), primary_key=True)
    summary = Column(JSONB, nullable=False)
    items = Column(JSONB, nullable=False)
    assumptions = Column(JSONB, nullable=False)
    diagnostics = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PriceCatalog(Base):
    __tablename__ = "price_catalog"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)
    unit = Column(Text, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    currency = Column(Text, nullable=False)
    country_code = Column(Text, nullable=False)
    region_code = Column(Text, nullable=True)
    city = Column(Text, nullable=True)
    provider_name = Column(Text, nullable=False)
    category = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_price_code_kind_region", "code", "kind", "country_code", "region_code"),
        Index("ix_price_code_kind_country", "code", "kind", "country_code"),
        Index("ix_price_category", "category", "kind", "country_code", "region_code"),
    )
