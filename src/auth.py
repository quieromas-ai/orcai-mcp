from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import settings


class BearerTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Health check is always public
        if request.url.path in ("/health",):
            return await call_next(request)

        if settings.mcp_auth_disabled or not settings.mcp_auth_token:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return Response(
                content='{"detail":"Missing or invalid Authorization header"}',
                status_code=401,
                media_type="application/json",
            )

        token = auth_header.removeprefix("Bearer ").strip()
        if token != settings.mcp_auth_token:
            return Response(
                content='{"detail":"Invalid bearer token"}',
                status_code=401,
                media_type="application/json",
            )

        return await call_next(request)
