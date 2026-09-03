"""Explicit middleware stack. Order is deliberate and documented:

1. request ID / correlation
2. security headers
3. trusted proxy/IP handling (inside request-context)
4. CORS (handled by FastAPI CORSMiddleware, registered first so it runs outermost)
5. request size/limits
6. session/auth context (dependency-level, not middleware)
7. audit/log context (request.state + contextvar)
8. error boundary (exception handlers, not middleware)
9. metrics/tracing (in-memory counters; no high-cardinality labels)
"""

from __future__ import annotations

import time
from collections import Counter

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.errors import envelope
from core.request_context import clear_current, new_request_id, normalize_correlation_id, RequestContext, set_current
from core.security import SECURITY_HEADERS, get_client_ip

metrics_counter: Counter = Counter()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        request_id = request_id[:128]
        correlation_id = normalize_correlation_id(request.headers.get("X-Correlation-ID"))
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        finally:
            clear_current()
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            rid = getattr(request.state, "request_id", "unknown")
            return JSONResponse(
                status_code=413,
                content=envelope("request_too_large", "Request is too large.", rid, None),
            )
        return await call_next(request)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Populate server-derived RequestContext (no trust in client identity headers)."""

    def __init__(self, app, trust_forwarded: bool = False, api_version: str = "v1"):
        super().__init__(app)
        self.trust_forwarded = trust_forwarded
        self.api_version = api_version

    async def dispatch(self, request: Request, call_next):
        client_ip = get_client_ip(
            self.trust_forwarded,
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
        )
        # Never trust spoofable identity headers; session resolution happens later.
        for spoofable in ("x-user-id", "x-workspace-id", "x-tenant-id"):
            if spoofable in request.headers:
                pass  # deliberately ignored
        ctx = RequestContext(
            request_id=getattr(request.state, "request_id", new_request_id()),
            correlation_id=getattr(request.state, "correlation_id", normalize_correlation_id(None)),
            route=request.url.path,
            api_version=self.api_version,
            client_ip=client_ip,
            user_agent=(request.headers.get("user-agent") or "")[:256] or None,
        )
        set_current(ctx)
        request.state.request_context = ctx
        return await call_next(request)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            metrics_counter["http_errors_total"] += 1
            raise
        duration_ms = (time.monotonic() - start) * 1000
        metrics_counter["http_requests_total"] += 1
        metrics_counter[f"http_status_{status // 100}xx"] += 1
        if status in (401, 403):
            metrics_counter["http_auth_denied_total"] += 1
        # Low-cardinality only: no user IDs, no raw paths in labels.
        request.state.duration_ms = duration_ms
        return response
