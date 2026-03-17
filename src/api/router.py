from __future__ import annotations

from fastapi import APIRouter

from src.api.routes.calculations import router as calculations_router

api_router = APIRouter()
api_router.include_router(calculations_router)
