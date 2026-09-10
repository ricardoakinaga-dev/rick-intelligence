"""Strict, bounded JSON decoding for evidence and runtime gate boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MAX_JSON_BYTES = 1 * 1024 * 1024


def _json_error(message: str) -> json.JSONDecodeError:
    return json.JSONDecodeError(message, "", 0)


def _reject_json_constant(_value: str) -> object:
    raise _json_error("non-finite JSON constants are not allowed")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded: dict[str, object] = {}
    for key, value in pairs:
        if key in decoded:
            raise _json_error("duplicate JSON object key")
        decoded[key] = value
    return decoded


def loads_json(value: str | bytes, *, maximum_bytes: int = MAX_JSON_BYTES) -> Any:
    """Decode finite UTF-8 JSON with a byte ceiling and unique object keys."""

    if isinstance(value, bytes):
        if len(value) > maximum_bytes:
            raise _json_error("JSON exceeds the bounded byte limit")
        text = value.decode("utf-8")
    elif isinstance(value, str):
        if len(value.encode("utf-8")) > maximum_bytes:
            raise _json_error("JSON exceeds the bounded byte limit")
        text = value
    else:
        raise TypeError("JSON input must be text or bytes")
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_json_constant,
    )


def load_json(path: Path, *, maximum_bytes: int = MAX_JSON_BYTES) -> Any:
    """Read and decode one bounded JSON file without unbounded buffering."""

    with path.open("rb") as stream:
        raw = stream.read(maximum_bytes + 1)
    return loads_json(raw, maximum_bytes=maximum_bytes)


__all__ = ["MAX_JSON_BYTES", "load_json", "loads_json"]
