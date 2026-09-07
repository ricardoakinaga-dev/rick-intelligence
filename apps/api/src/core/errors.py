"""Canonical error envelope. Never leaks stack traces, provider bodies, or secrets."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from core.request_context import normalize_correlation_id, normalize_request_id
from core.security import SECURITY_HEADERS
from core.transport import _TransportClosed, is_transport_only

ERROR_CODES = (
    "validation_error",
    "unauthorized",
    "forbidden",
    "not_found",
    "conflict",
    "rate_limited",
    "request_too_large",
    "unsupported_media_type",
    "provider_timeout",
    "provider_unavailable",
    "provider_rate_limit",
    "vector_store_unavailable",
    "storage_unavailable",
    "recovery_required",
    "lock_unavailable",
    "ingestion_failed",
    "retrieval_failed",
    "generation_failed",
    "internal_error",
)

_STATUS_BY_CODE = {
    "validation_error": 400,
    "unauthorized": 401,
    "forbidden": 403,
    "not_found": 404,
    "conflict": 409,
    "rate_limited": 429,
    "request_too_large": 413,
    "unsupported_media_type": 415,
    "provider_timeout": 504,
    "provider_unavailable": 503,
    "provider_rate_limit": 429,
    "vector_store_unavailable": 503,
    "storage_unavailable": 503,
    "recovery_required": 503,
    "lock_unavailable": 503,
    "ingestion_failed": 500,
    "retrieval_failed": 500,
    "generation_failed": 500,
    "internal_error": 500,
}

_SAFE_MESSAGES = {
    "validation_error": "Request validation failed.",
    "unauthorized": "Authentication required.",
    "forbidden": "Action is not permitted.",
    "not_found": "Resource not found.",
    "conflict": "Resource conflict.",
    "rate_limited": "Too many requests.",
    "request_too_large": "Request is too large.",
    "unsupported_media_type": "Unsupported media type.",
    "provider_timeout": "Provider timed out.",
    "provider_unavailable": "Provider is unavailable.",
    "provider_rate_limit": "Provider rate limit exceeded.",
    "vector_store_unavailable": "Vector store is unavailable.",
    "storage_unavailable": "Storage is unavailable.",
    "recovery_required": "Ingestion recovery requires operator attention.",
    "lock_unavailable": "Lock service is unavailable.",
    "ingestion_failed": "Ingestion failed.",
    "retrieval_failed": "Retrieval failed.",
    "generation_failed": "Generation failed.",
    "internal_error": "Internal server error.",
}

_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9\-_:.]{1,128}$")
_SAFE_DETAIL_TEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/\[\] ',-]{0,127}$")
_SAFE_DETAIL_KEYS = frozenset({"error", "tenant_id", "user_id", "workspace_id", "fields"})


class ApiError(Exception):
    def __init__(self, code: str, message: str | None = None, details: Any = None):
        if code not in ERROR_CODES:
            raise ValueError(f"Unknown error code: {code}")
        super().__init__(message or code)
        self.code = code
        self.message = message or _SAFE_MESSAGES[code]
        self.details = details

    @property
    def status_code(self) -> int:
        return _STATUS_BY_CODE[self.code]


def _safe_details(details: Any) -> dict[str, Any] | None:
    if not isinstance(details, Mapping):
        return None
    result: dict[str, Any] = {}
    for key, value in details.items():
        if key not in _SAFE_DETAIL_KEYS:
            continue
        if key == "fields":
            if not isinstance(value, (list, tuple)):
                continue
            fields = [
                item.strip()
                for item in value[:20]
                if isinstance(item, str)
                and len(item.strip()) <= 128
                and _SAFE_DETAIL_TEXT_RE.fullmatch(item.strip())
            ]
            if fields:
                result[key] = fields
            continue
        if key == "error":
            if isinstance(value, str) and value in ERROR_CODES:
                result[key] = value
            continue
        if isinstance(value, str) and _SAFE_DETAIL_TEXT_RE.fullmatch(value.strip()):
            result[key] = value.strip()
    return result or None


def envelope(code: str, message: str, request_id: str, details: Any = None) -> dict:
    safe_code = code if code in ERROR_CODES else "internal_error"
    safe_request_id = request_id if isinstance(request_id, str) and _SAFE_REQUEST_ID_RE.fullmatch(request_id) else "unknown"
    # ``message`` is deliberately ignored at the HTTP boundary. Internal
    # exceptions may carry provider text; only the canonical code message is
    # allowed to cross the public API.
    return {
        "error": {
            "code": safe_code,
            "message": _SAFE_MESSAGES[safe_code],
            "request_id": safe_request_id,
            "details": _safe_details(details),
        }
    }


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _legacy_detail_to_code(detail: Any, status: int) -> tuple[str, Any]:
    """Map legacy HTTPException details to canonical codes without leaking internals."""
    code = "internal_error"
    if status == 400:
        code = "validation_error"
    elif status == 401:
        code = "unauthorized"
    elif status == 403:
        code = "forbidden"
    elif status == 404:
        code = "not_found"
    elif status == 409:
        code = "conflict"
    elif status == 413:
        code = "request_too_large"
    elif status == 415:
        code = "unsupported_media_type"
    elif status == 429:
        code = "rate_limited"
    elif status == 503:
        code = "provider_unavailable"
    if isinstance(detail, dict) and isinstance(detail.get("error"), str):
        legacy_code = detail["error"]
        if legacy_code in ERROR_CODES:
            code = legacy_code
        # Never forward legacy message verbatim; use safe message + redacted detail keys only.
        safe_detail = {k: v for k, v in detail.items() if k in {"error", "tenant_id", "user_id", "workspace_id"}}
        return code, safe_detail or None
    return code, None


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    rid = _request_id(request)
    return JSONResponse(status_code=exc.status_code, content=envelope(exc.code, exc.message, rid, exc.details))


async def http_exception_handler(request: Request, exc: HTTPException | StarletteHTTPException) -> JSONResponse:
    rid = _request_id(request)
    code, details = _legacy_detail_to_code(exc.detail, exc.status_code)
    return JSONResponse(status_code=exc.status_code, content=envelope(code, _SAFE_MESSAGES[code], rid, details))


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    rid = _request_id(request)
    # Do not echo raw input values; report locations only.
    locations = sorted({str(err.get("loc", "")) for err in exc.errors()})
    return JSONResponse(status_code=400, content=envelope("validation_error", _SAFE_MESSAGES["validation_error"], rid, {"fields": locations[:20]}))


class _ServerErrorResponse(JSONResponse):
    """Let native ServerErrorMiddleware rethrow the original after transport loss."""

    def __init__(self, original: Exception, **kwargs):
        super().__init__(**kwargs)
        self.original = original

    async def __call__(self, scope, receive, send):
        # No synthetic 500 intent for an observed, transport-only exception.
        if is_transport_only(scope, self.original):
            return
        try:
            await super().__call__(scope, receive, send)
        except _TransportClosed:
            # This marker comes from the actual send observer. Returning lets
            # the native middleware raise the original exception unchanged.
            return
        except BaseException as secondary:
            raise BaseExceptionGroup(
                "application and error response failed", [self.original, secondary]
            ) from None


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # ServerErrorMiddleware renders outside the registered policy wrappers.
    rid = normalize_request_id(_request_id(request))
    correlation = normalize_correlation_id(getattr(request.state, "correlation_id", None))
    return _ServerErrorResponse(exc, status_code=500,
        content=envelope("internal_error", _SAFE_MESSAGES["internal_error"], rid, None),
        headers={**SECURITY_HEADERS, "X-Request-ID": rid, "X-Correlation-ID": correlation})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
