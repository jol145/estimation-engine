from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import settings


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Require X-API-Key header on all routes except /health.

    If no API keys are configured (api_keys=""), authentication is disabled.
    This allows tests and local dev without a key.
    """

    async def dispatch(self, request: Request, call_next):
        allowed_keys = settings.api_keys_list

        # Auth disabled when no keys configured
        if not allowed_keys:
            return await call_next(request)

        # /health is always public
        if request.url.path == "/health":
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key not in allowed_keys:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized: missing or invalid X-API-Key"},
            )

        return await call_next(request)
