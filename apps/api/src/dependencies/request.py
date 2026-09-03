"""Request-scoped dependency for RequestContext."""

from __future__ import annotations

from fastapi import Request

from core.errors import ApiError
from core.request_context import RequestContext


async def get_request_context(request: Request) -> RequestContext:
    ctx = getattr(request.state, "request_context", None)
    if ctx is None:
        raise ApiError("internal_error")
    return ctx
