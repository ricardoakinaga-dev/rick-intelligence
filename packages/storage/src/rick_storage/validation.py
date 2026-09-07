"""Input validation for filesystem-independent object identities."""

from __future__ import annotations

from rick_storage.errors import InvalidObjectKeyError, InvalidScopeError

MAX_SCOPE_COMPONENT_BYTES = 128
MAX_OBJECT_KEY_BYTES = 1024


def _valid_text(value: object, *, maximum_bytes: int) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    if len(encoded) > maximum_bytes:
        return False
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return False
    return True


def validate_scope_component(value: object) -> str:
    """Validate one tenant/workspace/source path component.

    Scope components are deliberately stricter than object keys because they
    are represented as directory names.  They are never normalized or
    silently rewritten.
    """

    if not _valid_text(value, maximum_bytes=MAX_SCOPE_COMPONENT_BYTES):
        raise InvalidScopeError()
    candidate = value  # type: ignore[assignment]
    if candidate in {".", ".."} or "/" in candidate or "\\" in candidate or ":" in candidate:
        raise InvalidScopeError()
    if candidate.endswith((".", " ")):
        raise InvalidScopeError()
    return candidate


def validate_object_key(value: object) -> str:
    """Validate a relative logical key without relying on filesystem joins."""

    if not _valid_text(value, maximum_bytes=MAX_OBJECT_KEY_BYTES):
        raise InvalidObjectKeyError()
    candidate = value  # type: ignore[assignment]
    if (
        candidate.startswith(("/", "\\"))
        or candidate.endswith("/")
        or "\\" in candidate
        or ":" in candidate
    ):
        raise InvalidObjectKeyError()
    parts = candidate.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise InvalidObjectKeyError()
    if any(len(part.encode("utf-8")) > MAX_SCOPE_COMPONENT_BYTES for part in parts):
        raise InvalidObjectKeyError()
    return candidate


def validate_key_prefix(value: object) -> str:
    """Validate a list prefix while allowing one trailing separator."""

    if value == "":
        return ""
    if not _valid_text(value, maximum_bytes=MAX_OBJECT_KEY_BYTES):
        raise InvalidObjectKeyError()
    candidate = value  # type: ignore[assignment]
    if candidate.startswith(("/", "\\")) or "\\" in candidate or ":" in candidate:
        raise InvalidObjectKeyError()
    parts = candidate.split("/")
    if parts[-1] == "":
        parts = parts[:-1]
    if any(not part or part in {".", ".."} for part in parts):
        raise InvalidObjectKeyError()
    if any(len(part.encode("utf-8")) > MAX_SCOPE_COMPONENT_BYTES for part in parts):
        raise InvalidObjectKeyError()
    return candidate


__all__ = [
    "MAX_OBJECT_KEY_BYTES",
    "MAX_SCOPE_COMPONENT_BYTES",
    "validate_key_prefix",
    "validate_object_key",
    "validate_scope_component",
]
