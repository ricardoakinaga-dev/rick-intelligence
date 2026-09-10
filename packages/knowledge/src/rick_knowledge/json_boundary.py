"""Finite, byte-bounded JSON for persisted knowledge metadata."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any


MAX_METADATA_JSON_BYTES = 256 * 1024


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON constants are not allowed")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded: dict[str, object] = {}
    for key, value in pairs:
        if key in decoded:
            raise ValueError("duplicate JSON object key")
        decoded[key] = value
    return decoded


def encode_metadata(value: object) -> str:
    """Return canonical metadata JSON or reject it before a durable write."""

    if not isinstance(value, Mapping):
        raise ValueError("metadata must be a mapping")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise ValueError("metadata must be finite JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_METADATA_JSON_BYTES:
        raise ValueError("metadata exceeds the JSON size limit")
    return encoded


def decode_metadata(value: object) -> dict[str, Any] | None:
    """Decode one driver/SQLite value, omitting corrupt metadata rows."""

    if isinstance(value, str):
        try:
            if len(value.encode("utf-8")) > MAX_METADATA_JSON_BYTES:
                return None
            decoded = json.loads(
                value,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_json_constant,
            )
        except (RecursionError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
            return None
    elif isinstance(value, Mapping):
        decoded = dict(value)
    else:
        return None

    if not isinstance(decoded, Mapping):
        return None
    try:
        canonical = json.dumps(
            decoded,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(canonical.encode("utf-8")) > MAX_METADATA_JSON_BYTES:
            return None
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError):
        return None
    return dict(decoded)


__all__ = ["MAX_METADATA_JSON_BYTES", "decode_metadata", "encode_metadata"]
