from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.middleware.idempotency import IdempotencyMiddleware
from src.api.router import api_router

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Estimation Engine",
        description="Construction cost estimation engine API",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Note: idempotency is handled at the route level via the repo dependency
    # The middleware can be used as an additional layer for non-injected contexts
    app.add_middleware(IdempotencyMiddleware)

    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
