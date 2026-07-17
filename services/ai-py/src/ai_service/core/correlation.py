"""Correlation ID middleware for internal AI requests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response

CorrelationIDHeader = "X-Correlation-ID"


def install_correlation_middleware(app: FastAPI) -> None:
    """Ensure every request/response carries a stable correlation ID."""

    @app.middleware("http")
    async def correlation_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(CorrelationIDHeader, "").strip()
        correlation_id = incoming or uuid4().hex
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[CorrelationIDHeader] = correlation_id
        return response
