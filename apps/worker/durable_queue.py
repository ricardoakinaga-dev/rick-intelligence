"""Bounded, restartable SQLite queue with owner-bound leases.

This is a local durability primitive for the worker boundary. It deliberately
does not claim distributed coordination: one process should own a queue file,
and production multi-instance operation still needs an external broker or a
database deployment with an explicitly reviewed leasing policy.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
from threading import RLock
import time
from typing import Any

from rick_observability import emit_safely, opaque_ref


MAX_JSON_BYTES = 32 * 1024
MAX_TEXT = 256
MAX_QUEUE_ROWS = 100_000
MAX_TERMINAL_ROWS = 100_000
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_ALLOWED_PAYLOAD = frozenset({
    "operation", "document_id", "source_key", "filename", "request_id",
    "correlation_id", "collection_id", "workspace_id", "tenant_id",
})
_ACTIVE = frozenset({"queued", "leased"})
# ``published`` is the canonical external queue acknowledgement state; the
# local SQLite adapter historically calls the same terminal state ``acked``.
_TERMINAL = frozenset({"acked", "published", "dead", "cancelled"})


class DurableQueueError(RuntimeError):
    """Base class for queue control failures."""


class QueueCapacityError(DurableQueueError):
    pass


class QueueConfigurationError(DurableQueueError):
    pass


class QueueNotFoundError(DurableQueueError):
    pass


class QueueLeaseError(DurableQueueError):
    pass


class QueueIdempotencyError(DurableQueueError):
    pass


@dataclass(frozen=True, slots=True)
class QueueRecord:
    job_id: str
    idempotency_key: str
    status: str
    payload: Mapping[str, str]
    tenant_id: str
    workspace_id: str
    collection_id: str
    attempts: int
    available_at: float
    lease_until: float | None
    lease_token: str | None
    created_at: float
    updated_at: float
    last_error: str | None = None
    document_id: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "payload": dict(self.payload),
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "collection_id": self.collection_id,
            "attempts": self.attempts,
            "available_at": self.available_at,
            "lease_until": self.lease_until,
            "lease_token": self.lease_token,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_error": self.last_error,
            "document_id": self.document_id,
        }


def _safe_text(value: object, *, label: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise QueueConfigurationError(f"{label} must be text")
    candidate = value.strip()
    if not candidate or len(candidate) > limit or "\x00" in candidate or any(ord(ch) < 0x20 for ch in candidate):
        raise QueueConfigurationError(f"{label} is invalid")
    return candidate


def _safe_key(value: object, *, label: str) -> str:
    candidate = _safe_text(value, label=label, limit=128)
    if not _KEY.fullmatch(candidate):
        raise QueueConfigurationError(f"{label} is invalid")
    return candidate


def _safe_scope(value: object, *, label: str) -> str:
    return _safe_key(value, label=label)


def _payload(value: object) -> tuple[str, dict[str, str]]:
    if not isinstance(value, Mapping) or not value:
        raise QueueConfigurationError("payload must be a non-empty mapping")
    clean: dict[str, str] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or key not in _ALLOWED_PAYLOAD:
            raise QueueConfigurationError("payload contains an unsupported field")
        if not isinstance(raw, str):
            raise QueueConfigurationError("payload values must be bounded text")
        clean[key] = _safe_text(raw, label=f"payload.{key}")
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise QueueConfigurationError("payload is too large")
    return encoded, clean


def _safe_error(value: object) -> str:
    candidate = _safe_text(value, label="error", limit=64).lower()
    if not _SAFE_ERROR.fullmatch(candidate) or any(token in candidate for token in ("token", "secret", "password", "bearer")):
        raise QueueConfigurationError("error is invalid")
    return candidate


def _finite_now(value: object) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise QueueConfigurationError("clock returned an invalid value") from exc
    if not math.isfinite(converted):
        raise QueueConfigurationError("clock returned a non-finite value")
    return converted


class SQLiteDurableQueue:
    """A local queue with durable idempotency and owner-bound leases."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_pending: int = 256,
        max_terminal_rows: int | None = None,
        max_attempts: int = 3,
        lease_seconds: float = 30.0,
        backoff_seconds: float = 1.0,
        clock: Callable[[], float] = time.time,
        mode: str = "local",
        event_sink: object | None = None,
    ) -> None:
        if mode not in {"local", "test"} or os.environ.get("RICK_ENV", "").strip().lower() == "production":
            raise QueueConfigurationError("local durable queue cannot run in production mode")
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or not 0 < max_pending <= MAX_QUEUE_ROWS:
            raise QueueConfigurationError("max_pending is out of range")
        if max_terminal_rows is not None and (
            isinstance(max_terminal_rows, bool)
            or not isinstance(max_terminal_rows, int)
            or not 1 <= max_terminal_rows <= MAX_TERMINAL_ROWS
        ):
            raise QueueConfigurationError("max_terminal_rows is out of range")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 0 < max_attempts <= 64:
            raise QueueConfigurationError("max_attempts is out of range")
        if not isinstance(lease_seconds, (int, float)) or not 0.1 <= float(lease_seconds) <= 86_400:
            raise QueueConfigurationError("lease_seconds is out of range")
        if not isinstance(backoff_seconds, (int, float)) or not 0 <= float(backoff_seconds) <= 86_400:
            raise QueueConfigurationError("backoff_seconds is out of range")
        if not callable(clock):
            raise QueueConfigurationError("clock is invalid")

        if isinstance(path, Path):
            location = path
        elif isinstance(path, str) and path and "\x00" not in path:
            location = Path(path)
        else:
            raise QueueConfigurationError("queue path is invalid")
        if location == Path(".") or location.is_symlink():
            raise QueueConfigurationError("queue path is invalid")
        if location.exists() and location.is_dir():
            raise QueueConfigurationError("queue path must be a file")
        parent = location.parent
        try:
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(parent, 0o700)
            self._connection = sqlite3.connect(str(location), check_same_thread=False, timeout=5.0)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
            os.chmod(location, 0o600)
        except (OSError, sqlite3.Error) as exc:
            raise QueueConfigurationError("queue storage is unavailable") from exc

        self.path = str(location)
        self.max_pending = max_pending
        self.max_terminal_rows = (
            max_terminal_rows
            if max_terminal_rows is not None
            else min(MAX_TERMINAL_ROWS, max(64, max_pending * 4))
        )
        self.max_attempts = max_attempts
        self.lease_seconds = float(lease_seconds)
        self.backoff_seconds = float(backoff_seconds)
        self._clock = clock
        self._event_sink = event_sink
        self._lock = RLock()
        self._closed = False
        self._initialize()

    def _initialize(self) -> None:
        with self._transaction():
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS durable_jobs (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    available_at REAL NOT NULL,
                    lease_until REAL,
                    lease_owner TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS durable_jobs_claim_idx
                    ON durable_jobs (status, available_at, created_at, job_id);
                """
            )
            self._prune_terminal_rows()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            if self._closed:
                raise QueueConfigurationError("queue is closed")
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
                raise QueueConfigurationError("queue is closed")
            yield self._connection

    def _now(self) -> float:
        return _finite_now(self._clock())

    def _emit(self, event_name: str, **fields: object) -> None:
        """Emit bounded lifecycle metadata without exposing job payload/scope."""

        emit_safely(self._event_sink, event_name, fields)

    @staticmethod
    def _job_ref(job_id: str) -> str:
        return opaque_ref(job_id)

    @staticmethod
    def _decode(row: sqlite3.Row) -> QueueRecord:
        try:
            parsed = json.loads(row["payload_json"])
            payload = dict(parsed) if isinstance(parsed, Mapping) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        return QueueRecord(
            job_id=row["job_id"],
            idempotency_key=row["idempotency_key"],
            status=row["status"],
            payload=payload,
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            collection_id=row["collection_id"],
            attempts=int(row["attempts"]),
            available_at=float(row["available_at"]),
            lease_until=float(row["lease_until"]) if row["lease_until"] is not None else None,
            lease_token=row["lease_owner"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            last_error=row["last_error"],
        )

    def _row(self, job_id: str) -> QueueRecord | None:
        row = self._connection.execute("SELECT * FROM durable_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._decode(row) if row is not None else None

    def _prune_terminal_rows(self, *, preserve_job_id: str | None = None) -> int:
        """Retain a bounded terminal idempotency window.

        Active capacity and terminal history are separate budgets. A terminal
        row outside this window is intentionally forgotten, allowing its
        idempotency key to be reused while preventing an append-only SQLite
        history from defeating the queue bound.
        """
        total = int(
            self._connection.execute(
                "SELECT COUNT(*) FROM durable_jobs WHERE status IN ('acked', 'dead', 'cancelled')"
            ).fetchone()[0]
        )
        excess = total - self.max_terminal_rows
        if excess <= 0:
            return 0
        query = (
            "SELECT job_id FROM durable_jobs "
            "WHERE status IN ('acked', 'dead', 'cancelled')"
        )
        values: list[object] = []
        if preserve_job_id is not None:
            query += " AND job_id <> ?"
            values.append(preserve_job_id)
        query += " ORDER BY updated_at, created_at, job_id LIMIT ?"
        values.append(excess)
        rows = self._connection.execute(query, tuple(values)).fetchall()
        for row in rows:
            self._connection.execute("DELETE FROM durable_jobs WHERE job_id = ?", (row["job_id"],))
        return len(rows)

    def _recover_expired(self, now: float) -> int:
        rows = self._connection.execute(
            "SELECT job_id, attempts FROM durable_jobs WHERE status = 'leased' AND lease_until <= ?",
            (now,),
        ).fetchall()
        for row in rows:
            attempts = int(row["attempts"])
            if attempts >= self.max_attempts:
                self._connection.execute(
                    "UPDATE durable_jobs SET status='dead', lease_until=NULL, lease_owner=NULL, last_error=?, updated_at=? WHERE job_id=?",
                    ("lease_expired", now, row["job_id"]),
                )
            else:
                delay = self.backoff_seconds * (2 ** max(0, attempts - 1))
                self._connection.execute(
                    "UPDATE durable_jobs SET status='queued', available_at=?, lease_until=NULL, lease_owner=NULL, last_error=?, updated_at=? WHERE job_id=?",
                    (now + min(delay, 86_400.0), "lease_expired", now, row["job_id"]),
                )
        return len(rows)

    def enqueue(
        self,
        *,
        job_id: str,
        idempotency_key: str,
        payload: Mapping[str, str],
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        now: float | None = None,
    ) -> QueueRecord:
        job_id = _safe_key(job_id, label="job_id")
        idempotency_key = _safe_key(idempotency_key, label="idempotency_key")
        tenant_id = _safe_scope(tenant_id, label="tenant_id")
        workspace_id = _safe_scope(workspace_id, label="workspace_id")
        collection_id = _safe_scope(collection_id, label="collection_id")
        payload_json, clean_payload = _payload(payload)
        timestamp = self._now() if now is None else _finite_now(now)
        recovered_count = 0
        replayed = False
        with self._transaction():
            recovered_count = self._recover_expired(timestamp)
            existing = self._connection.execute(
                "SELECT * FROM durable_jobs WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing is not None:
                existing_record = self._decode(existing)
                if existing_record.payload != clean_payload or existing_record.job_id != job_id:
                    raise QueueIdempotencyError("idempotency key conflicts with an existing job")
                record = existing_record
                replayed = True
            else:
                active_count = self._connection.execute(
                    "SELECT COUNT(*) FROM durable_jobs WHERE status IN ('queued', 'leased')"
                ).fetchone()[0]
                if int(active_count) >= self.max_pending:
                    raise QueueCapacityError("durable queue is full")
                try:
                    self._connection.execute(
                        """INSERT INTO durable_jobs
                        (job_id, idempotency_key, status, payload_json, tenant_id,
                         workspace_id, collection_id, attempts, available_at,
                         lease_until, lease_owner, created_at, updated_at, last_error)
                        VALUES (?, ?, 'queued', ?, ?, ?, ?, 0, ?, NULL, NULL, ?, ?, NULL)""",
                        (job_id, idempotency_key, payload_json, tenant_id, workspace_id,
                         collection_id, timestamp, timestamp, timestamp),
                    )
                except sqlite3.IntegrityError as exc:
                    raise QueueIdempotencyError("job identity already exists") from exc
                record = self._row(job_id)  # type: ignore[assignment]
            # Recovery can create a terminal row before an idempotent replay
            # is resolved. Prune on both branches so the terminal window is an
            # invariant even when the replay refers to the row being kept.
            self._prune_terminal_rows(preserve_job_id=record.job_id if replayed else job_id)
        if recovered_count:
            self._emit("worker.queue.recovered", recovered=recovered_count)
        self._emit(
            "worker.queue.idempotent_replay" if replayed else "worker.queue.enqueued",
            job_ref=self._job_ref(record.job_id),
            status=record.status,
            attempts=record.attempts,
        )
        return record

    def claim(self, *, worker_id: str, limit: int = 1, now: float | None = None) -> tuple[QueueRecord, ...]:
        worker_id = _safe_key(worker_id, label="worker_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 100:
            raise QueueConfigurationError("claim limit is out of range")
        timestamp = self._now() if now is None else _finite_now(now)
        recovered_count = 0
        with self._transaction():
            recovered_count = self._recover_expired(timestamp)
            self._prune_terminal_rows()
            rows = self._connection.execute(
                "SELECT job_id FROM durable_jobs WHERE status='queued' AND available_at <= ? ORDER BY created_at, job_id LIMIT ?",
                (timestamp, limit),
            ).fetchall()
            claimed: list[QueueRecord] = []
            for row in rows:
                token = secrets.token_urlsafe(18)
                updated = self._connection.execute(
                    "UPDATE durable_jobs SET status='leased', attempts=attempts+1, lease_until=?, lease_owner=?, updated_at=? WHERE job_id=? AND status='queued'",
                    (timestamp + self.lease_seconds, f"{worker_id}:{token}", timestamp, row["job_id"]),
                )
                if updated.rowcount:
                    claimed.append(self._row(row["job_id"]) )  # type: ignore[arg-type]
        if recovered_count:
            self._emit("worker.queue.recovered", recovered=recovered_count)
        for record in claimed:
            self._emit(
                "worker.queue.claimed",
                job_ref=self._job_ref(record.job_id),
                status=record.status,
                attempts=record.attempts,
                worker_ref=opaque_ref(worker_id),
            )
        return tuple(claimed)

    def heartbeat(self, job_id: str, *, lease_token: str, now: float | None = None) -> QueueRecord:
        job_id = _safe_key(job_id, label="job_id")
        lease_token = _safe_text(lease_token, label="lease_token", limit=256)
        timestamp = self._now() if now is None else _finite_now(now)
        with self._transaction():
            row = self._owned_row(job_id, lease_token, timestamp)
            if row is None:
                if self._row(job_id) is None:
                    raise QueueNotFoundError("job does not exist")
                raise QueueLeaseError("lease is not owned by this worker")
            self._connection.execute(
                "UPDATE durable_jobs SET lease_until=?, updated_at=? WHERE job_id=? AND status='leased'",
                (timestamp + self.lease_seconds, timestamp, job_id),
            )
            record = self._row(job_id)  # type: ignore[assignment]
        self._emit(
            "worker.queue.heartbeat",
            job_ref=self._job_ref(record.job_id),
            status=record.status,
            attempts=record.attempts,
        )
        return record

    def ack(self, job_id: str, *, lease_token: str, now: float | None = None) -> QueueRecord:
        return self._finish(job_id, lease_token=lease_token, status="acked", now=now)

    def fail(self, job_id: str, *, lease_token: str, error: str, now: float | None = None) -> QueueRecord:
        job_id = _safe_key(job_id, label="job_id")
        lease_token = _safe_text(lease_token, label="lease_token", limit=256)
        safe_error = _safe_error(error)
        timestamp = self._now() if now is None else _finite_now(now)
        with self._transaction():
            row = self._owned_row(job_id, lease_token, timestamp)
            if row is None:
                raise QueueLeaseError("lease is not owned by this worker")
            attempts = int(row["attempts"])
            if attempts >= self.max_attempts:
                status = "dead"
                available_at = timestamp
            else:
                status = "queued"
                available_at = timestamp + min(self.backoff_seconds * (2 ** max(0, attempts - 1)), 86_400.0)
            self._connection.execute(
                "UPDATE durable_jobs SET status=?, available_at=?, lease_until=NULL, lease_owner=NULL, last_error=?, updated_at=? WHERE job_id=?",
                (status, available_at, safe_error, timestamp, job_id),
            )
            record = self._row(job_id)  # type: ignore[assignment]
            self._prune_terminal_rows(preserve_job_id=job_id if status == "dead" else None)
        self._emit(
            "worker.queue.failed",
            job_ref=self._job_ref(record.job_id),
            status=record.status,
            attempts=record.attempts,
            error=record.last_error or "unknown",
        )
        return record

    def _owned_row(self, job_id: str, lease_token: str, now: float) -> sqlite3.Row | None:
        row = self._connection.execute(
            "SELECT * FROM durable_jobs WHERE job_id=? AND status='leased' AND lease_owner=? AND lease_until > ?",
            (job_id, lease_token, now),
        ).fetchone()
        return row

    def _finish(self, job_id: str, *, lease_token: str, status: str, now: float | None) -> QueueRecord:
        job_id = _safe_key(job_id, label="job_id")
        lease_token = _safe_text(lease_token, label="lease_token", limit=256)
        timestamp = self._now() if now is None else _finite_now(now)
        with self._transaction():
            if self._owned_row(job_id, lease_token, timestamp) is None:
                raise QueueLeaseError("lease is not owned by this worker")
            self._connection.execute(
                "UPDATE durable_jobs SET status=?, lease_until=NULL, lease_owner=NULL, updated_at=? WHERE job_id=?",
                (status, timestamp, job_id),
            )
            record = self._row(job_id)  # type: ignore[assignment]
            self._prune_terminal_rows(preserve_job_id=job_id)
        self._emit(
            f"worker.queue.{status}",
            job_ref=self._job_ref(record.job_id),
            status=record.status,
            attempts=record.attempts,
        )
        return record

    def cancel(self, job_id: str, *, lease_token: str | None = None, now: float | None = None) -> QueueRecord:
        job_id = _safe_key(job_id, label="job_id")
        if lease_token is not None:
            lease_token = _safe_text(lease_token, label="lease_token", limit=256)
        timestamp = self._now() if now is None else _finite_now(now)
        changed = False
        with self._transaction():
            row = self._connection.execute("SELECT * FROM durable_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise QueueNotFoundError("job does not exist")
            if row["status"] == "leased" and (lease_token is None or row["lease_owner"] != lease_token):
                raise QueueLeaseError("leased job requires its owner to cancel")
            if row["status"] in {"acked", "dead", "cancelled"}:
                record = self._decode(row)
            else:
                self._connection.execute(
                    "UPDATE durable_jobs SET status='cancelled', lease_until=NULL, lease_owner=NULL, updated_at=? WHERE job_id=?",
                    (timestamp, job_id),
                )
                record = self._row(job_id)  # type: ignore[assignment]
                changed = True
            self._prune_terminal_rows(preserve_job_id=job_id)
        self._emit(
            "worker.queue.cancelled" if changed else "worker.queue.cancel_ignored",
            job_ref=self._job_ref(record.job_id),
            status=record.status,
            attempts=record.attempts,
            changed=changed,
        )
        return record

    def recover(self, *, now: float | None = None) -> int:
        timestamp = self._now() if now is None else _finite_now(now)
        with self._transaction():
            recovered = self._recover_expired(timestamp)
            self._prune_terminal_rows()
        if recovered:
            self._emit("worker.queue.recovered", recovered=recovered)
        return recovered

    def get(self, job_id: str) -> QueueRecord | None:
        job_id = _safe_key(job_id, label="job_id")
        with self._read():
            return self._row(job_id)

    def list(self, *, limit: int = 100, statuses: set[str] | None = None) -> tuple[QueueRecord, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1_000:
            raise QueueConfigurationError("list limit is out of range")
        allowed_statuses = {"queued", "leased", "acked", "dead", "cancelled"}
        if statuses is not None and not statuses.issubset(allowed_statuses):
            raise QueueConfigurationError("invalid queue status filter")
        query = "SELECT * FROM durable_jobs"
        values: list[Any] = []
        if statuses:
            query += " WHERE status IN (" + ",".join("?" for _ in statuses) + ")"
            values.extend(sorted(statuses))
        query += " ORDER BY created_at, job_id LIMIT ?"
        values.append(limit)
        with self._read():
            rows = self._connection.execute(query, tuple(values)).fetchall()
            return tuple(self._decode(row) for row in rows)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "SQLiteDurableQueue":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


__all__ = [
    "DurableQueueError", "QueueCapacityError", "QueueConfigurationError",
    "QueueIdempotencyError", "QueueLeaseError", "QueueNotFoundError",
    "QueueRecord", "SQLiteDurableQueue", "MAX_TERMINAL_ROWS",
]
