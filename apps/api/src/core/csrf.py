"""Small, dependency-free CSRF/origin policy for cookie-authenticated requests."""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from urllib.parse import urlsplit


MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEFAULT_CSRF_HEADER = "X-CSRF-Token"


def is_mutating_method(method: str) -> bool:
    return method.upper() in MUTATING_METHODS


def _origin_from_url(value: str | None, *, allow_path: bool) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        return None
    if not allow_path and (parsed.path not in {"", "/"} or parsed.query):
        return None
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    hostname = hostname.lower()
    scheme = parsed.scheme.lower()
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    port_suffix = f":{port}" if port is not None and not default_port else ""
    return f"{scheme}://{hostname}{port_suffix}"


def normalize_origin(value: str | None) -> str | None:
    """Normalize an Origin header or an origin allowlist entry."""
    return _origin_from_url(value, allow_path=False)


def normalize_referer_origin(value: str | None) -> str | None:
    """Extract the origin from a Referer URL without trusting its path."""
    return _origin_from_url(value, allow_path=True)


def is_allowed_origin(value: str | None, allowed_origins: Iterable[str]) -> bool:
    normalized = normalize_origin(value)
    if normalized is None:
        return False
    return normalized in {
        configured
        for configured in (normalize_origin(item) for item in allowed_origins)
        if configured is not None
    }


def csrf_request_is_allowed(
    *,
    method: str,
    has_session_cookie: bool,
    environment: str,
    origin: str | None,
    referer: str | None,
    presented_token: str | None,
    configured_token: str | None,
    allowed_origins: Iterable[str],
) -> bool:
    """Return whether a request may mutate state under the cookie session.

    Local/test clients retain the existing no-Origin behavior. Once an Origin
    or Referer is supplied it is still validated, so a forged disallowed
    origin never becomes acceptable just because the process is local.
    """
    if not has_session_cookie or not is_mutating_method(method):
        return True

    if configured_token and presented_token and hmac.compare_digest(
        presented_token.encode("utf-8"), configured_token.encode("utf-8")
    ):
        return True

    if origin is not None:
        return is_allowed_origin(origin, allowed_origins)
    if referer is not None:
        return is_allowed_origin(normalize_referer_origin(referer), allowed_origins)

    return environment in {"local", "test"}
