"""ASGI policy stack, outside to inside:

metrics -> native server errors -> request IDs -> security headers -> CSRF -> body limits ->
request context/trusted proxy -> CORS -> routed auth dependencies/handlers.
Metrics surrounds FastAPI's native server-error and registered middleware stack.
Metrics observes actual receive/send events without adding task/stream bridges.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter

from fastapi import Request
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

from core.errors import envelope
from core.csrf import csrf_request_is_allowed
from core.request_context import clear_current, get_current, new_request_id, normalize_correlation_id, normalize_request_id, RequestContext, set_current
from core.security import (
    COMPAT_API_KEY_PATHS,
    PUBLIC_ALLOWLIST,
    SECURITY_HEADERS,
    get_client_ip,
    resolve_session_cookie,
)
from core.telemetry import ApiTelemetry
from core.transport import _TransportClosed, all_leaves as _all_leaves, get_transport, is_transport_only

metrics_counter: Counter = Counter()


class RequestTooLarge(Exception):
    """Internal signal used by the streaming request-size guard."""


def is_request_too_large(error: BaseException) -> bool:
    """Recognize only size signals; mixed groups must retain real failures."""
    if isinstance(error, RequestTooLarge):
        return True
    nested = getattr(error, "exceptions", ())
    return bool(nested) and all(is_request_too_large(item) for item in nested)


class HTTPMiddleware:
    """Policy wrappers operate on the ASGI stream without task/queue bridges."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        return await self.handle(scope, receive, send)


class RequestIdMiddleware(HTTPMiddleware):
    async def handle(self, scope, receive, send):
        request = Request(scope, receive)
        request_id = normalize_request_id(request.headers.get("X-Request-ID"))
        correlation_id = normalize_correlation_id(request.headers.get("X-Correlation-ID"))
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        async def with_ids(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Correlation-ID"] = correlation_id
            await send(message)
        await self.app(scope, receive, with_ids)


class SecurityHeadersMiddleware(HTTPMiddleware):
    async def handle(self, scope, receive, send):
        async def with_security(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in SECURITY_HEADERS.items():
                    headers.setdefault(key, value)
            await send(message)
        await self.app(scope, receive, with_security)


class CSRFProtectionMiddleware(HTTPMiddleware):
    """Protect state-changing requests carrying the configured session cookie."""

    def __init__(
        self,
        app,
        *,
        environment: str,
        allowed_origins: tuple[str, ...] = (),
        session_cookie_name: str = "rick_session",
        csrf_token: str = "",
        csrf_header_name: str = "X-CSRF-Token",
    ):
        super().__init__(app)
        self.environment = environment
        self.allowed_origins = tuple(allowed_origins)
        self.session_cookie_name = session_cookie_name
        self.csrf_token = csrf_token
        self.csrf_header_name = csrf_header_name

    async def handle(self, scope, receive, send):
        request = Request(scope, receive)
        route_key = (request.method, request.url.path)
        if route_key in PUBLIC_ALLOWLIST or route_key in COMPAT_API_KEY_PATHS:
            return await self.app(scope, receive, send)
        session_cookie = resolve_session_cookie(request.cookies, self.session_cookie_name)
        allowed = csrf_request_is_allowed(
            method=request.method,
            has_session_cookie=bool(session_cookie),
            environment=self.environment,
            origin=request.headers.get("origin"),
            referer=request.headers.get("referer"),
            presented_token=request.headers.get(self.csrf_header_name),
            configured_token=self.csrf_token,
            allowed_origins=self.allowed_origins,
        )
        if not allowed:
            request_id = getattr(request.state, "request_id", "unknown")
            response = JSONResponse(
                status_code=403,
                content=envelope("forbidden", "CSRF validation failed.", request_id, None),
            )
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


# Short alias keeps the middleware easy to discover for app wiring and tests.
CSRFMiddleware = CSRFProtectionMiddleware


class RequestSizeLimitMiddleware(HTTPMiddleware):
    """Reject requests whose declared body exceeds the selected limit."""

    def __init__(self, app, max_bytes: int, upload_max_bytes: int | None = None):
        super().__init__(app)
        self.max_bytes = max_bytes
        self.upload_max_bytes = upload_max_bytes if upload_max_bytes is not None else max_bytes

    async def handle(self, scope, receive, send):
        request = Request(scope, receive)
        content_length = request.headers.get("content-length")
        content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        limit = self.upload_max_bytes if content_type == "multipart/form-data" else self.max_bytes
        def rejection():
            return JSONResponse(status_code=413, content=envelope(
                "request_too_large", "Request is too large.",
                getattr(request.state, "request_id", "unknown"), None))
        if content_length and content_length.isascii() and content_length.isdigit():
            declared = content_length.lstrip("0") or "0"
            if len(declared) > len(str(limit)) or int(declared) > limit:
                return await rejection()(scope, receive, send)

        # Content-Length is advisory: chunked requests and HTTP/2 streams may
        # omit it. Count the actual bytes before they reach a JSON/multipart
        # parser so the declared limit cannot be bypassed with transfer
        # framing.
        received_bytes = 0
        exceeded = False
        started = False
        rejected = False

        async def bounded_receive():
            nonlocal received_bytes, exceeded
            if exceeded:
                raise RequestTooLarge
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b"") or b"")
                if received_bytes > limit:
                    exceeded = True
                    raise RequestTooLarge
            return message

        async def bounded_send(message):
            nonlocal started, rejected
            if rejected:
                return
            if exceeded and not started:
                rejected = True
                return await rejection()(scope, receive, send)
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, bounded_send)
        except Exception as exc:
            if not is_request_too_large(exc) or started:
                raise
            if not rejected:
                await rejection()(scope, receive, send)


