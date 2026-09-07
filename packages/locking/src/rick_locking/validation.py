"""Input validation shared by every lease implementation."""

from __future__ import annotations

import math
import uuid
from urllib.parse import urlsplit

from rick_locking.errors import LeaseError, LeaseOperation

MAX_KEY_LENGTH = 512
MAX_OWNER_LENGTH = 256
MAX_TTL_MS = 3_600_000
MAX_CORRELATION_ID_LENGTH = 128
MAX_BASE_URL_LENGTH = 2_048
MAX_RESPONSE_BYTES = 64 * 1024
MAX_TIMEOUT_SECONDS = 30.0
DEFAULT_CLEANUP_TIMEOUT_SECONDS = 2.0

def new_correlation_id() -> str:
    """Create a bounded, log-safe correlation ID."""

    return uuid.uuid4().hex


def correlation_id_for(
    operation: LeaseOperation, correlation_id: str | None
) -> str:
    """Validate or create a correlation ID, raising only a safe error."""

    generated = new_correlation_id()
    if correlation_id is None:
        return generated
    if (
        isinstance(correlation_id, str)
        and 1 <= len(correlation_id) <= MAX_CORRELATION_ID_LENGTH
        and all(char.isalnum() or char in "._:-" for char in correlation_id)
    ):
        return correlation_id
    raise LeaseError("invalid_request", operation, generated)


def _valid_scalar_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and all(ord(char) >= 0x20 and char != "\x7f" for char in value)
    )


def validate_key(key: object, operation: LeaseOperation, correlation_id: str) -> str:
    if not _valid_scalar_text(key, MAX_KEY_LENGTH):
        raise LeaseError("invalid_request", operation, correlation_id)
    return key  # type: ignore[return-value]


def validate_owner(owner: object, operation: LeaseOperation, correlation_id: str) -> str:
    if not _valid_scalar_text(owner, MAX_OWNER_LENGTH):
        raise LeaseError("invalid_request", operation, correlation_id)
    return owner  # type: ignore[return-value]


def validate_ttl(ttl_ms: object, operation: LeaseOperation, correlation_id: str) -> int:
    if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int):
        raise LeaseError("invalid_request", operation, correlation_id)
    if not 0 < ttl_ms <= MAX_TTL_MS:
        raise LeaseError("invalid_request", operation, correlation_id)
    return ttl_ms


def validate_timeout(
    timeout_seconds: object, operation: LeaseOperation, correlation_id: str
) -> float:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise LeaseError("invalid_request", operation, correlation_id)
    value = float(timeout_seconds)
    if not math.isfinite(value) or not 0.0 < value <= MAX_TIMEOUT_SECONDS:
        raise LeaseError("invalid_request", operation, correlation_id)
    return value


def validate_cleanup_timeout(timeout_seconds: object) -> float:
    """Validate a local cleanup bound without accepting unsafe values."""

    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("invalid cleanup timeout")
    value = float(timeout_seconds)
    if not math.isfinite(value) or not 0.0 < value <= MAX_TIMEOUT_SECONDS:
        raise ValueError("invalid cleanup timeout")
    return value


def validate_response_limit(
    maximum_bytes: object, operation: LeaseOperation, correlation_id: str
) -> int:
    if isinstance(maximum_bytes, bool) or not isinstance(maximum_bytes, int):
        raise LeaseError("invalid_request", operation, correlation_id)
    if not 1 <= maximum_bytes <= 4 * 1024 * 1024:
        raise LeaseError("invalid_request", operation, correlation_id)
    return maximum_bytes


def validate_base_url(base_url: object) -> str:
    """Validate an HTTP(S) endpoint without putting it in any public error."""

    if not isinstance(base_url, str) or not 1 <= len(base_url) <= MAX_BASE_URL_LENGTH:
        raise ValueError("invalid locker endpoint")
    if any(ord(char) < 0x20 or char == "\x7f" for char in base_url):
        raise ValueError("invalid locker endpoint")
    valid_port = True
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        hostname = None
        valid_port = False
        parsed = None
    if (
        parsed is None
        or parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or not valid_port
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid locker endpoint")
    return base_url.rstrip("/")


__all__ = [
    "DEFAULT_CLEANUP_TIMEOUT_SECONDS",
    "MAX_BASE_URL_LENGTH",
    "MAX_CORRELATION_ID_LENGTH",
    "MAX_KEY_LENGTH",
    "MAX_OWNER_LENGTH",
    "MAX_RESPONSE_BYTES",
    "MAX_TIMEOUT_SECONDS",
    "MAX_TTL_MS",
    "correlation_id_for",
    "new_correlation_id",
    "validate_base_url",
    "validate_cleanup_timeout",
    "validate_key",
    "validate_owner",
    "validate_response_limit",
    "validate_timeout",
    "validate_ttl",
]
