"""Bounded redaction for structured events and diagnostic fields."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MAX_EVENT_KEYS = 64
MAX_VALUE_CHARS = 512
MAX_NESTING = 4
MAX_EVENT_NODES = 512
MAX_EVENT_BYTES = 16 * 1024
_NODE_OVERHEAD_BYTES = 8
_SENSITIVE = frozenset({
    "authorization", "api_key", "apikey", "cookie", "credential", "password",
    "secret", "token", "set_cookie", "prompt", "document", "content", "body",
    "stack", "traceback", "raw_response",
})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_EVENT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,95}$")
_EMBEDDED_URL = re.compile(
    r"(?<![A-Za-z0-9+.-])(?:[A-Za-z][A-Za-z0-9+.-]*://|//)[^\s<>{}\"']+"
)
_SENSITIVE_VALUE = re.compile(
    r"\bbearer\s+[^\s\"']+",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_-])([\"']?[A-Za-z0-9_-]*"
    r"(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|authorization|cookie|credential|dsn|url|bearer)"
    r"[A-Za-z0-9_-]*[\"']?)(\s*[:=]\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\[redacted\]|"
    r"[^\s,;}\]]+)",
    re.IGNORECASE,
)
_SENSITIVE_ARGUMENT = re.compile(
    r"(?<![A-Za-z0-9_-])([/-]{0,2}[A-Za-z0-9_-]*"
    r"(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|authorization|cookie|credential|dsn|url|bearer)"
    r"[A-Za-z0-9_-]*)(\s+)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\[redacted\]|"
    r"[^\s,;}\]]+)",
    re.IGNORECASE,
)
_URL_TRAILING = frozenset(",.;:!?)]}")


def safe_text(value: object, *, limit: int = MAX_VALUE_CHARS) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _CONTROL.sub(" ", value).strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[redacted-url]"
    if not parsed.netloc:
        # A URL-like value without a parseable authority (for example a
        # malformed URL or a non-hierarchical scheme) is still untrusted
        # diagnostic input. Never return it verbatim.
        return "[redacted-url]"
    try:
        hostname = parsed.hostname or "[redacted-host]"
        port = parsed.port
    except ValueError:
        return "[redacted-url]"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    authority = hostname + (f":{port}" if port is not None else "")
    # Any hierarchical scheme can carry userinfo and query credentials
    # (redis://, amqp://, custom://, ...), so do not special-case HTTP.
    return urlunsplit((parsed.scheme, authority, parsed.path[:256], "", ""))


def _redact_embedded_urls(value: str) -> str:
    """Redact credentials and query material even inside free-form text."""

    # Diagnostics can contain a JSON-escaped URL copied from a nested payload.
    # Normalize only escaped slashes before parsing; the output is still passed
    # through the same authority/query-stripping path and never returns the
    # original credential-bearing spelling.
    value = value.replace(r"\/", "/")

    def replace(match: re.Match[str]) -> str:
        candidate = match.group(0)
        trailing = ""
        while candidate and candidate[-1] in _URL_TRAILING:
            trailing = candidate[-1] + trailing
            candidate = candidate[:-1]
        return _safe_url(candidate) + trailing

    return _EMBEDDED_URL.sub(replace, value)


def _redact_inline_secrets(value: str) -> str:
    """Remove credentials embedded in otherwise non-sensitive text fields."""

    value = value.replace(r"\/", "/")
    value = _redact_embedded_urls(value)
    value = _SENSITIVE_VALUE.sub("[redacted]", value)
    value = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[redacted]",
        value,
    )
    return _SENSITIVE_ARGUMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[redacted]",
        value,
    )


class _RedactionBudget:
    __slots__ = ("nodes_left", "bytes_left")

    def __init__(
        self,
        *,
        max_nodes: int = MAX_EVENT_NODES,
        max_bytes: int = MAX_EVENT_BYTES,
    ) -> None:
        self.nodes_left = max_nodes
        self.bytes_left = max_bytes

    @property
    def exhausted(self) -> bool:
        return self.nodes_left <= 0 or self.bytes_left < _NODE_OVERHEAD_BYTES

    def reserve_node(self) -> bool:
        if self.nodes_left <= 0 or self.bytes_left < _NODE_OVERHEAD_BYTES:
            return False
        self.nodes_left -= 1
        # Reserve a conservative amount for JSON punctuation, quotes and the
        # container slot. Scalar text is charged separately below.
        self.bytes_left -= _NODE_OVERHEAD_BYTES
        return True

    def marker(self) -> str | None:
        marker = "[truncated]"
        encoded_size = len(
            json.dumps(marker, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if self.bytes_left < encoded_size:
            return None
        self.bytes_left -= encoded_size
        return marker

    def text(self, value: str) -> str | None:
        # Charge the actual JSON string representation, including quotes and
        # escapes. The node reservation remains intentionally conservative for
        # the surrounding key/colon/comma/container punctuation.
        encoded_size = len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if encoded_size <= self.bytes_left:
            self.bytes_left -= encoded_size
            return value
        return self.marker()


def redact(
    value: object,
    *,
    _depth: int = 0,
    _budget: _RedactionBudget | None = None,
) -> Any:
    """Return a JSON-safe, bounded value with sensitive fields removed."""

    budget = _budget or _RedactionBudget()
    if not budget.reserve_node():
        return None
    if _depth > MAX_NESTING:
        return budget.marker()
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (raw_key, raw_value) in enumerate(value.items()):
            if index >= MAX_EVENT_KEYS:
                break
            key = safe_text(raw_key, limit=64) if isinstance(raw_key, str) else None
            if key is None:
                continue
            if not budget.reserve_node():
                break
            key = budget.text(key)
            if key is None:
                break
            lowered = key.lower().replace("-", "_")
            if any(marker in lowered for marker in _SENSITIVE):
                redacted = budget.text("[redacted]")
                if redacted is None:
                    break
                result[key] = redacted
            else:
                redacted = redact(raw_value, _depth=_depth + 1, _budget=budget)
                if redacted is None and budget.exhausted:
                    break
                result[key] = redacted
        return result
    if isinstance(value, (list, tuple)):
        result_list: list[Any] = []
        for index, item in enumerate(value):
            if index >= MAX_EVENT_KEYS:
                break
            redacted = redact(item, _depth=_depth + 1, _budget=budget)
            if redacted is None and budget.exhausted:
                break
            result_list.append(redacted)
        return result_list
    if isinstance(value, (bool, type(None))):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        candidate = "[bounded-integer]" if abs(value) >= 2**53 else str(value)
        charged = budget.text(candidate)
        if charged is None:
            return None
        return value if charged == candidate and candidate != "[bounded-integer]" else charged
    if isinstance(value, float):
        candidate = repr(value) if value == value and abs(value) != float("inf") else "[non-finite]"
        charged = budget.text(candidate)
        if charged is None:
            return None
        return value if charged == candidate and candidate != "[non-finite]" else charged
    if isinstance(value, str):
        cleaned = safe_text(value)
        if cleaned is None:
            return None
        cleaned = _redact_inline_secrets(cleaned)
        return budget.text(cleaned)
    return budget.marker()


def safe_event_name(value: object) -> str:
    """Keep event names bounded and free of query/credential syntax."""

    candidate = safe_text(value, limit=96)
    if candidate is None or _EVENT_NAME.fullmatch(candidate) is None:
        return "event"
    return candidate


def safe_event(event: Mapping[str, object], *, event_name: str = "event") -> dict[str, Any]:
    name = safe_event_name(event_name)
    # Reserve the fixed envelope so MAX_EVENT_BYTES applies to the complete
    # JSON event, not only to ``fields``. Four additional nodes cover the
    # envelope object, its two keys and the event name.
    envelope_empty = json.dumps(
        {"event": name, "fields": {}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    envelope_overhead = len(envelope_empty) - len(b"{}")
    budget = _RedactionBudget(
        max_nodes=max(1, MAX_EVENT_NODES - 4),
        max_bytes=max(0, MAX_EVENT_BYTES - envelope_overhead),
    )
    payload = redact(event, _budget=budget)
    return {"event": name, "fields": payload if isinstance(payload, dict) else {}}
