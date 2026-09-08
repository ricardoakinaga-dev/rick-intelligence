"""Transactional PostgreSQL ingestion queue.

This module is an external counterpart to ``SQLiteDurableQueue``. It uses an
injected DB-API connection and PostgreSQL row locks; it never creates a
connection or reads credentials itself. Claims use ``FOR UPDATE SKIP LOCKED``
and every state transition checks the owner-bound lease in the same update.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import json
import secrets
import time
from typing import Iterator, Protocol

try:
    from rick_observability import emit_safely, opaque_ref
except ImportError:  # pragma: no cover - packaged worker fallback
    def emit_safely(*_args, **_kwargs) -> bool:
        return True

    def opaque_ref(value: object) -> str:
        import hashlib
        return hashlib.sha256(str(value).encode()).hexdigest()[:16]

try:
    from durable_queue import QueueRecord
except ImportError:  # pragma: no cover - package import layout
    from .durable_queue import QueueRecord


class DbConnection(Protocol):
    def cursor(self) -> object: ...
    def commit(self) -> object: ...
    def rollback(self) -> object: ...
    def close(self) -> object: ...


class PostgresQueueError(RuntimeError):
    def __init__(self, code: str = "queue_unavailable") -> None:
        self.code = code if code in {
            "queue_unavailable", "invalid_input", "capacity", "not_found",
            "lease", "idempotency", "closed",
        } else "queue_unavailable"
        super().__init__(self.code)


class PostgresQueueCapacityError(PostgresQueueError):
    def __init__(self) -> None:
        super().__init__("capacity")


class PostgresQueueLeaseError(PostgresQueueError):
    def __init__(self) -> None:
        super().__init__("lease")


class PostgresQueueIdempotencyError(PostgresQueueError):
    def __init__(self) -> None:
        super().__init__("idempotency")


def _text(value: object, *, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise PostgresQueueError("invalid_input")
    value = value.strip()
    if not value or len(value) > maximum or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise PostgresQueueError("invalid_input")
    return value


def _row_dict(cursor: object, row: object) -> dict[str, object]:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    description = getattr(cursor, "description", None) or ()
    names = [item[0] for item in description if isinstance(item, (tuple, list)) and item]
    return dict(zip(names, row if isinstance(row, (tuple, list)) else ()))


def _epoch(value: object) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _payload(value: Mapping[str, str]) -> tuple[str, dict[str, str]]:
    if not isinstance(value, Mapping) or not value or len(value) > 32:
        raise PostgresQueueError("invalid_input")
    clean: dict[str, str] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not isinstance(raw, str):
            raise PostgresQueueError("invalid_input")
        clean[_text(key, maximum=64)] = _text(raw, maximum=512)
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 32 * 1024:
        raise PostgresQueueError("invalid_input")
    return encoded, clean


@dataclass(frozen=True, slots=True)
class QueueHealth:
    ok: bool
    detail: str = ""


class PostgresIngestionQueue:
    """External queue implementation for the ``rick_ingestion`` worker port."""

    def __init__(
        self,
        connection_factory: Callable[[], DbConnection],
        *,
        max_pending: int = 256,
        max_attempts: int = 3,
        lease_seconds: float = 30.0,
        backoff_seconds: float = 1.0,
        close_connections: bool = True,
        event_sink: object | None = None,
    ) -> None:
        if not callable(connection_factory):
            raise PostgresQueueError("invalid_input")
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or not 1 <= max_pending <= 100_000:
            raise PostgresQueueError("invalid_input")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 64:
            raise PostgresQueueError("invalid_input")
        if not isinstance(lease_seconds, (int, float)) or not 0.1 <= float(lease_seconds) <= 86_400:
            raise PostgresQueueError("invalid_input")
        if not isinstance(backoff_seconds, (int, float)) or not 0 <= float(backoff_seconds) <= 86_400:
            raise PostgresQueueError("invalid_input")
        self._factory = connection_factory
        self.max_pending = max_pending
        self.max_attempts = max_attempts
        self.lease_seconds = float(lease_seconds)
        self.backoff_seconds = float(backoff_seconds)
        self._close_connections = close_connections
        self._event_sink = event_sink
        self._closed = False

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[tuple[DbConnection, object]]:
        if self._closed:
            raise PostgresQueueError("closed")
        connection: DbConnection | None = None
        cursor: object | None = None
        try:
            connection = self._factory()
            if connection is None:
                raise PostgresQueueError()
            cursor = connection.cursor()
            yield connection, cursor
            if write:
                connection.commit()
        except PostgresQueueError:
            if write and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        except Exception:
            if write and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise PostgresQueueError() from None
        finally:
            if cursor is not None:
                close = getattr(cursor, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            if self._close_connections and connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _execute(cursor: object, query: str, params: tuple[object, ...] = ()) -> None:
        execute = getattr(cursor, "execute", None)
        if not callable(execute):
            raise PostgresQueueError()
        execute(query, params)

    @staticmethod
    def _one(cursor: object) -> dict[str, object] | None:
        row = getattr(cursor, "fetchone", lambda: None)()
        return None if row is None else _row_dict(cursor, row)

    @staticmethod
    def _many(cursor: object) -> list[dict[str, object]]:
        return [_row_dict(cursor, row) for row in getattr(cursor, "fetchall", lambda: [])()]

    @staticmethod
    def _decode(row: Mapping[str, object]) -> QueueRecord:
        raw_payload = row.get("payload") or row.get("payload_json") or {}
        if isinstance(raw_payload, str):
            try:
                raw_payload = json.loads(raw_payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                raw_payload = {}
        payload = dict(raw_payload) if isinstance(raw_payload, Mapping) else {}
        return QueueRecord(
            job_id=str(row.get("job_id") or ""),
            idempotency_key=str(row.get("idempotency_key") or ""),
            status=str(row.get("status") or "queued"),
            payload=payload,
            tenant_id=str(row.get("tenant_id") or ""),
            workspace_id=str(row.get("workspace_id") or ""),
            collection_id=str(row.get("collection_id") or ""),
            attempts=int(row.get("attempts") or 0),
            available_at=_epoch(row.get("available_at")),
            lease_until=_epoch(row.get("lease_until")) if row.get("lease_until") is not None else None,
            lease_token=row.get("lease_owner") if isinstance(row.get("lease_owner"), str) else None,
            created_at=_epoch(row.get("created_at")),
            updated_at=_epoch(row.get("updated_at")),
            last_error=row.get("last_error_code") if isinstance(row.get("last_error_code"), str) else None,
            document_id=row.get("document_id") if isinstance(row.get("document_id"), str) else None,
        )

    def _emit(self, name: str, **fields: object) -> None:
        emit_safely(self._event_sink, name, fields)

    def health_check(self) -> QueueHealth:
        try:
            with self._session() as (_connection, cursor):
                self._execute(cursor, "SELECT 1")
                return QueueHealth(ok=self._one(cursor) is not None)
        except PostgresQueueError:
            return QueueHealth(ok=False, detail="unavailable")

    def enqueue(
        self, *, job_id: str, idempotency_key: str, payload: Mapping[str, str],
        tenant_id: str, workspace_id: str, collection_id: str,
    ) -> QueueRecord:
        job_id = _text(job_id, maximum=128)
        idempotency_key = _text(idempotency_key, maximum=128)
        tenant_id = _text(tenant_id, maximum=128)
        workspace_id = _text(workspace_id, maximum=128)
        collection_id = _text(collection_id, maximum=128)
        payload_json, clean_payload = _payload(payload)
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, """
                SELECT * FROM rick_ingestion_jobs
                WHERE tenant_id=%s AND idempotency_key=%s FOR UPDATE
            """, (tenant_id, idempotency_key))
            existing = self._one(cursor)
            if existing:
                record = self._decode(existing)
                if record.job_id != job_id or dict(record.payload) != clean_payload:
                    raise PostgresQueueIdempotencyError()
                replay = True
            else:
                self._execute(cursor, "SELECT COUNT(*) AS count FROM rick_ingestion_jobs WHERE status IN ('queued','leased','processing')")
                count_row = self._one(cursor)
                if int((count_row or {}).get("count", 0)) >= self.max_pending:
                    raise PostgresQueueCapacityError()
                self._execute(cursor, """
                    INSERT INTO rick_ingestion_jobs
                        (job_id, idempotency_key, tenant_id, workspace_id, collection_id,
                         status, attempts, available_at, last_error_code, payload)
                    VALUES (%s,%s,%s,%s,%s,'queued',0,NOW(),NULL,CAST(%s AS jsonb))
                    RETURNING *
                """, (job_id, idempotency_key, tenant_id, workspace_id, collection_id, payload_json))
                inserted = self._one(cursor)
                if inserted is None:
                    raise PostgresQueueError()
                record = self._decode(inserted)
                replay = False
            self._emit(
                "worker.queue.idempotent_replay" if replay else "worker.queue.enqueued",
                job_ref=opaque_ref(record.job_id),
                # The observability contract calls a queue acknowledgement
                # ``acked``; ``published`` remains the durable DB state.
                status="acked" if replay and record.status == "published" else record.status,
                attempts=record.attempts,
            )
            return record

    def _recover_expired(self, cursor: object) -> int:
        self._execute(cursor, """
            UPDATE rick_ingestion_jobs
            SET status = CASE WHEN attempts >= %s THEN 'dead' ELSE 'queued' END,
                lease_until = NULL, lease_owner = NULL,
                last_error_code = 'lease_expired', updated_at = NOW()
            WHERE status IN ('leased','processing') AND lease_until IS NOT NULL AND lease_until <= NOW()
        """, (self.max_attempts,))
        return max(0, int(getattr(cursor, "rowcount", 0) or 0))

    def claim(self, *, worker_id: str, limit: int = 1) -> tuple[QueueRecord, ...]:
        worker_id = _text(worker_id, maximum=128)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise PostgresQueueError("invalid_input")
        with self._session(write=True) as (_connection, cursor):
            recovered = self._recover_expired(cursor)
            self._execute(cursor, """
                SELECT job_id FROM rick_ingestion_jobs
                WHERE status='queued' AND available_at <= NOW()
                ORDER BY created_at, job_id
                LIMIT %s FOR UPDATE SKIP LOCKED
            """, (limit,))
            ids = [row.get("job_id") for row in self._many(cursor)]
            claimed: list[QueueRecord] = []
            for job_id in ids:
                if not isinstance(job_id, str):
                    continue
                owner = f"{worker_id}:{secrets.token_urlsafe(18)}"
                self._execute(cursor, """
                    UPDATE rick_ingestion_jobs
                    SET status='leased', attempts=attempts+1,
                        lease_until=NOW() + (%s * INTERVAL '1 second'),
                        lease_owner=%s, updated_at=NOW()
                    WHERE job_id=%s AND status='queued'
                    RETURNING *
                """, (self.lease_seconds, owner, job_id))
                row = self._one(cursor)
                if row is not None:
                    claimed.append(self._decode(row))
        if recovered:
            self._emit("worker.queue.recovered", recovered=recovered)
        for record in claimed:
            self._emit("worker.queue.claimed", job_ref=opaque_ref(record.job_id), status=record.status,
                       attempts=record.attempts, worker_ref=opaque_ref(worker_id))
        return tuple(claimed)

    def heartbeat(self, job_id: str, *, lease_token: str) -> QueueRecord:
        job_id = _text(job_id, maximum=128)
        lease_token = _text(lease_token, maximum=256)
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, """
                UPDATE rick_ingestion_jobs
                SET lease_until=NOW() + (%s * INTERVAL '1 second'), updated_at=NOW()
                WHERE job_id=%s AND status IN ('leased','processing')
                  AND lease_owner=%s AND lease_until > NOW()
                RETURNING *
            """, (self.lease_seconds, job_id, lease_token))
            row = self._one(cursor)
            if row is None:
                raise PostgresQueueLeaseError()
            result = self._decode(row)
        self._emit("worker.queue.heartbeat", job_ref=opaque_ref(job_id), status=result.status, attempts=result.attempts)
        return result

    def mark_processing(self, job_id: str, *, lease_token: str) -> QueueRecord:
        """Move a claimed job into processing under the same owner lease."""

        job_id = _text(job_id, maximum=128)
        lease_token = _text(lease_token, maximum=256)
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, """
                UPDATE rick_ingestion_jobs
                SET status='processing', updated_at=NOW()
                WHERE job_id=%s AND status='leased' AND lease_owner=%s
                  AND lease_until > NOW()
                RETURNING *
            """, (job_id, lease_token))
            row = self._one(cursor)
            if row is None:
                raise PostgresQueueLeaseError()
            result = self._decode(row)
        self._emit("worker.queue.processing", job_ref=opaque_ref(job_id), status=result.status,
                   attempts=result.attempts)
        return result

    def bind_document(
        self,
        job_id: str,
        document_id: str,
        *,
        lease_token: str,
    ) -> QueueRecord:
        """Attach the canonical document identity before publication."""

        job_id = _text(job_id, maximum=128)
        document_id = _text(document_id, maximum=256)
        lease_token = _text(lease_token, maximum=256)
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, """
                UPDATE rick_ingestion_jobs
                SET document_id=%s, updated_at=NOW()
                WHERE job_id=%s AND status='processing' AND lease_owner=%s
                  AND lease_until > NOW()
                RETURNING *
            """, (document_id, job_id, lease_token))
            row = self._one(cursor)
            if row is None:
                raise PostgresQueueLeaseError()
            result = self._decode(row)
        self._emit("worker.queue.document_bound", job_ref=opaque_ref(job_id),
                   document_ref=opaque_ref(document_id), status=result.status)
        return result

    def ack(self, job_id: str, *, lease_token: str) -> QueueRecord:
        return self._finish(job_id, lease_token=lease_token, status="published")

    def fail(self, job_id: str, *, lease_token: str, error: str) -> QueueRecord:
        job_id = _text(job_id, maximum=128)
        lease_token = _text(lease_token, maximum=256)
        error = _text(error, maximum=64).lower()
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, "SELECT * FROM rick_ingestion_jobs WHERE job_id=%s AND lease_owner=%s AND status IN ('leased','processing') FOR UPDATE", (job_id, lease_token))
            row = self._one(cursor)
            if row is None:
                raise PostgresQueueLeaseError()
            attempts = int(row.get("attempts") or 0)
            if attempts >= self.max_attempts:
                status = "dead"
                available = None
            else:
                status = "queued"
                available = self.backoff_seconds * (2 ** max(0, attempts - 1))
            self._execute(cursor, """
                UPDATE rick_ingestion_jobs
                SET status=%s, available_at=COALESCE(NOW() + (%s * INTERVAL '1 second'), available_at),
                    lease_until=NULL, lease_owner=NULL, last_error_code=%s, updated_at=NOW()
                WHERE job_id=%s RETURNING *
            """, (status, available, error, job_id))
            result_row = self._one(cursor)
            if result_row is None:
                raise PostgresQueueError()
            result = self._decode(result_row)
        self._emit("worker.queue.dead" if status == "dead" else "worker.queue.failed",
                   job_ref=opaque_ref(job_id), status=result.status, attempts=result.attempts, error=error)
        return result

    def _finish(self, job_id: str, *, lease_token: str, status: str) -> QueueRecord:
        job_id = _text(job_id, maximum=128)
        lease_token = _text(lease_token, maximum=256)
        if status not in {"published", "cancelled"}:
            raise PostgresQueueError("invalid_input")
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, """
                UPDATE rick_ingestion_jobs
                SET status=%s, lease_until=NULL, lease_owner=NULL, updated_at=NOW()
                WHERE job_id=%s AND status IN ('leased','processing') AND lease_owner=%s
                RETURNING *
            """, (status, job_id, lease_token))
            row = self._one(cursor)
            if row is None:
                raise PostgresQueueLeaseError()
            result = self._decode(row)
        self._emit("worker.queue.acked" if status == "published" else "worker.queue.cancelled",
                   job_ref=opaque_ref(job_id),
                   status="acked" if status == "published" else result.status,
                   attempts=result.attempts)
        return result

    def cancel(
        self,
        job_id: str,
        *,
        lease_token: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> QueueRecord:
        job_id = _text(job_id, maximum=128)
        if lease_token is not None:
            lease_token = _text(lease_token, maximum=256)
        if (tenant_id is None) != (workspace_id is None):
            raise PostgresQueueError("invalid_input")
        scope_clause = ""
        scope_params: tuple[object, ...] = ()
        if tenant_id is not None:
            scope_clause = " AND tenant_id=%s AND workspace_id=%s"
            scope_params = (
                _text(tenant_id, maximum=128),
                _text(workspace_id, maximum=128),
            )
        with self._session(write=True) as (_connection, cursor):
            if lease_token:
                self._execute(cursor, "UPDATE rick_ingestion_jobs SET status='cancelled', lease_until=NULL, lease_owner=NULL, updated_at=NOW() WHERE job_id=%s AND status IN ('queued','leased','processing') AND (status='queued' OR lease_owner=%s)" + scope_clause + " RETURNING *", (job_id, lease_token, *scope_params))
            else:
                self._execute(cursor, "UPDATE rick_ingestion_jobs SET status='cancelled', lease_until=NULL, lease_owner=NULL, updated_at=NOW() WHERE job_id=%s AND status='queued'" + scope_clause + " RETURNING *", (job_id, *scope_params))
            row = self._one(cursor)
            if row is None:
                raise PostgresQueueLeaseError()
            result = self._decode(row)
        self._emit("worker.queue.cancelled", job_ref=opaque_ref(job_id), status=result.status, attempts=result.attempts)
        return result

    def get(
        self,
        job_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> QueueRecord | None:
        job_id = _text(job_id, maximum=128)
        if (tenant_id is None) != (workspace_id is None):
            raise PostgresQueueError("invalid_input")
        where = "job_id=%s"
        params: tuple[object, ...] = (job_id,)
        if tenant_id is not None:
            tenant_id = _text(tenant_id, maximum=128)
            workspace_id = _text(workspace_id, maximum=128)
            where = "job_id=%s AND tenant_id=%s AND workspace_id=%s"
            params = (job_id, tenant_id, workspace_id)
        with self._session() as (_connection, cursor):
            self._execute(cursor, f"SELECT * FROM rick_ingestion_jobs WHERE {where} LIMIT 1", params)
            row = self._one(cursor)
        return self._decode(row) if row else None

    def list(
        self,
        *,
        limit: int = 100,
        statuses: set[str] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> tuple[QueueRecord, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise PostgresQueueError("invalid_input")
        allowed = {"queued", "leased", "processing", "published", "failed", "cancelled", "dead"}
        if statuses is not None and (not statuses or not set(statuses).issubset(allowed)):
            raise PostgresQueueError("invalid_input")
        if (tenant_id is None) != (workspace_id is None):
            raise PostgresQueueError("invalid_input")
        query = "SELECT * FROM rick_ingestion_jobs"
        params: list[object] = []
        clauses: list[str] = []
        if tenant_id is not None:
            clauses.extend(("tenant_id=%s", "workspace_id=%s"))
            params.extend((_text(tenant_id, maximum=128), _text(workspace_id, maximum=128)))
        if statuses is not None:
            clauses.append("status = ANY(%s)")
            params.append(list(statuses))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at, job_id LIMIT %s"
        params.append(limit)
        with self._session() as (_connection, cursor):
            self._execute(cursor, query, tuple(params))
            rows = self._many(cursor)
        return tuple(self._decode(row) for row in rows)

    def close(self) -> None:
        self._closed = True


PostgresDurableQueue = PostgresIngestionQueue


__all__ = [
    "DbConnection", "PostgresDurableQueue", "PostgresIngestionQueue",
    "PostgresQueueCapacityError", "PostgresQueueError",
    "PostgresQueueIdempotencyError", "PostgresQueueLeaseError", "QueueHealth",
]
