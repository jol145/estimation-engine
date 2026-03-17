from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.base import AsyncSessionLocal
from src.infrastructure.providers.static_price_provider import StaticPriceProvider
from src.infrastructure.repositories.calculation_repository import CalculationRepository


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_repository(
    session: AsyncSession = Depends(get_db_session),
) -> CalculationRepository:
    return CalculationRepository(session)


async def get_price_provider(
    session: AsyncSession = Depends(get_db_session),
) -> StaticPriceProvider:
    return StaticPriceProvider(session)
