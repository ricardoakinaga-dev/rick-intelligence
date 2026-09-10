"""Small local SQLite ledger for bounded ingestion-job recovery.

The journal is deliberately local and process-owned.  It records a narrow,
whitelisted job snapshot plus the private staging source reference needed for
restart recovery.  It is not a queue, a lease service, or a distributed
coordination mechanism.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sqlite3
from threading import RLock
import time
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_MAX_ROWS = 256
MAX_JOB_ID_LENGTH = 128
MAX_DOCUMENT_ID_LENGTH = 256
MAX_SCOPE_LENGTH = 128
MAX_FILENAME_LENGTH = 256
MAX_SOURCE_PATH_LENGTH = 4096
MAX_REQUEST_ID_LENGTH = 256
MAX_JSON_BYTES = 32 * 1024
MAX_ACL_ITEMS = 128

JOB_STATES = frozenset(
    {
        "queued",
        "validating",
        "parsing",
        "chunking",
        "embedding",
        "indexing",
        "verifying",
        "published",
        "failed",
        "cancelled",
    }
)
TERMINAL_STATES = frozenset({"published", "failed", "cancelled"})
RECOVERABLE_STATES = JOB_STATES - TERMINAL_STATES
ERROR_CODES = frozenset(
    {
        "validation_error",
        "unsupported_media_type",
        "request_too_large",
        "not_found",
        "storage_unavailable",
        "provider_timeout",
        "provider_unavailable",
        "vector_store_unavailable",
        "lock_unavailable",
        "conflict",
        "ingestion_failed",
        "recovery_required",
    }
)

_UNSET = object()
_INVALID_JSON = object()


class JobJournalError(RuntimeError):
    """Base error for local journal failures."""


class JobJournalCapacityError(JobJournalError):
    """Raised when bounded retention cannot evict an active row safely."""


def _value(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _safe_text(value: object, *, max_length: int, default: str | None = None) -> str | None:
    if not isinstance(value, str):
        return default
    candidate = value.strip()
    if (
        not candidate
        or len(candidate) > max_length
        or "\x00" in candidate
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate)
    ):
        return default
    return candidate


def _required_text(value: object, *, label: str, max_length: int) -> str:
    candidate = _safe_text(value, max_length=max_length)
    if candidate is None:
        raise ValueError(f"{label} is required")
    return candidate


def _safe_float(value: object, *, default: float = 0.0, minimum: float | None = None,
                maximum: float | None = None) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        converted = default
    if not math.isfinite(converted):
        converted = default
    if minimum is not None:
        converted = max(minimum, converted)
    if maximum is not None:
        converted = min(maximum, converted)
    return converted


def _safe_optional_float(value: object) -> float | None:
    if value is None:
        return None
    converted = _safe_float(value, default=float("nan"))
    return converted if math.isfinite(converted) else None


def _safe_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        converted = int(value)
    except (TypeError, ValueError):
        converted = default
    return min(maximum, max(minimum, converted))


def _safe_list(value: object, *, max_items: int = MAX_ACL_ITEMS,
               max_length: int = MAX_SCOPE_LENGTH) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        candidate = _safe_text(item, max_length=max_length)
        if candidate is None or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
        if len(result) >= max_items:
            break
    return result


def _json_text(value: Mapping[str, Any], *, label: str) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError(f"{label} is too large")
    return encoded


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON number")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded: dict[str, object] = {}
    for key, value in pairs:
        if key in decoded:
            raise ValueError("duplicate JSON object key")
        decoded[key] = value
    return decoded


def _decode_mapping(value: object) -> dict[str, Any] | object:
    if not isinstance(value, str):
        return _INVALID_JSON
    if len(value.encode("utf-8")) > MAX_JSON_BYTES:
        return _INVALID_JSON
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(decoded, Mapping):
            return _INVALID_JSON
        encoded = json.dumps(
            decoded,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
            return _INVALID_JSON
    except (RecursionError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
        return _INVALID_JSON
    return dict(decoded)


def _normalize_acl_snapshot(
    value: object,
    *,
    tenant_id: str,
    workspace_id: str,
    collection_id: str,
) -> dict[str, Any]:
    """Keep only the authorization facts needed to explain a job scope."""

    raw: Mapping[str, Any]
    if isinstance(value, Mapping):
        raw = value
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw = {"allowed_collection_ids": value}
    else:
        raw = {}

    snapshot: dict[str, Any] = {
        "authorization_snapshot_version": _safe_int(
            raw.get("authorization_snapshot_version", 1),
            default=1,
            minimum=1,
            maximum=16,
        ),
        # The row scope is authoritative. A caller-provided ACL snapshot is
        # diagnostic context only and must not be able to relabel a job.
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "collection_id": collection_id,
    }
    allowed = _safe_list(
        raw.get("allowed_collection_ids", raw.get("authorized_collection_ids", [collection_id])),
    )
    if not allowed:
        allowed = [collection_id]
    snapshot["allowed_collection_ids"] = allowed

    permissions = _safe_list(raw.get("permissions"), max_length=MAX_SCOPE_LENGTH)
    if permissions:
        snapshot["permissions"] = permissions
    return snapshot


def _normalize_metadata(value: object) -> dict[str, Any]:
    """Whitelist the small public metadata shape; never persist arbitrary job metadata."""

    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in ("execution", "durability", "restart_recovery", "storage"):
        raw = value.get(key)
        if key == "restart_recovery":
            if isinstance(raw, bool):
                result[key] = raw
            continue
        safe = _safe_text(raw, max_length=64)
        if safe is not None:
            result[key] = safe
    return result


class JobJournal:
    """A bounded, reopenable SQLite ledger for local ingestion jobs.

    Each write is an atomic upsert.  Terminal rows are the only rows eligible
    for retention eviction; active rows are never silently discarded.  The
    caller owns lifecycle policy for the executor and may pass this object to
    :class:`IngestionApplicationService` as an optional dependency.
    """

    def __init__(self, path: str | Path, *, max_rows: int = DEFAULT_MAX_ROWS) -> None:
        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 0 < max_rows <= 100_000:
            raise ValueError("max_rows is out of range")
        if isinstance(path, str) and path == ":memory:":
            self.path = ":memory:"
            self._directory: Path | None = None
        else:
            if isinstance(path, Path):
                location = path
            elif isinstance(path, str) and path and "\x00" not in path:
                location = Path(path)
            else:
                raise ValueError("journal path is invalid")
            if location.is_symlink():
                raise ValueError("journal path must not be a symlink")
            if location.exists() and location.is_dir():
                raise ValueError("journal path must be a file")
            directory = location.parent
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(directory, 0o700)
            except OSError as exc:
                raise ValueError("private journal directory is unavailable") from exc
            self.path = str(location)
            self._directory = directory

        self.max_rows = max_rows
        self._lock = RLock()
        try:
            self._connection = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
        except sqlite3.Error as exc:
            raise JobJournalError("could not open job journal") from exc
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
            self._initialize()
            self._harden_filesystem_permissions()
        except Exception:
            self._connection.close()
            raise

    def _harden_filesystem_permissions(self) -> None:
        if self.path == ":memory:":
            return
        try:
            os.chmod(self.path, 0o600)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{self.path}{suffix}")
                if sidecar.exists():
                    os.chmod(sidecar, 0o600)
        except OSError as exc:
            raise JobJournalError("private journal file is unavailable") from exc

    def _initialize(self) -> None:
        with self._transaction():
            current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if current not in (0, SCHEMA_VERSION):
                raise JobJournalError(f"unsupported job journal schema version: {current}")
            if current == 0:
                self._connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS ingestion_jobs (
                        job_id TEXT PRIMARY KEY,
                        document_id TEXT,
                        status TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        progress REAL NOT NULL,
                        attempt INTEGER NOT NULL,
                        error_code TEXT,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        collection_id TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        started_at REAL,
                        finished_at REAL,
                        cancel_requested INTEGER NOT NULL,
                        retry_count INTEGER NOT NULL,
                        source_path TEXT,
                        display_filename TEXT,
                        request_id TEXT,
                        correlation_id TEXT,
                        acl_json TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS ingestion_jobs_recovery_idx
                        ON ingestion_jobs (status, created_at, job_id);
                    CREATE INDEX IF NOT EXISTS ingestion_jobs_document_idx
                        ON ingestion_jobs (document_id, status, updated_at);
                    """
                )
                self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield
                # Harden before commit. Raising after commit would tell the
                # caller that persistence failed while the row was already
                # durable, which makes restart/recovery truth impossible.
                self._harden_filesystem_permissions()
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._connection

    @staticmethod
    def _row_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        acl_snapshot = _decode_mapping(row["acl_json"])
        metadata = _decode_mapping(row["metadata_json"])
        if acl_snapshot is _INVALID_JSON or metadata is _INVALID_JSON:
            return None
        return {
            "job_id": row["job_id"],
            "document_id": row["document_id"],
            "status": row["status"],
            "stage": row["stage"],
            "progress": float(row["progress"]),
            "attempt": int(row["attempt"]),
            "error_code": row["error_code"],
            "tenant_id": row["tenant_id"],
            "workspace_id": row["workspace_id"],
            "collection_id": row["collection_id"],
            "created_at": float(row["created_at"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "cancel_requested": bool(row["cancel_requested"]),
            "retry_count": int(row["retry_count"]),
            "source_path": row["source_path"],
            "display_filename": row["display_filename"],
            "request_id": row["request_id"],
            "correlation_id": row["correlation_id"],
            "acl_snapshot": acl_snapshot,
            "metadata": _normalize_metadata(metadata),
            "updated_at": float(row["updated_at"]),
        }

    def _normalize_job(
        self,
        job: object,
        *,
        existing: dict[str, Any] | None,
        source_path: object,
        display_filename: object,
        retry_count: object,
        acl_snapshot: object,
        request_id: object,
        correlation_id: object,
    ) -> dict[str, Any]:
        job_id = _safe_text(_value(job, "job_id"), max_length=MAX_JOB_ID_LENGTH)
        if job_id is None:
            raise ValueError("job_id is required")

        status = _safe_text(_value(job, "status", "failed"), max_length=32, default="failed") or "failed"
        if status not in JOB_STATES:
            status = "failed"
        error_code = _safe_text(_value(job, "error_code"), max_length=64)
        if error_code not in ERROR_CODES:
            error_code = None
        if status == "failed" and error_code is None and existing is not None:
            error_code = existing.get("error_code")
        stage = _safe_text(_value(job, "stage", status), max_length=32, default=status) or status
        if stage not in JOB_STATES:
            stage = status

        # Scope is an authorization boundary, not optional metadata. Older
        # code used to coerce a missing value to the default tenant, which
        # could make an incomplete job appear owned by the default tenant.
        tenant_id = _required_text(
            _value(job, "tenant_id"), label="tenant_id", max_length=MAX_SCOPE_LENGTH
        )
        workspace_id = _required_text(
            _value(job, "workspace_id"), label="workspace_id", max_length=MAX_SCOPE_LENGTH
        )
        collection_id = _required_text(
            _value(job, "collection_id"), label="collection_id", max_length=MAX_SCOPE_LENGTH
        )
        document_id = _safe_text(_value(job, "document_id"), max_length=MAX_DOCUMENT_ID_LENGTH)
        created_at = _safe_float(
            _value(job, "created_at", existing.get("created_at") if existing else time.time()),
            default=time.time(),
            minimum=0.0,
        )
        started_at = _safe_optional_float(_value(job, "started_at", existing.get("started_at") if existing else None))
        finished_at = _safe_optional_float(_value(job, "finished_at", existing.get("finished_at") if existing else None))
        metadata = _normalize_metadata(_value(job, "metadata", existing.get("metadata") if existing else {}))

        if source_path is _UNSET:
            normalized_source = existing.get("source_path") if existing else None
        elif source_path is None:
            normalized_source = None
        else:
            normalized_source = _safe_text(str(source_path), max_length=MAX_SOURCE_PATH_LENGTH)

        if display_filename is _UNSET:
            normalized_filename = existing.get("display_filename") if existing else None
        elif display_filename is None:
            normalized_filename = None
        else:
            normalized_filename = _safe_text(str(display_filename), max_length=MAX_FILENAME_LENGTH)

        if request_id is _UNSET:
            normalized_request_id = existing.get("request_id") if existing else None
        else:
            normalized_request_id = _safe_text(request_id, max_length=MAX_REQUEST_ID_LENGTH)
        if correlation_id is _UNSET:
            normalized_correlation_id = existing.get("correlation_id") if existing else None
        else:
            normalized_correlation_id = _safe_text(correlation_id, max_length=MAX_REQUEST_ID_LENGTH)

        if retry_count is _UNSET:
            raw_retry_count = _value(job, "retry_count", existing.get("retry_count", 0) if existing else 0)
        else:
            raw_retry_count = retry_count
        bounded_retry_count = _safe_int(raw_retry_count, default=0, minimum=0, maximum=64)

        if acl_snapshot is _UNSET:
            raw_acl = _value(job, "acl_snapshot", existing.get("acl_snapshot") if existing else None)
        else:
            raw_acl = acl_snapshot
        normalized_acl = _normalize_acl_snapshot(
            raw_acl,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            collection_id=collection_id,
        )
        return {
            "job_id": job_id,
            "document_id": document_id,
            "status": status,
            "stage": stage,
            "progress": _safe_float(_value(job, "progress", 0.0), minimum=0.0, maximum=1.0),
            "attempt": _safe_int(_value(job, "attempt", 1), default=1, minimum=1, maximum=64),
            "error_code": error_code,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "collection_id": collection_id,
            "created_at": created_at,
            "started_at": started_at,
            "finished_at": finished_at,
            "cancel_requested": 1 if _value(job, "cancel_requested", False) is True else 0,
            "retry_count": bounded_retry_count,
            "source_path": normalized_source,
            "display_filename": normalized_filename,
            "request_id": normalized_request_id,
            "correlation_id": normalized_correlation_id,
            "acl_json": _json_text(normalized_acl, label="acl snapshot"),
            "metadata_json": _json_text(metadata, label="job metadata"),
            "updated_at": time.time(),
        }

    def _trim_locked(self, *, keep_job_id: str) -> None:
        count = int(self._connection.execute("SELECT COUNT(*) FROM ingestion_jobs").fetchone()[0])
        excess = count - self.max_rows
        if excess <= 0:
            return
        terminal_rows = self._connection.execute(
            """
            SELECT job_id FROM ingestion_jobs
            WHERE status IN ('published', 'failed', 'cancelled') AND job_id != ?
            ORDER BY updated_at ASC, job_id ASC
            LIMIT ?
            """,
            (keep_job_id, excess),
        ).fetchall()
        if terminal_rows:
            self._connection.executemany(
                "DELETE FROM ingestion_jobs WHERE job_id = ?",
                [(row["job_id"],) for row in terminal_rows],
            )
        remaining = int(self._connection.execute("SELECT COUNT(*) FROM ingestion_jobs").fetchone()[0])
        if remaining > self.max_rows:
            raise JobJournalCapacityError("job journal capacity is exhausted by active jobs")

    def upsert(
        self,
        job: object,
        *,
        source_path: str | Path | None | object = _UNSET,
        display_filename: str | None | object = _UNSET,
        retry_count: int | object = _UNSET,
        acl_snapshot: Mapping[str, Any] | list[str] | tuple[str, ...] | object = _UNSET,
        request_id: str | None | object = _UNSET,
        correlation_id: str | None | object = _UNSET,
    ) -> dict[str, Any]:
        """Atomically insert/update one whitelisted job row."""

        with self._transaction():
            job_id = _safe_text(_value(job, "job_id"), max_length=MAX_JOB_ID_LENGTH)
            if job_id is None:
                raise ValueError("job_id is required")
            existing = self._row_record(
                self._connection.execute(
                    "SELECT * FROM ingestion_jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
            )
            normalized = self._normalize_job(
                job,
                existing=existing,
                source_path=source_path,
                display_filename=display_filename,
                retry_count=retry_count,
                acl_snapshot=acl_snapshot,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            self._connection.execute(
                """
                INSERT INTO ingestion_jobs (
                    job_id, document_id, status, stage, progress, attempt, error_code,
                    tenant_id, workspace_id, collection_id, created_at, started_at,
                    finished_at, cancel_requested, retry_count, source_path,
                    display_filename, request_id, correlation_id, acl_json,
                    metadata_json, updated_at
                ) VALUES (
                    :job_id, :document_id, :status, :stage, :progress, :attempt,
                    :error_code, :tenant_id, :workspace_id, :collection_id,
                    :created_at, :started_at, :finished_at, :cancel_requested,
                    :retry_count, :source_path, :display_filename, :request_id,
                    :correlation_id, :acl_json, :metadata_json, :updated_at
                )
                ON CONFLICT(job_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    status = excluded.status,
                    stage = excluded.stage,
                    progress = excluded.progress,
                    attempt = excluded.attempt,
                    error_code = excluded.error_code,
                    tenant_id = excluded.tenant_id,
                    workspace_id = excluded.workspace_id,
                    collection_id = excluded.collection_id,
                    created_at = excluded.created_at,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    cancel_requested = excluded.cancel_requested,
                    retry_count = excluded.retry_count,
                    source_path = excluded.source_path,
                    display_filename = excluded.display_filename,
                    request_id = excluded.request_id,
                    correlation_id = excluded.correlation_id,
                    acl_json = excluded.acl_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                normalized,
            )
            self._trim_locked(keep_job_id=job_id)
            row = self._connection.execute(
                "SELECT * FROM ingestion_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            record = self._row_record(row)
            if record is None:
                raise JobJournalError("job journal upsert was not observable")
            return record

    upsert_job = upsert
    record_job = upsert
    save = upsert

    def get(self, job_id: str) -> dict[str, Any] | None:
        safe_job_id = _safe_text(job_id, max_length=MAX_JOB_ID_LENGTH)
        if safe_job_id is None:
            return None
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE job_id = ?", (safe_job_id,)
            ).fetchone()
        return self._row_record(row)

    get_job = get

    def list_jobs(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is None:
            bounded_limit = self.max_rows
        else:
            bounded_limit = _safe_int(limit, default=self.max_rows, minimum=1, maximum=self.max_rows)
        with self._read() as connection:
            rows = connection.execute(
                """
                SELECT * FROM ingestion_jobs
                ORDER BY created_at ASC, job_id ASC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        return [record for row in rows if (record := self._row_record(row)) is not None]

    list = list_jobs

    def mark_recovery_required(
        self,
        job_id: str,
        *,
        source_path: str | Path | None | object = _UNSET,
    ) -> dict[str, Any] | None:
        safe_job_id = _safe_text(job_id, max_length=MAX_JOB_ID_LENGTH)
        if safe_job_id is None:
            return None
        if source_path is _UNSET or source_path is None:
            retained_source = None
        else:
            retained_source = _safe_text(str(source_path), max_length=MAX_SOURCE_PATH_LENGTH)
        now = time.time()
        with self._transaction():
            row = self._connection.execute(
                "SELECT 1 FROM ingestion_jobs WHERE job_id = ?", (safe_job_id,)
            ).fetchone()
            if row is None:
                return None
            self._connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'failed', stage = 'failed', error_code = 'recovery_required',
                    finished_at = ?, cancel_requested = 0, source_path = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (now, retained_source, now, safe_job_id),
            )
            updated = self._connection.execute(
                "SELECT * FROM ingestion_jobs WHERE job_id = ?", (safe_job_id,)
            ).fetchone()
            return self._row_record(updated)

    def row_count(self) -> int:
        with self._read() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM ingestion_jobs").fetchone()[0])

    count = row_count

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "JobJournal":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()


SQLiteJobJournal = JobJournal


__all__ = [
    "DEFAULT_MAX_ROWS",
    "ERROR_CODES",
    "JOB_STATES",
    "JobJournal",
    "JobJournalCapacityError",
    "JobJournalError",
    "RECOVERABLE_STATES",
    "SCHEMA_VERSION",
    "SQLiteJobJournal",
    "TERMINAL_STATES",
]
