"""Bounded, redacted in-memory audit sink for hermetic/local runtimes."""

from __future__ import annotations

from collections.abc import Mapping
import re
from urllib.parse import urlsplit, urlunsplit

from core.errors import ApiError


DEFAULT_RETENTION = 10_000
_ALLOWED_FIELDS = frozenset({
    "action", "actor_user_id", "target_id", "target_type", "tenant_id",
    "workspace_id", "request_id", "correlation_id", "reason", "status",
    "error_code", "user_id", "session_id", "collection_id",
})
_SAFE_STRING = re.compile(r"^[A-Za-z0-9_.:@/%+~\-]+$")
_SENSITIVE_VALUE_MARKERS = (
    "authorization", "bearer ", "api key", "apikey", "cookie", "credential",
    "password", "passphrase", "private document", "document content", "prompt",
    "secret", "token=", "reset token", "access token",
)


def emit_required(sink: object, event: dict) -> None:
    """Persist an audit event or fail the mutation request closed."""

    if sink is None:
        raise ApiError("provider_unavailable")
    health = getattr(sink, "health_check", None)
    if callable(health):
        try:
            healthy = health()
        except Exception:
            raise ApiError("provider_unavailable") from None
        if healthy is not True:
            raise ApiError("provider_unavailable")
    emitter = getattr(sink, "emit", None)
    if not callable(emitter):
        raise ApiError("provider_unavailable")
    try:
        result = emitter(event)
    except Exception:
        raise ApiError("provider_unavailable") from None
    if result is False:
        raise ApiError("provider_unavailable")


def _strip_url_credentials(value: str) -> str | None:
    """Keep a URL useful without persisting userinfo/query/fragment secrets.

    The audit boundary cannot assume that every identifier uses HTTP(S): object
    stores, database URLs, and provider-specific schemes are all plausible
    inputs.  Reconstruct every hierarchical URL from its parsed host/port and
    path so credentials in ``userinfo`` never survive under another scheme.
    """

    if "://" not in value:
        return value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if not parsed.netloc or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path[:256], "", ""))

try:
    from rick_observability import redact as _redact
except ImportError:  # Keep a packaged API fallback independent of the monorepo wheel.
    def _redact(value: object, *, _depth: int = 0) -> object:
        if _depth > 4:
            return "[truncated]"
        if isinstance(value, Mapping):
            result: dict[str, object] = {}
            for key, item in list(value.items())[:64]:
                if not isinstance(key, str):
                    continue
                lowered = key.lower().replace("-", "_")
                if any(marker in lowered for marker in (
                    "authorization", "api_key", "apikey", "cookie", "credential",
                    "password", "secret", "token", "prompt", "document", "content",
                    "body", "stack", "traceback", "raw_response",
                )):
                    result[key] = "[redacted]"
                else:
                    result[key] = _redact(item, _depth=_depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [_redact(item, _depth=_depth + 1) for item in list(value)[:64]]
        if isinstance(value, str):
            cleaned = value[:512]
            if "://" in cleaned:
                try:
                    parsed = urlsplit(cleaned)
                    if parsed.scheme in {"http", "https"} and parsed.netloc:
                        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path[:256], "", ""))
                except ValueError:
                    return "[redacted-url]"
            return cleaned
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return "[unsupported]"


class InMemoryAuditSink:
    def __init__(self, *, max_events: int = DEFAULT_RETENTION) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events <= 0:
            raise ValueError("audit retention must be a positive integer")
        self.max_events = max_events
        self.events: list[dict] = []

    def emit(self, event: dict) -> bool:
        try:
            sanitized = _redact(event)
            if not isinstance(sanitized, dict):
                return False
            sanitized = {
                key: value for key, value in sanitized.items()
                if key in _ALLOWED_FIELDS
            }
            safe: dict[str, str] = {}
            for key, value in sanitized.items():
                if not isinstance(value, str):
                    continue
                value = value.strip()
                if not value or len(value) > 512:
                    continue
                if "://" in value:
                    value = _strip_url_credentials(value)
                    if value is None:
                        continue
                lowered = value.casefold()
                if any(marker in lowered for marker in _SENSITIVE_VALUE_MARKERS):
                    continue
                if not _SAFE_STRING.fullmatch(value):
                    continue
                safe[key] = value
            if not safe.get("action"):
                return False
            self.events.append(safe)
            if len(self.events) > self.max_events:
                del self.events[:-self.max_events]
            return True
        except Exception:
            return False

    def health_check(self) -> bool:
        return True

    def list(
        self,
        *,
        tenant_id: str,
        workspace_id: str | None = None,
        limit: int = 50,
        order: str = "desc",
    ) -> list[dict]:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise ValueError("audit limit is out of range")
        normalized_order = order.strip().lower()
        if normalized_order not in {"asc", "ascending", "oldest", "desc", "descending", "newest"}:
            raise ValueError("audit order is invalid")
        items = [
            dict(event)
            for event in self.events
            if event.get("tenant_id") == tenant_id
            and (workspace_id is None or event.get("workspace_id") in {None, workspace_id})
        ]
        if normalized_order in {"desc", "descending", "newest"}:
            items.reverse()
        return items[:limit]