class RequestContextMiddleware(HTTPMiddleware):
    """Populate server-derived RequestContext (no trust in client identity headers)."""

    def __init__(
        self,
        app,
        trust_forwarded: bool = False,
        trusted_proxies: tuple[str, ...] = (),
        api_version: str = "v1",
    ):
        super().__init__(app)
        self.trust_forwarded = trust_forwarded
        self.trusted_proxies = trusted_proxies
        self.api_version = api_version

    async def handle(self, scope, receive, send):
        request = Request(scope, receive)
        client_ip = get_client_ip(
            self.trust_forwarded,
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
            self.trusted_proxies,
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
        previous = get_current()
        set_current(ctx)
        request.state.request_context = ctx
        try:
            await self.app(scope, receive, send)
        finally:
            if previous is None:
                clear_current()
            else:
                set_current(previous)


class MetricsMiddleware(HTTPMiddleware):
    def __init__(self, app, *, telemetry: ApiTelemetry | None = None):
        super().__init__(app)
        self.telemetry = telemetry or ApiTelemetry()

    async def handle(self, scope, receive, send):
        start = time.monotonic()
        status = None
        header_ms = None
        transport = get_transport(scope)
        cancelled = False
        failed = False
        complete = False

        async def observed_receive():
            message = await receive()
            if message["type"] == "http.disconnect":
                transport.disconnect()
            return message

        async def observed_send(message):
            nonlocal status, header_ms, complete
            if message["type"] == "http.response.start":
                status = message["status"]
                header_ms = (time.monotonic() - start) * 1000
            # A known application failure still matters when delivery is no
            # longer possible. Observe intent before suppressing transport I/O.
            if transport.disconnected.is_set():
                return
            try:
                await send(message)
            except OSError as exc:
                transport.disconnect()
                raise _TransportClosed("transport closed") from exc
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True

        try:
            await self.app(scope, observed_receive, observed_send)
            if not complete and not transport.disconnected.is_set():
                raise RuntimeError("ASGI application returned before completing its response")
        except BaseException as exc:
            if is_transport_only(scope, exc):
                pass
            elif _all_leaves(exc, (asyncio.CancelledError,)):
                cancelled = True
                raise
            else:
                failed = True
                raise
        finally:
            disconnected = transport.disconnected.is_set()
            duration_ms = header_ms if header_ms is not None else (time.monotonic() - start) * 1000
            scope.setdefault("state", {})["duration_ms"] = duration_ms
            request_state = scope.get("state") or {}
            request_id = request_state.get("request_id")
            correlation_id = request_state.get("correlation_id")
            service_failed = failed or (status is not None and status >= 500)
            if not service_failed and (disconnected or cancelled):
                reason = "disconnect" if disconnected else "cancellation"
                metrics_counter[f"http_{reason}s_total"] += 1
                self.telemetry.record_abandonment(
                    path=scope["path"], reason=reason,
                    request_id=request_id, correlation_id=correlation_id,
                )
            else:
                recorded_status = status if status is not None else 500
                metrics_counter["http_requests_total"] += 1
                metrics_counter[f"http_status_{recorded_status // 100}xx"] += 1
                if failed or recorded_status >= 500:
                    metrics_counter["http_errors_total"] += 1
                if recorded_status in (401, 403):
                    metrics_counter["http_auth_denied_total"] += 1
                self.telemetry.record_request(method=scope["method"], path=scope["path"],
                    status=recorded_status, duration_ms=duration_ms, failed=failed,
                    request_id=request_id, correlation_id=correlation_id)
