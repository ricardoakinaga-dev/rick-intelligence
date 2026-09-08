"""Bounded local SQLite vector store for restartable test/dev runtimes.

This adapter is deliberately a local durability seam, not a replacement for
Qdrant.  It persists the same point dictionaries consumed by the canonical
retrieval facade, validates vectors and payloads before commit, and refuses to
start in production-shaped environments.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Iterator


MAX_POINT_ID = 256
MAX_VECTOR_DIMENSIONS = 16_384
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_POINTS_PER_WRITE = 1_000
MAX_POINTS_PER_READ = 100_000
_POINT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")


class SQLiteVectorStoreError(RuntimeError):
    """Base class for safe local vector-store failures."""


class SQLiteVectorStoreConfigurationError(SQLiteVectorStoreError, ValueError):
    pass


class SQLiteVectorStoreValidationError(SQLiteVectorStoreError, ValueError):
    pass


class SQLiteVectorStore:
    """Private SQLite point store with atomic idempotent upserts."""

    def __init__(self, path: str | Path, *, mode: str = "local") -> None:
        if mode not in {"local", "test"} or os.environ.get("RICK_ENV", "").strip().lower() == "production":
            raise SQLiteVectorStoreConfigurationError("local vector store is not allowed in production")
        if isinstance(path, Path):
            location = path
        elif isinstance(path, str) and path and "\x00" not in path:
            location = Path(path)
        else:
            raise SQLiteVectorStoreConfigurationError("vector store path is invalid")
        if location == Path(".") or location.is_symlink():
            raise SQLiteVectorStoreConfigurationError("vector store path is invalid")
        if location.exists() and location.is_dir():
            raise SQLiteVectorStoreConfigurationError("vector store path must be a file")
        try:
            location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(location.parent, 0o700)
            self._connection = sqlite3.connect(str(location), check_same_thread=False, timeout=5.0)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
            os.chmod(location, 0o600)
        except (OSError, sqlite3.Error) as exc:
            raise SQLiteVectorStoreConfigurationError("vector storage is unavailable") from exc
        self.path = str(location)
        self._lock = RLock()
        self._closed = False
        self._initialize()

    def _initialize(self) -> None:
        with self._transaction():
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS vector_points (
                    point_id TEXT PRIMARY KEY,
                    vector_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_checksum TEXT NOT NULL,
                    created_at REAL NOT NULL DEFAULT (unixepoch()),
                    updated_at REAL NOT NULL DEFAULT (unixepoch())
                );
                CREATE INDEX IF NOT EXISTS vector_points_document_idx
                    ON vector_points (
                        json_extract(payload_json, '$.document_id'),
                        json_extract(payload_json, '$.collection_id')
                    );
                """
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            if self._closed:
                raise SQLiteVectorStoreConfigurationError("vector store is closed")
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._closed:
                raise SQLiteVectorStoreConfigurationError("vector store is closed")
            yield self._connection

    def upsert_points(self, points: list[dict]) -> int:
        if not isinstance(points, list) or len(points) > MAX_POINTS_PER_WRITE:
            raise SQLiteVectorStoreValidationError("point batch is out of range")
        encoded: list[tuple[str, str, str, str]] = []
        for point in points:
            point_id, vector_json, payload_json, checksum = _validate_point(point)
            encoded.append((point_id, vector_json, payload_json, checksum))
        if not encoded:
            return 0
        with self._transaction():
            self._connection.executemany(
                """
                INSERT INTO vector_points(point_id, vector_json, payload_json, payload_checksum, updated_at)
                VALUES (?, ?, ?, ?, unixepoch())
                ON CONFLICT(point_id) DO UPDATE SET
                    vector_json=excluded.vector_json,
                    payload_json=excluded.payload_json,
                    payload_checksum=excluded.payload_checksum,
                    updated_at=unixepoch()
                """,
                encoded,
            )
        return len(encoded)

    def all_points(
        self,
        *,
        limit: int = MAX_POINTS_PER_READ,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= MAX_POINTS_PER_READ:
            raise SQLiteVectorStoreValidationError("point read limit is out of range")
        clauses: list[str] = []
        parameters: list[object] = []
        if tenant_id is not None:
            clauses.append("json_extract(payload_json, '$.tenant_id') = ?")
            parameters.append(tenant_id)
        if workspace_id is not None:
            clauses.append("json_extract(payload_json, '$.workspace_id') = ?")
            parameters.append(workspace_id)
        if allowed_collection_ids is not None:
            allowed = list(allowed_collection_ids)
            if "*" not in allowed:
                if not allowed:
                    return []
                clauses.append(
                    "json_extract(payload_json, '$.collection_id') IN ("
                    + ",".join("?" for _ in allowed) + ")"
                )
                parameters.extend(allowed)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(limit + 1)
        with self._read() as connection:
            rows = connection.execute(
                "SELECT point_id, vector_json, payload_json, payload_checksum "
                "FROM vector_points" + where + " ORDER BY point_id LIMIT ?",
                tuple(parameters),
            ).fetchall()
        if len(rows) > limit:
            raise SQLiteVectorStoreValidationError("complete point snapshot exceeds read limit")
        return [_decode_point(row) for row in rows]

    def delete_document(self, document_id: str, collection_id: str) -> int:
        _safe_identifier(document_id, "document_id")
        _safe_identifier(collection_id, "collection_id")
        with self._transaction():
            cursor = self._connection.execute(
                """
                DELETE FROM vector_points
                WHERE json_extract(payload_json, '$.document_id') = ?
                  AND json_extract(payload_json, '$.collection_id') = ?
                """,
                (document_id, collection_id),
            )
            return max(0, int(cursor.rowcount))

    def count_for_document(self, document_id: str, collection_id: str) -> int:
        _safe_identifier(document_id, "document_id")
        _safe_identifier(collection_id, "collection_id")
        with self._read() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM vector_points
                WHERE json_extract(payload_json, '$.document_id') = ?
                  AND json_extract(payload_json, '$.collection_id') = ?
                """,
                (document_id, collection_id),
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def __enter__(self) -> "SQLiteVectorStore":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


def _safe_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_POINT_ID or not _POINT_ID.fullmatch(value):
        raise SQLiteVectorStoreValidationError(f"{label} is invalid")
    return value


def _validate_point(point: object) -> tuple[str, str, str, str]:
    if not isinstance(point, Mapping):
        raise SQLiteVectorStoreValidationError("point must be a mapping")
    point_id = _safe_identifier(point.get("point_id"), "point_id")
    vector = point.get("vector")
    if not isinstance(vector, list) or not 0 < len(vector) <= MAX_VECTOR_DIMENSIONS:
        raise SQLiteVectorStoreValidationError("vector is invalid")
    normalized_vector: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SQLiteVectorStoreValidationError("vector contains a non-numeric value")
        converted = float(value)
        if not math.isfinite(converted):
            raise SQLiteVectorStoreValidationError("vector contains a non-finite value")
        normalized_vector.append(converted)
    payload = point.get("payload")
    if not isinstance(payload, Mapping):
        raise SQLiteVectorStoreValidationError("payload is invalid")
    try:
        payload_json = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SQLiteVectorStoreValidationError("payload is not JSON-safe") from exc
    if len(payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise SQLiteVectorStoreValidationError("payload is too large")
    vector_json = json.dumps(normalized_vector, separators=(",", ":"), allow_nan=False)
    checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return point_id, vector_json, payload_json, checksum


def _decode_point(row: sqlite3.Row) -> dict[str, Any]:
    try:
        vector = json.loads(row["vector_json"])
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SQLiteVectorStoreError("persisted point is corrupt") from exc
    if not isinstance(vector, list) or not isinstance(payload, dict):
        raise SQLiteVectorStoreError("persisted point is corrupt")
    checksum = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if checksum != row["payload_checksum"]:
        raise SQLiteVectorStoreError("persisted point integrity check failed")
    return {"point_id": row["point_id"], "vector": vector, "payload": payload}


__all__ = [
    "MAX_PAYLOAD_BYTES",
    "MAX_POINTS_PER_WRITE",
    "MAX_VECTOR_DIMENSIONS",
    "SQLiteVectorStore",
    "SQLiteVectorStoreConfigurationError",
    "SQLiteVectorStoreError",
    "SQLiteVectorStoreValidationError",
]
