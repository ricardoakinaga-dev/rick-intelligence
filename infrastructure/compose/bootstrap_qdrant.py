#!/usr/bin/env python3
"""Create and validate the disposable Qdrant collection used by Compose.

The application never mutates a collection during import.  This one-shot
service owns the reviewed, idempotent bootstrap and exits before API/worker
processes are admitted.
"""

from __future__ import annotations

import json
import os
from pathlib import PurePosixPath
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or len(value) > 512 or "\x00" in value:
        raise RuntimeError(f"{name} is required")
    return value


def _endpoint() -> str:
    raw = _required("RICK_QDRANT_URL")
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("RICK_QDRANT_URL is invalid")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _request(endpoint: str, method: str, path: str, *, body: object | None = None) -> tuple[int, object | None]:
    encoded = None if body is None else json.dumps(body, separators=(",", ":"), allow_nan=False).encode("utf-8")
    request = Request(
        f"{endpoint}{PurePosixPath(path)}",
        data=encoded,
        method=method,
        headers={
            "api-key": _required("RICK_QDRANT_API_KEY"),
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if encoded is not None else {}),
        },
    )
    try:
        with urlopen(request, timeout=10.0) as response:
            payload = response.read(256 * 1024)
            return int(response.status), json.loads(payload.decode("utf-8")) if payload else None
    except HTTPError as error:
        payload = error.read(256 * 1024)
        if error.code == 404:
            return 404, None
        detail = payload.decode("utf-8", errors="replace")[:256]
        raise RuntimeError(f"Qdrant {method} {path} failed ({error.code}): {detail}") from None
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Qdrant {method} {path} failed") from error


def _require_success(status: int, operation: str) -> None:
    """Keep a one-shot bootstrap fail-closed on every mutation response."""

    if not 200 <= status < 300:
        raise RuntimeError(f"Qdrant {operation} returned an unexpected status")


def _dense_schema(payload: object) -> tuple[int, str]:
    """Extract the named dense vector schema from Qdrant's collection shape."""

    if not isinstance(payload, dict):
        raise RuntimeError("Qdrant collection schema is unavailable")
    result = payload.get("result")
    config = result.get("config") if isinstance(result, dict) else None
    params = config.get("params") if isinstance(config, dict) else None
    vectors = params.get("vectors") if isinstance(params, dict) else None
    if not isinstance(vectors, dict):
        raise RuntimeError("Qdrant collection vectors schema is unavailable")
    # This composition requires the explicit `dense` vector used by the
    # retrieval adapter; an unnamed collection is a schema mismatch.
    dense = vectors.get("dense")
    size = dense.get("size") if isinstance(dense, dict) else None
    distance = dense.get("distance") if isinstance(dense, dict) else None
    if type(size) is not int or not isinstance(distance, str):
        raise RuntimeError("Qdrant dense vector schema is invalid")
    return size, distance.strip().lower()


def main() -> int:
    endpoint = _endpoint()
    collection = _required("RICK_QDRANT_COLLECTION")
    if "/" in collection or len(collection) > 128:
        raise RuntimeError("RICK_QDRANT_COLLECTION is invalid")
    dimensions_raw = os.getenv("EMBEDDING_DIMENSION", os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536"))
    try:
        dimensions = int(dimensions_raw)
    except (TypeError, ValueError):
        raise RuntimeError("embedding dimensions are invalid") from None
    if not 1 <= dimensions <= 16_384:
        raise RuntimeError("embedding dimensions are out of range")

    path = f"/collections/{quote(collection, safe='')}"
    status, collection_payload = _request(endpoint, "GET", path)
    if status == 404:
        create_status, _ = _request(
            endpoint,
            "PUT",
            path,
            body={"vectors": {"dense": {"size": dimensions, "distance": "Cosine"}}},
        )
        _require_success(create_status, "collection create")
    elif status != 200:
        raise RuntimeError("Qdrant collection preflight failed")
    else:
        observed_dimensions, observed_distance = _dense_schema(collection_payload)
        if observed_dimensions != dimensions or observed_distance != "cosine":
            raise RuntimeError("Qdrant collection schema does not match the configured embedding")

    for field in ("tenant_id", "workspace_id", "collection_id"):
        index_status, _ = _request(
            endpoint,
            "PUT",
            f"{path}/index",
            body={"field_name": field, "field_schema": "keyword", "wait": True},
        )
        _require_success(index_status, f"index {field}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"qdrant bootstrap unavailable: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(2)
