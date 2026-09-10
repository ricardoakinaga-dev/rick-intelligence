"""Bounded, finite JSON decoding for application-owned persisted values."""

from __future__ import annotations

import json


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON constants are not allowed")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def decode_request_json(value: bytes, *, max_bytes: int) -> object:
    """Decode one bounded request body without ambiguous JSON semantics."""

    if not isinstance(value, bytes):
        raise TypeError("request JSON must be bytes")
    if not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if len(value) > max_bytes:
        raise ValueError("request JSON exceeds the configured byte limit")
    try:
        parsed = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("request JSON is invalid") from exc
    if not isinstance(parsed, (dict, list)):
        raise ValueError("request JSON must be an object or array")
    return parsed


def decode_bounded_json(value: object, default: object, *, max_bytes: int) -> object:
    """Decode only finite object/array JSON within a UTF-8 byte budget."""

    if not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    parsed = value
    if isinstance(value, str):
        try:
            if len(value.encode("utf-8")) > max_bytes:
                return default
            parsed = json.loads(
                value,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, UnicodeError, ValueError, RecursionError):
            return default
    if not isinstance(parsed, (dict, list)):
        return default
    try:
        encoded = json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > max_bytes:
            return default
    except (TypeError, UnicodeError, ValueError, OverflowError, RecursionError):
        return default
    return parsed


__all__ = ["decode_bounded_json", "decode_request_json"]
