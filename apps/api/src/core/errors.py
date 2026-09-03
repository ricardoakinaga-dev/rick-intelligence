"""Canonical error envelope. Never leaks stack traces, provider bodies, or secrets."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    "lock_unavailable": "Lock service is unavailable.",
    "ingestion_failed": "Ingestion failed.",
    "retrieval_failed": "Retrieval failed.",
    "generation_failed": "Generation failed.",
    "internal_error": "Internal server error.",
}


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


def envelope(code: str, message: str, request_id: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id, "details": details}}


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


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = _request_id(request)
    return JSONResponse(status_code=500, content=envelope("internal_error", _SAFE_MESSAGES["internal_error"], rid, None))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
