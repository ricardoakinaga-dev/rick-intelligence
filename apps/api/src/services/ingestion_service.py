"""Bounded API application boundary for the canonical ingestion service.

The package-level :class:`rick_ingestion.IngestionService` owns the document
state machine.  This module owns the HTTP-facing concerns around it:

* copying an upload into a private, server-generated staging file;
* applying a bounded read while copying the source;
* retaining only enough process-local state to support status, cancellation,
  and reindex of an upload made by this process; and
* reducing package jobs to a deliberately small public DTO.

The default remains intentionally process-local.  An optional local SQLite
job journal can restore bounded staging references after restart; it is not a
claim of a distributed queue or object-storage semantics.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
import hashlib
import inspect
from itertools import islice
import json
import math
import os
import re
import secrets
import shutil
import tempfile
import copy
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from threading import Condition, Event, RLock, Thread, current_thread, get_ident
from typing import Any, Callable

from core.telemetry import emit_safely, opaque_ref


SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".md", ".txt"})
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_READ_CHUNK_BYTES = 64 * 1024
DEFAULT_MAX_JOBS = 256
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_STAGED_BYTES = DEFAULT_MAX_BYTES * 2
MAX_POINT_SNAPSHOT = 100_000

_WORKSPACE_ID = re.compile(r"^[^\x00/\\]{1,128}$")
_JOB_STATES = frozenset(
    {"queued", "processing", "validating", "parsing", "chunking", "embedding", "indexing", "verifying", "published", "failed", "cancelled"}
)
_TERMINAL_STATES = frozenset({"published", "failed", "cancelled"})
_RECOVERABLE_STATES = _JOB_STATES - _TERMINAL_STATES
_SAFE_ERROR_MESSAGES = {
    "validation_error": "Document validation failed.",
    "unsupported_media_type": "Unsupported document type.",
    "request_too_large": "Document is too large.",
    "not_found": "Resource not found.",
    "storage_unavailable": "Upload storage is unavailable.",
    "provider_timeout": "Ingestion provider timed out.",
    "provider_unavailable": "Ingestion provider is unavailable.",
    "vector_store_unavailable": "Vector store is unavailable.",
    "lock_unavailable": "Lock service is unavailable.",
    "conflict": "The ingestion job cannot be retried in its current state.",
    "recovery_required": "Ingestion recovery requires operator attention.",
    "ingestion_failed": "Ingestion failed.",
}
_SAFE_ERROR_CODES = frozenset(_SAFE_ERROR_MESSAGES)


class IngestionApplicationError(Exception):
    """Internal, code-only error used at the API application boundary.

    ``message`` is retained for local diagnostics only.  Routes map the code
    to the public ``ApiError`` message and never serialize this exception.
    """

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code if code in _SAFE_ERROR_CODES else "ingestion_failed"
        self.message = message or _SAFE_ERROR_MESSAGES[self.code]
        super().__init__(self.message)


def _value(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _safe_order(value: object) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return 0.0
    return converted if math.isfinite(converted) else 0.0


def _safe_identifier(value: object, *, default: str | None = None, max_length: int = 256) -> str | None:
    if value is None:
        return default
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


def _retryable(error_code: str | None) -> bool:
    if not error_code:
        return False
    try:
        from rick_ingestion import is_retryable

        return bool(is_retryable(error_code))
    except (ImportError, AttributeError):
        return error_code in {"provider_timeout", "provider_unavailable", "vector_store_unavailable", "lock_unavailable", "storage_unavailable"}


def safe_job_json(
    job: object,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    collection_id: str | None = None,
) -> dict[str, Any]:
    """Return the only job representation allowed across the API boundary.

    This function is whitelist-based rather than a dataclass dump.  In
    particular, it does not copy arbitrary ``metadata``, heartbeat fields,
    exception objects, filenames, source text, or paths from a package job.
    """

    raw_status = _value(job, "status", "failed")
    status = raw_status if isinstance(raw_status, str) and raw_status in _JOB_STATES else "failed"
    raw_stage = _value(job, "stage", status)
    stage = raw_stage if isinstance(raw_stage, str) and raw_stage in _JOB_STATES else status

    raw_progress = _value(job, "progress", 0.0)
    try:
        progress = float(raw_progress)
    except (TypeError, ValueError):
        progress = 0.0
    progress = round(min(1.0, max(0.0, progress)), 4)

    raw_attempt = _value(job, "attempt", 1)
    try:
        attempt = min(64, max(1, int(raw_attempt)))
    except (TypeError, ValueError):
        attempt = 1

    raw_error_code = _value(job, "error_code")
    error_code = raw_error_code if isinstance(raw_error_code, str) and raw_error_code in _SAFE_ERROR_CODES else None

    metadata = _value(job, "metadata", {})
    journaled = _value(job, "_journaled", False) is True or (
        isinstance(metadata, Mapping)
        and (metadata.get("durability") == "local-sqlite" or metadata.get("restart_recovery") is True)
    )
    result: dict[str, Any] = {
        "job_id": _safe_identifier(_value(job, "job_id"), default="unknown-job", max_length=128),
        "document_id": _safe_identifier(_value(job, "document_id"), max_length=256),
        "status": status,
        "stage": stage,
        "progress": progress,
        "attempt": attempt,
        "error_code": error_code,
        "cancel_requested": _value(job, "cancel_requested", False) is True,
        "retryable": _retryable(error_code),
        "tenant_id": _safe_identifier(_value(job, "tenant_id"), default=tenant_id, max_length=128),
        "workspace_id": _safe_identifier(_value(job, "workspace_id"), default=workspace_id, max_length=128),
        "collection_id": _safe_identifier(_value(job, "collection_id"), default=collection_id, max_length=128),
        "metadata": {
            "execution": "process-local",
            "durability": "local-sqlite" if journaled else "process-local",
            "restart_recovery": journaled,
            "storage": "private-staging" if journaled else "private-temporary",
        },
    }

    # Timestamps are bounded scalar observability fields.  Do not include the
    # package's heartbeat list because it is extensible input from the worker.
    for name in ("created_at", "started_at", "finished_at"):
        timestamp = _value(job, name)
        if timestamp is None:
            result[name] = None
            continue
        try:
            converted = float(timestamp)
            result[name] = converted if math.isfinite(converted) else None
        except (TypeError, ValueError):
            result[name] = None

    if error_code:
        result["error_message"] = _SAFE_ERROR_MESSAGES[error_code]
    else:
        result["error_message"] = None
    if error_code == "recovery_required":
        result["recovery_required"] = True
    return result


# Explicit aliases make the serializer easy to discover without exposing a
# second, subtly different serialization path.
serialize_job = safe_job_json
job_to_json = safe_job_json


class _TrackedEventSink:
    """Track the actual callback thread when observability is time-bounded."""

    __slots__ = ("_owner", "_target")

    def __init__(self, owner: "IngestionApplicationService", target: object) -> None:
        self._owner = owner
        self._target = target

    def emit(self, event: object) -> None:
        self._owner._event_callback_started()
        try:
            emitter = getattr(self._target, "emit", None)
            if callable(emitter):
                emitter(event)
            elif callable(self._target):
                self._target(event)
        finally:
            self._owner._event_callback_finished()


class IngestionApplicationService:
    """Small process-local lifecycle facade over canonical ingestion.

    ``ingestion`` must implement the synchronous package contract. The public
    ``submit_upload`` method adds a bounded local queue, while ``upload``
    remains available for deterministic internal callers. The optional
    ``refresh_callback`` is invoked after a job reaches ``published`` and
    after the application state lock is released, so the root retrieval
    facade can rebuild its in-memory view without blocking lifecycle callers.
    """

    # Explicitly limited to the hermetic process-local adapter. Durable
    # integrations must implement the scoped list_jobs signature themselves;
    # the admin route refuses an unscoped fallback for those providers.
    allow_unscoped_legacy_listing = True
    runtime_metadata = {
        "execution": "process-local",
        "durability": "process-local",
    }

    def __init__(
        self,
        ingestion: object,
        *,
        refresh_callback: Callable[[], object] | None = None,
        staging_root: Path | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        read_chunk_bytes: int = DEFAULT_READ_CHUNK_BYTES,
        max_jobs: int = DEFAULT_MAX_JOBS,
        max_staged_bytes: int = DEFAULT_MAX_STAGED_BYTES,
        job_journal: object | None = None,
        event_sink: object | None = None,
    ) -> None:
        if ingestion is None:
            raise ValueError("ingestion service is required")
        if max_bytes <= 0 or max_bytes > DEFAULT_MAX_BYTES:
            raise ValueError("max_bytes is out of range")
        if read_chunk_bytes <= 0 or read_chunk_bytes > 1024 * 1024:
            raise ValueError("read_chunk_bytes is out of range")
        if max_jobs <= 0:
            raise ValueError("max_jobs is out of range")
        if max_staged_bytes < max_bytes:
            raise ValueError("max_staged_bytes must cover one upload")

        self.ingestion = ingestion
        self.refresh_callback = refresh_callback
        self.max_bytes = max_bytes
        self.read_chunk_bytes = read_chunk_bytes
        self.max_jobs = max_jobs
        self.max_staged_bytes = max_staged_bytes
        self.job_journal = job_journal
        self.event_sink = event_sink

        owns_staging_root = staging_root is None and job_journal is None
        if staging_root is None:
            root = Path(tempfile.mkdtemp(prefix="rick-ingestion-"))
        else:
            root = Path(staging_root)
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.staging_root = root.resolve()
        self._owns_staging_root = owns_staging_root
        self._staging_root_closed = False
        self.staging_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.staging_root, 0o700)
        except OSError as exc:
            raise ValueError("private staging storage is unavailable") from exc
        # A failed journal write and a failed unlink must not erase the last
        # restart-recovery reference. This directory is created lazily only
        # when the primary journal cannot persist a private cleanup lease.
        self._cleanup_lease_root = self.staging_root / ".cleanup-leases"

        self._jobs: dict[str, object] = {}
        self._retry_counts: dict[str, int] = {}
        self._job_paths: dict[str, Path] = {}
        self._document_paths: dict[str, Path] = {}
        self._document_filenames: dict[str, str] = {}
        self._document_order: dict[str, int] = {}
        self._document_order_counter = 0
        self._staged_bytes = 0
        # Keep per-file reservations so a partially written source is never
        # subtracted from the aggregate budget as if it had been fully
        # accounted (or, worse, as if it had no bytes at all).
        self._staged_sizes: dict[Path, int] = {}
        self._lock = RLock()
        self._async_pending = 0
        self._cancel_events: dict[str, Event] = {}
        self._scheduled_jobs: set[str] = set()
        self._scheduled_futures: dict[str, object] = {}
        self._start_gates: dict[str, Event] = {}
        self._accepting_work = True
        self._admission_condition = Condition()
        self._active_operations = 0
        self._active_operation_threads: dict[int, int] = {}
        self._event_callbacks = 0
        self._event_callback_threads: dict[int, int] = {}
        self._event_sink_proxy = (
            _TrackedEventSink(self, event_sink) if event_sink is not None else None
        )
        self._shutdown_lock = RLock()
        self._staging_cleanup_thread: Thread | None = None
        self._staging_cleanup_error: Exception | None = None
        # _async_pending is checked before submission, so the executor queue
        # never receives more than the configured bounded workload.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rick-ingestion")
        self._restore_journal()
        self._restore_cleanup_leases()

    @contextmanager
    def _admitted_operation(self, *, allow_stopping: bool = False):
        """Account for work that must finish before dependent stores close."""

        with self._admission_condition:
            if not allow_stopping and not self._accepting_work:
                raise IngestionApplicationError(
                    "storage_unavailable", "Ingestion queue is unavailable."
                )
            self._active_operations += 1
            thread_id = get_ident()
            self._active_operation_threads[thread_id] = self._active_operation_threads.get(thread_id, 0) + 1
        try:
            yield
        finally:
            with self._admission_condition:
                self._active_operations = max(0, self._active_operations - 1)
                thread_id = get_ident()
                active_on_thread = self._active_operation_threads.get(thread_id, 0)
                if active_on_thread <= 1:
                    self._active_operation_threads.pop(thread_id, None)
                else:
                    self._active_operation_threads[thread_id] = active_on_thread - 1
                self._admission_condition.notify_all()

    def _set_accepting_work(self, accepting: bool) -> None:
        with self._admission_condition:
            self._accepting_work = accepting
            self._admission_condition.notify_all()

    def _event_callback_started(self) -> None:
        with self._admission_condition:
            self._event_callbacks += 1
            thread_id = get_ident()
            self._event_callback_threads[thread_id] = self._event_callback_threads.get(thread_id, 0) + 1

    def _event_callback_finished(self) -> None:
        with self._admission_condition:
            self._event_callbacks = max(0, self._event_callbacks - 1)
            thread_id = get_ident()
            active_on_thread = self._event_callback_threads.get(thread_id, 0)
            if active_on_thread <= 1:
                self._event_callback_threads.pop(thread_id, None)
            else:
                self._event_callback_threads[thread_id] = active_on_thread - 1
            self._admission_condition.notify_all()

    def _wait_for_active_operations(self, deadline: float | None) -> bool:
        """Wait for admitted work without exceeding a lifecycle deadline."""

        with self._admission_condition:
            while self._active_operations or self._event_callbacks:
                if deadline is None:
                    self._admission_condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._admission_condition.wait(remaining)
        return True

    def _submit_async(self, job_id: str, function: Callable[..., object], *args: object) -> None:
        """Submit one local job while retaining its future for shutdown."""

        # Keep submission and registration under the same lock. A worker can
        # finish immediately, so registering after releasing the lock would
        # leave a completed future invisible to the shutdown reconciler.
        with self._lock:
            if not self._accepting_work:
                raise RuntimeError("ingestion service is shutting down")
            future = self._executor.submit(function, *args)
            self._scheduled_futures[job_id] = future

    # ---------------------------------------------------------- local journal
    def _journal_upsert(
        self,
        job: object,
        source_path: Path | None = None,
        *,
        display_filename: str | None = None,
        retry_count: int | None = None,
        acl_snapshot: Mapping[str, Any] | None = None,
        request_id: str | None | object = None,
        correlation_id: str | None | object = None,
        preserve_request_context: bool = True,
        retain_source_on_cleanup_failure: bool = False,
    ) -> bool:
        """Best-effort persistence boundary that never changes no-journal behavior.

        A terminal job normally clears its source reference. When unlink has
        failed, the reference is deliberately retained so a restart can retry
        private-source cleanup instead of silently orphaning the upload.
        """

        journal = self.job_journal
        if journal is None:
            return False
        upsert = getattr(journal, "upsert", None) or getattr(journal, "upsert_job", None)
        if not callable(upsert):
            return False

        status = _value(job, "status", "failed")
        persisted_source = (
            source_path
            if status not in {"failed", "cancelled"} or retain_source_on_cleanup_failure
            else None
        )
        kwargs: dict[str, Any] = {
            "source_path": str(persisted_source) if persisted_source is not None else None,
        }
        if display_filename is not None:
            kwargs["display_filename"] = display_filename
        if retry_count is not None:
            kwargs["retry_count"] = retry_count
        if acl_snapshot is not None:
            kwargs["acl_snapshot"] = acl_snapshot
        if not preserve_request_context or request_id is not None:
            kwargs["request_id"] = request_id
        if not preserve_request_context or correlation_id is not None:
            kwargs["correlation_id"] = correlation_id
        try:
            outcome = upsert(job, **kwargs)
            if outcome is False:
                return False
        except Exception:
            # A local journal must not turn a successful canonical ingestion
            # into a public failure. Cleanup callers have a separate private
            # lease fallback so a failed journal write cannot erase the last
            # restart-recovery reference.
            return False
        if isinstance(job, dict):
            job["_journaled"] = True
        else:
            try:
                setattr(job, "_journaled", True)
            except Exception:
                pass
        return True

    @staticmethod
    def _cleanup_lease_filename(job_id: object) -> str:
        digest = hashlib.sha256(str(job_id).encode("utf-8", "replace")).hexdigest()
        return f"lease-{digest[:32]}.json"

    def _safe_staging_path(self, raw_path: object) -> Path | None:
        """Resolve a private staging path without following it outside root."""
        if isinstance(raw_path, Path):
            candidate = raw_path
        elif isinstance(raw_path, str) and raw_path:
            candidate = Path(raw_path)
        else:
            return None
        if not candidate.is_absolute():
            return None
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(self.staging_root)
            if (
                resolved == self.staging_root
                or resolved == self._cleanup_lease_root
                or self._cleanup_lease_root in resolved.parents
            ):
                return None
        except (OSError, ValueError):
            return None
        return resolved

    def _persist_cleanup_lease(self, job_id: object, job: object, path: Path) -> bool:
        """Persist a private fallback lease when the primary journal is unavailable."""
        safe_path = self._safe_staging_path(path)
        scope = self._job_scope(job)
        if safe_path is None or scope is None:
            return False
        lease_root = self._cleanup_lease_root
        temporary: str | None = None
        try:
            lease_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(lease_root, 0o700)
            payload = {
                "version": 1,
                "job_id": _safe_identifier(job_id, max_length=128) or "unknown",
                "source_path": str(safe_path),
                "tenant_id": scope[0],
                "workspace_id": scope[1],
                "collection_id": scope[2],
            }
            descriptor, temporary = tempfile.mkstemp(
                prefix=".lease-", suffix=".tmp", dir=str(lease_root)
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, lease_root / self._cleanup_lease_filename(job_id))
            temporary = None
            return True
        except (OSError, TypeError, ValueError):
            return False
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    @staticmethod
    def _remove_cleanup_lease(marker: Path, lease_root: Path) -> None:
        try:
            marker.unlink()
        except OSError:
            return
        try:
            if not any(lease_root.iterdir()):
                lease_root.rmdir()
        except OSError:
            pass

    def _restore_cleanup_leases(self) -> None:
        """Retry private cleanup leases that outlived a failed journal write."""
        lease_root = self._cleanup_lease_root
        try:
            markers = sorted(lease_root.iterdir())
        except (OSError, FileNotFoundError):
            return
        for marker in markers:
            if marker.is_symlink() or not marker.is_file() or marker.suffix != ".json":
                continue
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, Mapping) or payload.get("version") != 1:
                continue
            if not all(
                _safe_identifier(payload.get(name), max_length=128)
                for name in ("tenant_id", "workspace_id", "collection_id")
            ):
                continue
            source = self._safe_staging_path(payload.get("source_path"))
            if source is not None and self._remove_path(source):
                self._remove_cleanup_lease(marker, lease_root)

    def _journal_records(self) -> list[Mapping[str, Any]]:
        journal = self.job_journal
        if journal is None:
            return []
        reader = getattr(journal, "list_jobs", None) or getattr(journal, "list", None)
        if not callable(reader):
            return []
        try:
            records = reader()
        except TypeError:
            try:
                records = reader(limit=max(self.max_jobs, 1))
            except Exception:
                return []
        except Exception:
            return []
        return [record for record in records if isinstance(record, Mapping)] if isinstance(records, list) else []

    def _journal_mark_recovery_required(
        self,
        job_id: str,
        *,
        source_path: Path | None = None,
        retain_source: bool = False,
    ) -> None:
        journal = self.job_journal
        marker = getattr(journal, "mark_recovery_required", None) if journal is not None else None
        if not callable(marker):
            return
        try:
            if retain_source and source_path is not None:
                marker(job_id, source_path=source_path)
            else:
                marker(job_id)
        except TypeError:
            # Narrow compatibility seam for test doubles that predate the
            # optional cleanup reference. The real journal supports it.
            try:
                marker(job_id)
            except Exception:
                return
        except Exception:
            # Recovery quarantine is best effort at this boundary; malformed
            # rows remain opaque even if the local journal is unavailable.
            return

    def _cleanup_job_source(
        self,
        job_id: str,
        job: object,
        path: Path | None,
        *,
        preserve_path: Path | None = None,
    ) -> bool:
        """Remove a terminal source, retaining its reference until success."""
        if path is None or (preserve_path is not None and path == preserve_path):
            self._journal_upsert(job, None)
            return True
        if self._remove_path(path):
            self._job_paths.pop(job_id, None)
            self._journal_upsert(job, None)
            return True
        # Keep both references. The journal is private/internal and will be
        # retried on restart; safe_job_json never exposes source_path.
        self._job_paths[job_id] = path
        persisted = self._journal_upsert(
            job,
            path,
            retain_source_on_cleanup_failure=True,
        )
        if self.job_journal is not None and not persisted:
            self._persist_cleanup_lease(job_id, job, path)
        return False

    def _quarantine_unowned_source(
        self,
        path: Path,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
    ) -> None:
        """Keep an unowned source recoverable when a cleanup unlink fails."""
        job_id = f"cleanup-{secrets.token_hex(12)}"
        now = time.time()
        job = {
            "job_id": job_id,
            "document_id": None,
            "status": "failed",
            "stage": "failed",
            "progress": 0.0,
            "attempt": 1,
            "error_code": "recovery_required",
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "collection_id": collection_id,
            "created_at": now,
            "started_at": None,
            "finished_at": now,
            "cancel_requested": False,
            "metadata": {},
        }
        self._jobs[job_id] = job
        self._job_paths[job_id] = path
        persisted = self._journal_upsert(
            job,
            path,
            display_filename=path.name,
            retain_source_on_cleanup_failure=True,
        )
        if self.job_journal is not None and not persisted:
            self._persist_cleanup_lease(job_id, job, path)

    @staticmethod
    def _job_scope(job: object) -> tuple[str, str, str] | None:
        """Return a complete scope only when the canonical job proves it."""
        values = tuple(
            _safe_identifier(_value(job, name), max_length=128)
            for name in ("tenant_id", "workspace_id", "collection_id")
        )
        return values if all(values) else None  # type: ignore[return-value]

    def _remove_or_quarantine(
        self,
        path: Path | None,
        *,
        scope: tuple[str, str, str] | None,
    ) -> bool:
        """Unlink a private source or retain an owned cleanup lease."""
        if self._remove_path(path):
            return True
        if path is not None and scope is not None:
            self._quarantine_unowned_source(
                path,
                tenant_id=scope[0],
                workspace_id=scope[1],
                collection_id=scope[2],
            )
        return False

    def _recovery_path(self, raw_path: object) -> Path | None:
        """Accept only an existing resolved file below the private staging root."""

        if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
            return None
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            return None
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(self.staging_root)
        except (OSError, ValueError):
            return None
        try:
            if not resolved.is_file():
                return None
        except OSError:
            return None
        return resolved

    @staticmethod
    def _recovery_job(record: Mapping[str, Any]) -> dict[str, Any] | None:
        job_id = _safe_identifier(record.get("job_id"), max_length=128)
        if not job_id:
            return None
        status = record.get("status", "failed")
        if status not in _JOB_STATES:
            return None
        tenant_id = _safe_identifier(record.get("tenant_id"), max_length=128)
        workspace_id = _safe_identifier(record.get("workspace_id"), max_length=128)
        collection_id = _safe_identifier(record.get("collection_id"), max_length=128)
        # A persisted job without a complete scope cannot be safely resumed.
        # In particular, never turn it into a default-tenant job during
        # restart recovery.
        if not tenant_id or not workspace_id or not collection_id:
            return None
        job: dict[str, Any] = {
            "job_id": job_id,
            "document_id": _safe_identifier(record.get("document_id"), max_length=256),
            "status": status,
            "stage": record.get("stage", status),
            "progress": record.get("progress", 0.0),
            "attempt": record.get("attempt", 1),
            "error_code": record.get("error_code"),
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "collection_id": collection_id,
            "created_at": record.get("created_at", time.time()),
            "started_at": record.get("started_at"),
            "finished_at": record.get("finished_at"),
            "cancel_requested": record.get("cancel_requested") is True,
            "metadata": record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {},
            "acl_snapshot": record.get("acl_snapshot") if isinstance(record.get("acl_snapshot"), Mapping) else {},
            "retry_count": record.get("retry_count", 0),
            "request_id": record.get("request_id"),
            "correlation_id": record.get("correlation_id"),
            "_journaled": True,
        }
        return job

    def _mark_recovery_required(self, job: dict[str, Any]) -> None:
        job.update(
            {
                "status": "failed",
                "stage": "failed",
                "error_code": "recovery_required",
                "finished_at": time.time(),
                "cancel_requested": False,
            }
        )
        job_id = _safe_identifier(job.get("job_id"), max_length=128)
        if job_id:
            self._job_paths.pop(job_id, None)
        self._journal_upsert(job, None, preserve_request_context=True)

    def _restore_journal(self) -> None:
        """Restore bounded in-memory state and submit bounded local recovery."""

        records = self._journal_records()
        if not records:
            return

        record_by_id: dict[str, Mapping[str, Any]] = {}
        restored_source_paths: set[Path] = set()
        for record in records:
            job = self._recovery_job(record)
            if job is None:
                malformed_job_id = _safe_identifier(record.get("job_id"), max_length=128)
                malformed_source = self._recovery_path(record.get("source_path"))
                cleanup_succeeded = True
                if malformed_source is not None:
                    # A source with an unverifiable scope must never be
                    # resumed under a fallback tenant. Remove only the
                    # validated private staging file; the journal row is
                    # retained as an opaque recovery failure.
                    cleanup_succeeded = self._remove_path(malformed_source)
                if malformed_job_id:
                    self._journal_mark_recovery_required(
                        malformed_job_id,
                        source_path=malformed_source if not cleanup_succeeded else None,
                        retain_source=not cleanup_succeeded,
                    )
                continue
            job_id = job["job_id"]
            record_by_id[job_id] = record
            self._jobs[job_id] = job
            try:
                self._retry_counts[job_id] = min(64, max(0, int(record.get("retry_count", 0))))
            except (TypeError, ValueError):
                self._retry_counts[job_id] = 0

            status = _value(job, "status")
            source = self._recovery_path(record.get("source_path"))
            if source is not None:
                if source not in restored_source_paths:
                    try:
                        size = source.stat().st_size
                        self._staged_bytes += size
                        self._staged_sizes[source] = size
                    except OSError:
                        pass
                    restored_source_paths.add(source)
                if status in _RECOVERABLE_STATES | {"published"}:
                    self._job_paths[job_id] = source
                    if status == "published":
                        document_id = _safe_identifier(_value(job, "document_id"), max_length=256)
                        if document_id:
                            self._document_paths[document_id] = source
                            self._document_order_counter += 1
                            self._document_order[document_id] = self._document_order_counter
                            filename = _safe_identifier(record.get("display_filename"), max_length=256)
                            if filename:
                                self._document_filenames[document_id] = filename
                    else:
                        self._cancel_events.setdefault(job_id, Event())
                elif status in {"failed", "cancelled"}:
                    # Terminal rows are never resumed. Their source reference
                    # is a private cleanup lease and remains durable until the
                    # unlink succeeds.
                    self._job_paths[job_id] = source
                    self._cleanup_job_source(job_id, job, source)
            elif status in _RECOVERABLE_STATES:
                self._mark_recovery_required(job)

        self._evict_if_needed()
        self._evict_document_sources_if_needed()

        candidates = [
            (job_id, job, self._job_paths.get(job_id))
            for job_id, job in self._jobs.items()
            if _value(job, "status") in _RECOVERABLE_STATES and self._job_paths.get(job_id) is not None
        ]
        candidates.sort(key=lambda item: (_safe_order(_value(item[1], "created_at", 0.0)), item[0]))
        for job_id, job, path in candidates[: self.max_jobs]:
            if path is None:
                continue
            cancel_event = self._cancel_events.setdefault(job_id, Event())
            self._async_pending += 1
            record = record_by_id.get(job_id, {})
            display_filename = _safe_identifier(record.get("display_filename"), max_length=256) or path.name
            try:
                self._scheduled_jobs.add(job_id)
                self._submit_async(
                    job_id,
                    self._complete_async_upload,
                    job_id,
                    path,
                    display_filename,
                    _safe_identifier(_value(job, "tenant_id"), max_length=128) or "",
                    _safe_identifier(_value(job, "workspace_id"), max_length=128) or "",
                    _safe_identifier(_value(job, "collection_id"), max_length=128) or "",
                    record.get("request_id"),
                    record.get("correlation_id"),
                    cancel_event,
                )
            except Exception:
                self._scheduled_jobs.discard(job_id)
                self._start_gates.pop(job_id, None)
                self._cancel_events.pop(job_id, None)
                self._async_pending = max(0, self._async_pending - 1)
                self._mark_recovery_required(job)

    # ------------------------------------------------------------- validation
    @staticmethod
    def _display_filename(filename: object) -> tuple[str, str]:
        if not isinstance(filename, str) or not filename.strip() or len(filename) > 256:
            raise IngestionApplicationError("validation_error", "Invalid filename.")
        try:
            from rick_ingestion import sanitize_display_filename

            display = sanitize_display_filename(filename)
        except ImportError:
            display = filename.replace("\\", "/").split("/")[-1].replace("\x00", "")
            display = "".join(ch for ch in display if ch.isprintable()).strip()[:256] or "document"
        suffix = Path(display).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise IngestionApplicationError("unsupported_media_type", "Unsupported filename extension.")
        return display, suffix

    @staticmethod
    def _collection_id(collection_id: object) -> str:
        if not isinstance(collection_id, str) or not collection_id.strip():
            raise IngestionApplicationError("validation_error", "Invalid collection.")
        try:
            from rick_knowledge import normalize_collection_id

            normalized = normalize_collection_id(collection_id)
        except ImportError:
            normalized = collection_id.strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", normalized):
                raise IngestionApplicationError("validation_error", "Invalid collection.")
        except (TypeError, ValueError):
            raise IngestionApplicationError("validation_error", "Invalid collection.") from None
        if normalized == "*":
            raise IngestionApplicationError("validation_error", "Invalid collection.")
        return normalized

    @staticmethod
    def _tenant_id(tenant_id: object) -> str:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise IngestionApplicationError("validation_error", "Invalid tenant.")
        try:
            from rick_knowledge import normalize_tenant_id

            return normalize_tenant_id(tenant_id)
        except (ImportError, TypeError, ValueError):
            raise IngestionApplicationError("validation_error", "Invalid tenant.") from None

    @staticmethod
    def _workspace_id(workspace_id: object) -> str:
        if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id.strip()):
            raise IngestionApplicationError("validation_error", "Invalid workspace.")
        return workspace_id.strip()

    def _new_staging_path(self, suffix: str) -> Path:
        # The user-controlled filename contributes only its validated suffix.
        # The storage basename is always generated by the server.
        for _ in range(4):
            candidate = self.staging_root / f"doc_{secrets.token_hex(16)}{suffix}"
            if not candidate.exists():
                return candidate
        raise IngestionApplicationError("storage_unavailable", "Could not allocate staging storage.")

    @staticmethod
    def _source_reader(source: object, chunk_bytes: int) -> Iterable[bytes]:
        if isinstance(source, bytes):
            for start in range(0, len(source), chunk_bytes):
                yield source[start:start + chunk_bytes]
            return
        if isinstance(source, (bytearray, memoryview)):
            raw = bytes(source)
            for start in range(0, len(raw), chunk_bytes):
                yield raw[start:start + chunk_bytes]
            return
        if isinstance(source, str):
            raw = source.encode("utf-8")
            for start in range(0, len(raw), chunk_bytes):
                yield raw[start:start + chunk_bytes]
            return

        # FastAPI's UploadFile deliberately exposes a synchronous, spooled
        # ``file`` object.  Prefer it so this sync facade never calls the
        # coroutine-valued UploadFile.read without awaiting it.
        file_object = getattr(source, "file", None)
        reader = getattr(file_object, "read", None) if file_object is not None else None
        if not callable(reader):
            reader = getattr(source, "read", None)
        if callable(reader):
            while True:
                chunk = reader(chunk_bytes)
                if inspect.isawaitable(chunk):
                    raise IngestionApplicationError("validation_error", "Async upload source is not supported here.")
                if not chunk:
                    return
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise IngestionApplicationError("validation_error", "Upload source is not bytes.")
                raw = bytes(chunk)
                for start in range(0, len(raw), chunk_bytes):
                    yield raw[start:start + chunk_bytes]
            return

        if isinstance(source, Iterable):
            for chunk in source:
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise IngestionApplicationError("validation_error", "Upload source is not bytes.")
                raw = bytes(chunk)
                for start in range(0, len(raw), chunk_bytes):
                    yield raw[start:start + chunk_bytes]
            return

        raise IngestionApplicationError("validation_error", "Upload source is invalid.")

    def _write_staged(
        self,
        source: object,
        *,
        suffix: str,
        cleanup_scope: tuple[str, str, str] | None = None,
    ) -> tuple[Path, int]:
        def discard(path: Path) -> None:
            self._remove_or_quarantine(path, scope=cleanup_scope)

        self._make_staging_capacity()
        if len(self._job_paths) >= self.max_jobs or self._staged_bytes >= self.max_staged_bytes:
            raise IngestionApplicationError("storage_unavailable", "Staging capacity is exhausted.")
        path = self._new_staging_path(suffix)
        self._staged_sizes[path] = 0
        written = 0
        try:
            with path.open("xb") as target:
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
                for raw_chunk in self._source_reader(source, self.read_chunk_bytes):
                    remaining = self.max_bytes - written
                    if remaining <= 0 or len(raw_chunk) > remaining:
                        raise IngestionApplicationError("request_too_large", "Document exceeds size limit.")
                    if self._staged_bytes + written + len(raw_chunk) > self.max_staged_bytes:
                        raise IngestionApplicationError("storage_unavailable", "Staging capacity is exhausted.")
                    written_count = target.write(raw_chunk)
                    if written_count != len(raw_chunk):
                        raise OSError("short staging write")
                    written += len(raw_chunk)
        except IngestionApplicationError:
            discard(path)
            raise
        except (OSError, ValueError, TypeError):
            discard(path)
            raise IngestionApplicationError("storage_unavailable", "Could not write staging storage.") from None

        if written <= 0:
            discard(path)
            raise IngestionApplicationError("validation_error", "Document is empty.")
        self._staged_bytes += written
        self._staged_sizes[path] = written
        return path, written

    def _make_staging_capacity(self) -> None:
        """Release the oldest retained source before rejecting a new upload.

        Job snapshots remain available until normal job eviction, but source
        retention is deliberately independent and finite. Once the source budget
        is full, an older published source may no longer be available for a
        no-content reindex; callers can still provide bounded replacement data.
        """
        while len(self._job_paths) >= self.max_jobs or self._staged_bytes >= self.max_staged_bytes:
            if not self._evict_one_source():
                return

    def _evict_one_source(self) -> bool:
        def _order_for_job(job: object) -> float:
            return _safe_order(_value(job, "created_at", 0.0))

        candidates: list[tuple[float, Path]] = []
        for document_id, path in self._document_paths.items():
            candidates.append((self._document_order.get(document_id, 0), path))
        if candidates:
            _order, path = min(candidates, key=lambda item: item[0])
        else:
            # Failed/cancelled jobs normally release their source immediately,
            # but retain a safe fallback for injected adapters.
            candidates = [
                (_order_for_job(self._jobs.get(job_id)), path)
                for job_id, path in self._job_paths.items()
                if self._jobs.get(job_id) is not None
                and _value(self._jobs.get(job_id), "status") in _TERMINAL_STATES
            ]
            if not candidates:
                return False
            _order, path = min(candidates, key=lambda item: item[0])

        if not self._remove_path(path):
            # Do not drop the last in-memory reference when unlink fails; the
            # next capacity/restart reconciliation must be able to retry it.
            return False
        for document_id, document_path in list(self._document_paths.items()):
            if document_path == path:
                self._document_paths.pop(document_id, None)
                self._document_order.pop(document_id, None)
                self._document_filenames.pop(document_id, None)
        for job_id, job_path in list(self._job_paths.items()):
            if job_path == path:
                self._job_paths.pop(job_id, None)
                job = self._jobs.get(job_id)
                if job is not None:
                    self._journal_upsert(job, None)
        return True

    def _remove_path(self, path: Path | None) -> bool:
        if path is None:
            return True
        try:
            resolved = path.resolve()
            resolved.relative_to(self.staging_root)
        except (OSError, ValueError):
            return False
        accounted = self._staged_sizes.get(resolved)
        try:
            size = resolved.stat().st_size
        except FileNotFoundError:
            if accounted is not None:
                self._staged_bytes = max(0, self._staged_bytes - accounted)
                self._staged_sizes.pop(resolved, None)
            return True
        except OSError:
            return False
        if accounted is not None and size != accounted:
            # Reconcile an interrupted/externally truncated write before the
            # unlink. The aggregate is then debited by the exact reservation
            # represented by this path rather than by an unrelated file.
            self._staged_bytes = max(0, self._staged_bytes + size - accounted)
            self._staged_sizes[resolved] = size
            accounted = size
        try:
            resolved.unlink()
        except FileNotFoundError:
            if accounted is not None:
                self._staged_bytes = max(0, self._staged_bytes - accounted)
                self._staged_sizes.pop(resolved, None)
            return True
        except OSError:
            return False
        self._staged_bytes = max(0, self._staged_bytes - (accounted if accounted is not None else size))
        self._staged_sizes.pop(resolved, None)
        return True

    def _remember_job_path(self, job: object, path: Path) -> str:
        job_id = _safe_identifier(_value(job, "job_id"), max_length=128)
        if not job_id:
            # The canonical package always supplies an ID; retain a local
            # bounded key for a test double that does not.
            job_id = f"ing-{secrets.token_hex(6)}"
        self._jobs[job_id] = job
        self._job_paths[job_id] = path
        self._evict_if_needed()
        return job_id

    def _evict_if_needed(self) -> None:
        if len(self._jobs) <= self.max_jobs:
            return
        terminal = [
            (job_id, job)
            for job_id, job in self._jobs.items()
            if _value(job, "status") in _TERMINAL_STATES
        ]
        terminal.sort(key=lambda pair: _safe_order(_value(pair[1], "created_at", 0.0)))
        while len(self._jobs) > self.max_jobs and terminal:
            job_id, job = terminal.pop(0)
            path = self._job_paths.get(job_id)
            if path is not None and path not in self._document_paths.values():
                if not self._cleanup_job_source(job_id, job, path):
                    break
            elif path is not None:
                # The document retention reference still owns this source;
                # evicting only the job row must not clear its journal source.
                self._job_paths.pop(job_id, None)
            else:
                self._journal_upsert(job, None)
            self._jobs.pop(job_id, None)
            self._retry_counts.pop(job_id, None)

    def _remember_document_path(self, job: object, path: Path) -> Path | None:
        document_id = _safe_identifier(_value(job, "document_id"), max_length=256)
        if not document_id:
            return None
        previous = self._document_paths.get(document_id)
        self._document_paths[document_id] = path
        self._document_order_counter += 1
        self._document_order[document_id] = self._document_order_counter
        self._evict_document_sources_if_needed()
        return previous if previous is not None and previous != path else None

    def _evict_document_sources_if_needed(self) -> None:
        """Keep retained reindex sources bounded independently of job status."""
        while len(self._document_paths) > self.max_jobs and self._document_order:
            document_id = min(self._document_order, key=self._document_order.get)
            path = self._document_paths.get(document_id)
            if path is None:
                self._document_paths.pop(document_id, None)
                self._document_order.pop(document_id, None)
                self._document_filenames.pop(document_id, None)
                continue
            if not self._remove_path(path):
                # Keep the document/source reference until cleanup succeeds.
                break
            self._document_paths.pop(document_id, None)
            self._document_order.pop(document_id, None)
            self._document_filenames.pop(document_id, None)
            # A job snapshot may still be retained even after its source is no
            # longer eligible for reindex. Drop only that path reference; the
            # safe status DTO remains available until normal job eviction.
            for job_id, job_path in list(self._job_paths.items()):
                if job_path == path:
                    self._job_paths.pop(job_id, None)
                    job = self._jobs.get(job_id)
                    if job is not None:
                        self._journal_upsert(job, None)

    def _published(self, job: object) -> bool:
        return _value(job, "status") == "published"

    def _refresh(self) -> None:
        callback = self.refresh_callback
        if callback is None:
            return
        # Deliberately small callback contract: the retrieval owner closes
        # over its selected providers and rebuilds its own view.
        # Publication and deletion are already committed in the canonical
        # stores when this hook runs. A read-model refresh failure must not
        # rewrite a committed ingestion job as failed; the next explicit
        # refresh/reconciliation can rebuild the derived view.
        try:
            # Refresh is a derived read-model hook. It must not run under the
            # application lock or the canonical operation lock, but admission
            # accounting keeps its dependent stores alive while it runs.
            with self._admitted_operation(allow_stopping=True):
                callback()
        except Exception:
            return

    @contextmanager
    def _mutation_guard(self):
        # Always take the canonical operation lock before the application
        # lock: async ingestion takes these in that order at publication.
        guard = getattr(self.ingestion, "operation_guard", None)
        with self._admitted_operation():
            with guard() if callable(guard) else nullcontext():
                with self._lock:
                    yield

    @contextmanager
    def _publication_guard(self):
        """Linearize async cancellation against the canonical publish gate.

        The package pipeline calls this context while holding its own job
        lock. A cancel request signals cooperatively before reconciliation;
        whichever operation reaches this gate first wins the cancellation /
        publication race, and the public result agrees with that point.
        """
        with self._lock:
            yield

    def _record_result(
        self,
        job: object,
        path: Path,
        *,
        previous_path: Path | None = None,
        display_filename: str | None = None,
        refresh_required: list[bool] | None = None,
    ) -> dict[str, Any]:
        job_id = self._remember_job_path(job, path)
        if self._published(job):
            replaced_path = self._remember_document_path(job, path)
            document_id = _safe_identifier(_value(job, "document_id"), max_length=256)
            if document_id and display_filename:
                self._document_filenames[document_id] = display_filename
            self._journal_upsert(job, path, display_filename=display_filename)
            obsolete_paths = [
                candidate for candidate in (replaced_path, previous_path)
                if candidate is not None and candidate != path
            ]
            seen_paths: set[Path] = set()
            scope = self._job_scope(job)
            for obsolete_path in obsolete_paths:
                if obsolete_path in seen_paths:
                    continue
                seen_paths.add(obsolete_path)
                self._remove_or_quarantine(obsolete_path, scope=scope)
            if refresh_required is not None:
                refresh_required[0] = True
        else:
            # A failed/cancelled attempt never replaces a previously published
            # source.  Its temporary copy can be removed immediately.
            self._cleanup_job_source(
                job_id,
                job,
                path if previous_path != path else None,
                preserve_path=previous_path,
            )
        return safe_job_json(job)

    @classmethod
    def _job_result_matches_scope(
        cls,
        job: object,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
    ) -> bool:
        """Validate a completed adapter result before retaining its source."""
        if not cls._visible(
            job,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            allowed_collection_ids=[collection_id],
        ):
            return False
        if _value(job, "status") == "published":
            return bool(_safe_identifier(_value(job, "document_id"), max_length=256))
        return _value(job, "status") in _TERMINAL_STATES

    def _run_ingest(
        self,
        path: Path,
        *,
        display_filename: str,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        request_id: str | None,
        correlation_id: str | None,
        job_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
        publication_guard: Callable[[], object] | None = None,
    ) -> object:
        try:
            kwargs: dict[str, Any] = {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "collection_id": collection_id,
                "display_filename": display_filename,
                "request_id": request_id,
                "correlation_id": correlation_id,
            }
            if job_id is not None:
                kwargs["job_id"] = job_id
            if cancel_check is not None:
                kwargs["cancel_check"] = cancel_check
            if publication_guard is not None:
                kwargs["publication_guard"] = publication_guard
            return self.ingestion.ingest(
                path,
                **kwargs,
            )
        except IngestionApplicationError:
            raise
        except TimeoutError:
            raise IngestionApplicationError(
                "provider_timeout", "Ingestion provider timed out."
            ) from None
        except (ConnectionError, OSError):
            raise IngestionApplicationError(
                "provider_unavailable", "Ingestion provider is unavailable."
            ) from None
        except Exception:
            raise IngestionApplicationError("ingestion_failed", "Ingestion failed.") from None

    def upload(
        self,
        source: object,
        *,
        filename: str,
        collection_id: str,
        workspace_id: str,
        tenant_id: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        refresh_required = [False]
        with self._admitted_operation():
            with self._mutation_guard():
                result = self._upload(
                    source,
                    filename=filename,
                    collection_id=collection_id,
                    workspace_id=workspace_id,
                    tenant_id=tenant_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    refresh_required=refresh_required,
                )
            if refresh_required[0]:
                self._refresh()
        return result

    @staticmethod
    def _queued_job(*, job_id: str, tenant_id: str, workspace_id: str, collection_id: str) -> dict[str, Any]:
        now = time.time()
        return {
            "job_id": job_id,
            "document_id": None,
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "attempt": 1,
            "error_code": None,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "collection_id": collection_id,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "metadata": {},
        }

    @staticmethod
    def _job_event_fields(
        job: object,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
        worker_id: object | None = None,
        changed: bool | None = None,
    ) -> dict[str, object]:
        """Build the deliberately small event contract from an internal job.

        The application service never forwards the job mapping itself. Scope,
        filenames, metadata, source paths and package error text stay inside
        the authoritative lifecycle boundary; only opaque references and
        bounded state values cross into observability.
        """

        fields: dict[str, object] = {
            "job_ref": opaque_ref(_value(job, "job_id", job)),
        }
        status = _value(job, "status")
        if isinstance(status, str) and status in _JOB_STATES:
            fields["status"] = status
        stage = _value(job, "stage")
        if isinstance(stage, str) and stage in _JOB_STATES:
            fields["stage"] = stage
        try:
            progress = float(_value(job, "progress"))
            if math.isfinite(progress):
                fields["progress"] = round(min(1.0, max(0.0, progress)), 6)
        except (TypeError, ValueError):
            pass
        try:
            fields["attempt"] = min(64, max(1, int(_value(job, "attempt", 1))))
        except (TypeError, ValueError):
            fields["attempt"] = 1
        error_code = _value(job, "error_code")
        if isinstance(error_code, str) and error_code in _SAFE_ERROR_CODES:
            fields["error_code"] = error_code
        if request_id is not None:
            fields["request_ref"] = opaque_ref(request_id)
        if correlation_id is not None:
            fields["correlation_ref"] = opaque_ref(correlation_id)
        if worker_id is not None:
            fields["worker_ref"] = opaque_ref(worker_id)
        if changed is not None:
            fields["changed"] = changed
        return fields

    def _emit_job_event(
        self,
        event_name: str,
        job: object,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
        worker_id: object | None = None,
        changed: bool | None = None,
    ) -> None:
        """Best-effort delivery; callers invoke this only after state locks."""

        self._emit_event_fields(
            event_name,
            self._job_event_fields(
                job,
                request_id=request_id,
                correlation_id=correlation_id,
                worker_id=worker_id,
                changed=changed,
            ),
        )

    def _emit_event_fields(self, event_name: str, fields: Mapping[str, object]) -> None:
        """Deliver an already-snapshotted event after the state transition."""

        sink = self.event_sink
        if sink is None:
            return
        proxy = self._event_sink_proxy
        if proxy is None or getattr(proxy, "_target", None) is not sink:
            proxy = _TrackedEventSink(self, sink)
            self._event_sink_proxy = proxy
        emit_safely(
            proxy,
            event_name,
            fields,
        )

    @staticmethod
    def _terminal_event_name(job: object) -> str:
        status = _value(job, "status")
        if status in _TERMINAL_STATES:
            return f"worker.ingestion.{status}"
        return "worker.ingestion.finished"

    def submit_upload(
        self,
        source: object,
        *,
        filename: str,
        collection_id: str,
        workspace_id: str,
        tenant_id: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Admit one async upload and keep it live through its callbacks."""

        with self._admitted_operation():
            return self._submit_upload(
                source,
                filename=filename,
                collection_id=collection_id,
                workspace_id=workspace_id,
                tenant_id=tenant_id,
                request_id=request_id,
                correlation_id=correlation_id,
            )

    def _submit_upload(
        self,
        source: object,
        *,
        filename: str,
        collection_id: str,
        workspace_id: str,
        tenant_id: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Queue an upload and return its public job before ingestion finishes.

        This is a bounded process-local async path. The source is copied into
        private staging synchronously, then a single fixed worker executes the
        canonical package pipeline. When a local journal is configured, the
        placeholder and final state are durable enough for bounded restart
        recovery; this remains local execution, not a distributed queue.
        """

        with self._lock:
            if not self._accepting_work:
                raise IngestionApplicationError("storage_unavailable", "Ingestion queue is unavailable.")
            if self._async_pending >= self.max_jobs:
                raise IngestionApplicationError("storage_unavailable", "Ingestion capacity is exhausted.")
            display_filename, suffix = self._display_filename(filename)
            resolved_collection = self._collection_id(collection_id)
            resolved_workspace = self._workspace_id(workspace_id)
            resolved_tenant = self._tenant_id(tenant_id)
            path, _size = self._write_staged(
                source,
                suffix=suffix,
                cleanup_scope=(resolved_tenant, resolved_workspace, resolved_collection),
            )
            job_id = f"ing-{secrets.token_hex(6)}"
            placeholder = self._queued_job(
                job_id=job_id,
                tenant_id=resolved_tenant,
                workspace_id=resolved_workspace,
                collection_id=resolved_collection,
            )
            self._jobs[job_id] = placeholder
            self._job_paths[job_id] = path
            self._cancel_events[job_id] = Event()
            self._async_pending += 1
            self._journal_upsert(
                placeholder,
                path,
                display_filename=display_filename,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            self._evict_if_needed()
            start_gate = Event()
            try:
                self._scheduled_jobs.add(job_id)
                self._start_gates[job_id] = start_gate
                self._submit_async(
                    job_id,
                    self._complete_async_upload,
                    job_id,
                    path,
                    display_filename,
                    resolved_tenant,
                    resolved_workspace,
                    resolved_collection,
                    request_id,
                    correlation_id,
                    self._cancel_events[job_id],
                    start_gate,
                )
            except Exception:
                self._scheduled_jobs.discard(job_id)
                self._start_gates.pop(job_id, None)
                placeholder.update({
                    "status": "failed",
                    "stage": "failed",
                    "error_code": "storage_unavailable",
                    "finished_at": time.time(),
                })
                self._cancel_events.pop(job_id, None)
                cleanup_succeeded = self._cleanup_job_source(job_id, placeholder, path)
                if cleanup_succeeded:
                    self._jobs.pop(job_id, None)
                self._async_pending = max(0, self._async_pending - 1)
                raise IngestionApplicationError("storage_unavailable", "Ingestion queue is unavailable.") from None
            result = safe_job_json(placeholder)
            event_fields = self._job_event_fields(
                placeholder,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        # The event callback is intentionally outside the application lock;
        # a reentrant sink may inspect or cancel the just-enqueued job. The
        # worker waits on the gate until this callback returns, preserving the
        # public lifecycle order without invoking user code under the lock.
        try:
            self._emit_event_fields("worker.ingestion.enqueued", event_fields)
        finally:
            start_gate.set()
        return result

    def _complete_async_attempt(
        self,
        *,
        job_id: str,
        path: Path,
        display_filename: str,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        request_id: str | None,
        correlation_id: str | None,
        cancel_event: Event,
        job: object,
        refresh_required: list[bool],
    ) -> object:
        """Run and register one async attempt under one canonical operation."""

        guard = getattr(self.ingestion, "operation_guard", None)
        with guard() if callable(guard) else nullcontext():
            if job is None:
                try:
                    job = self._run_ingest(
                        path,
                        display_filename=display_filename,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        collection_id=collection_id,
                        request_id=request_id,
                        correlation_id=correlation_id,
                        job_id=job_id,
                        cancel_check=cancel_event.is_set,
                        publication_guard=self._publication_guard,
                    )
                except IngestionApplicationError as exc:
                    with self._lock:
                        job = self._jobs.get(job_id) or self._queued_job(
                            job_id=job_id,
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            collection_id=collection_id,
                        )
                        if isinstance(job, dict):
                            job.update({
                                "status": "failed",
                                "stage": "failed",
                                "error_code": exc.code if exc.code in _SAFE_ERROR_CODES else "ingestion_failed",
                                "finished_at": time.time(),
                            })
                except Exception:
                    with self._lock:
                        job = self._jobs.get(job_id) or self._queued_job(
                            job_id=job_id,
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            collection_id=collection_id,
                        )
                        if isinstance(job, dict):
                            job.update({
                                "status": "failed",
                                "stage": "failed",
                                "error_code": "ingestion_failed",
                                "finished_at": time.time(),
                            })

            if not self._job_result_matches_scope(
                job,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                collection_id=collection_id,
            ):
                with self._lock:
                    local_job = self._jobs.get(job_id) or self._queued_job(
                        job_id=job_id,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        collection_id=collection_id,
                    )
                    if isinstance(local_job, dict):
                        local_job.update({
                            "status": "failed",
                            "stage": "failed",
                            "error_code": "ingestion_failed",
                            "finished_at": time.time(),
                        })
                    job = local_job

            try:
                with self._lock:
                    # The application result registration is part of the same
                    # canonical operation as publication. DELETE/cancel must
                    # therefore wait until the source owner is authoritative.
                    self._jobs[job_id] = job
                    self._record_result(
                        job,
                        path,
                        display_filename=display_filename,
                        refresh_required=refresh_required,
                    )
            except Exception:
                # This is reserved for an unexpected application-boundary
                # failure after the canonical call returned. A refresh callback
                # itself is swallowed by _refresh and cannot create a false
                # failed job here.
                with self._lock:
                    fallback = self._jobs.get(job_id)
                    if isinstance(fallback, dict):
                        fallback.update({
                            "status": "failed",
                            "stage": "failed",
                            "error_code": "storage_unavailable",
                            "finished_at": time.time(),
                        })
                    fallback_job = self._jobs.get(job_id)
                    if fallback_job is not None:
                        preserve_path = path if path in self._document_paths.values() else None
                        self._cleanup_job_source(
                            job_id,
                            fallback_job,
                            path,
                            preserve_path=preserve_path,
                        )
                    else:
                        self._remove_or_quarantine(
                            path,
                            scope=(tenant_id, workspace_id, collection_id),
                        )
            return job

    def _complete_async_upload(
        self,
        job_id: str,
        path: Path,
        display_filename: str,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        request_id: str | None,
        correlation_id: str | None,
        cancel_event: Event,
        start_gate: Event | None = None,
    ) -> None:
        if start_gate is not None:
            start_gate.wait()
        with self._admitted_operation(allow_stopping=True):
            start_fields: dict[str, object] | None = None
            refresh_required = [False]
            with self._lock:
                placeholder = self._jobs.get(job_id)
                if isinstance(placeholder, dict):
                    if cancel_event.is_set():
                        placeholder.update({
                            "status": "cancelled",
                            "stage": "cancelled",
                            "cancel_requested": True,
                            "finished_at": time.time(),
                        })
                        self._journal_upsert(placeholder, path, display_filename=display_filename)
                        job: object = placeholder
                    else:
                        placeholder.update({
                            "status": "validating",
                            "stage": "validating",
                            "progress": 0.05,
                            "started_at": time.time(),
                        })
                        self._journal_upsert(placeholder, path, display_filename=display_filename)
                        start_fields = self._job_event_fields(
                            placeholder,
                            request_id=request_id,
                            correlation_id=correlation_id,
                            worker_id=current_thread().name,
                        )
                        job = None
                else:
                    job = None

            if start_fields is not None:
                self._emit_event_fields("worker.ingestion.started", start_fields)

            job = self._complete_async_attempt(
                job_id=job_id,
                path=path,
                display_filename=display_filename,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                collection_id=collection_id,
                request_id=request_id,
                correlation_id=correlation_id,
                cancel_event=cancel_event,
                job=job,
                refresh_required=refresh_required,
            )

            with self._lock:
                self._cancel_events.pop(job_id, None)
                self._scheduled_jobs.discard(job_id)
                self._start_gates.pop(job_id, None)
                self._scheduled_futures.pop(job_id, None)
                self._async_pending = max(0, self._async_pending - 1)

            # Snapshot the terminal state after all authoritative cleanup and
            # only then call optional sinks. The outer admission scope keeps
            # dependent stores alive through the refresh and event callback.
            with self._lock:
                terminal_job = self._jobs.get(job_id) or job
                terminal_event_name = self._terminal_event_name(terminal_job)
                terminal_fields = self._job_event_fields(
                    terminal_job,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    worker_id=current_thread().name,
                )
            if refresh_required[0]:
                self._refresh()
            self._emit_event_fields(terminal_event_name, terminal_fields)

    def _upload(
        self,
        source: object,
        *,
        filename: str,
        collection_id: str,
        workspace_id: str,
        tenant_id: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        refresh_required: list[bool] | None = None,
    ) -> dict[str, Any]:
        display_filename, suffix = self._display_filename(filename)
        resolved_collection = self._collection_id(collection_id)
        resolved_workspace = self._workspace_id(workspace_id)
        resolved_tenant = self._tenant_id(tenant_id)
        path, _size = self._write_staged(
            source,
            suffix=suffix,
            cleanup_scope=(resolved_tenant, resolved_workspace, resolved_collection),
        )
        try:
            job = self._run_ingest(
                path,
                display_filename=display_filename,
                tenant_id=resolved_tenant,
                workspace_id=resolved_workspace,
                collection_id=resolved_collection,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        except IngestionApplicationError:
            self._remove_or_quarantine(
                path,
                scope=(resolved_tenant, resolved_workspace, resolved_collection),
            )
            raise
        if not self._job_result_matches_scope(
            job,
            tenant_id=resolved_tenant,
            workspace_id=resolved_workspace,
            collection_id=resolved_collection,
        ):
            self._remove_or_quarantine(
                path,
                scope=(resolved_tenant, resolved_workspace, resolved_collection),
            )
            raise IngestionApplicationError("ingestion_failed", "Ingestion returned an invalid job scope.")
        return self._record_result(
            job,
            path,
            display_filename=display_filename,
            refresh_required=refresh_required,
        )

    def _stored_path(self, document_id: str) -> Path:
        path = self._document_paths.get(document_id)
        if path is None:
            raise IngestionApplicationError("not_found", "Document source is not available.")
        try:
            path.resolve().relative_to(self.staging_root)
        except (OSError, ValueError):
            raise IngestionApplicationError("not_found", "Document source is not available.") from None
        if not path.is_file():
            raise IngestionApplicationError("not_found", "Document source is not available.")
        return path

    def reindex(
        self,
        document_id: str,
        *,
        collection_id: str,
        workspace_id: str,
        tenant_id: str | None = None,
        source: object | None = None,
        filename: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        refresh_required = [False]
        with self._admitted_operation():
            with self._mutation_guard():
                result = self._reindex(
                    document_id,
                    collection_id=collection_id,
                    workspace_id=workspace_id,
                    tenant_id=tenant_id,
                    source=source,
                    filename=filename,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    refresh_required=refresh_required,
                )
            if refresh_required[0]:
                self._refresh()
        return result

    def _reindex(
        self,
        document_id: str,
        *,
        collection_id: str,
        workspace_id: str,
        tenant_id: str | None = None,
        source: object | None = None,
        filename: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        refresh_required: list[bool] | None = None,
    ) -> dict[str, Any]:
        safe_document_id = _safe_identifier(document_id, max_length=256)
        if not safe_document_id:
            raise IngestionApplicationError("validation_error", "Invalid document.")
        resolved_tenant = self._tenant_id(tenant_id)
        resolved_collection = self._collection_id(collection_id)
        resolved_workspace = self._workspace_id(workspace_id)
        knowledge = getattr(self.ingestion, "knowledge", None)
        get_document = getattr(knowledge, "get_document", None)
        if callable(get_document):
            existing = get_document(safe_document_id)
            existing_tenant = _value(existing, "tenant_id") if existing is not None else None
            existing_workspace = _value(existing, "workspace_id") if existing is not None else None
            existing_collection = _value(existing, "collection_id") if existing is not None else None
            if (
                existing is None
                or _value(existing, "status") == "deleted"
                or not isinstance(existing_tenant, str)
                or not isinstance(existing_workspace, str)
                or not isinstance(existing_collection, str)
                or existing_tenant != resolved_tenant
                or existing_workspace != resolved_workspace
                or existing_collection != resolved_collection
            ):
                raise IngestionApplicationError("not_found", "Document is outside the requested scope.")
        previous_path = self._stored_path(safe_document_id) if source is None else self._document_paths.get(safe_document_id)

        if source is None:
            path = self._stored_path(safe_document_id)
            display_filename = filename or self._document_filenames.get(safe_document_id) or path.name
            # The generated suffix is trusted only after checking the stored
            # path, never from a request path.
            display_filename, _suffix = self._display_filename(display_filename)
            staged_path = path
        else:
            display_filename, suffix = self._display_filename(filename or getattr(source, "filename", "document.txt"))
            staged_path, _size = self._write_staged(
                source,
                suffix=suffix,
                cleanup_scope=(resolved_tenant, resolved_workspace, resolved_collection),
            )

        try:
            reindex = getattr(self.ingestion, "reindex", None)
            if not callable(reindex):
                raise IngestionApplicationError("ingestion_failed", "Reindex is unavailable.")
            try:
                job = reindex(
                    safe_document_id,
                    staged_path,
                    tenant_id=resolved_tenant,
                    workspace_id=resolved_workspace,
                    collection_id=resolved_collection,
                    display_filename=display_filename,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
            except Exception:
                raise IngestionApplicationError("ingestion_failed", "Reindex failed.") from None
        except IngestionApplicationError:
            if source is not None:
                self._remove_or_quarantine(
                    staged_path,
                    scope=(resolved_tenant, resolved_workspace, resolved_collection),
                )
            raise
        if not self._job_matches_scope(
            job,
            document_id=safe_document_id,
            tenant_id=resolved_tenant,
            workspace_id=resolved_workspace,
            collection_id=resolved_collection,
            require_document_id=True,
        ):
            if source is not None:
                self._remove_or_quarantine(
                    staged_path,
                    scope=(resolved_tenant, resolved_workspace, resolved_collection),
                )
            raise IngestionApplicationError("ingestion_failed", "Reindex returned an invalid job scope.")
        result_document_id = _safe_identifier(_value(job, "document_id"), max_length=256)
        if result_document_id != safe_document_id and not callable(get_document):
            if source is not None:
                self._remove_or_quarantine(
                    staged_path,
                    scope=(resolved_tenant, resolved_workspace, resolved_collection),
                )
            raise IngestionApplicationError("ingestion_failed", "Reindex returned an unverifiable document.")
        if callable(get_document) and result_document_id is not None:
            result_document = get_document(result_document_id)
            if (
                result_document is None
                or _value(result_document, "tenant_id") != resolved_tenant
                or _value(result_document, "workspace_id") != resolved_workspace
                or _value(result_document, "collection_id") != resolved_collection
            ):
                if source is not None:
                    self._remove_or_quarantine(
                        staged_path,
                        scope=(resolved_tenant, resolved_workspace, resolved_collection),
                    )
                raise IngestionApplicationError("ingestion_failed", "Reindex produced an invalid document scope.")
        result = self._record_result(
            job,
            staged_path,
            previous_path=previous_path,
            display_filename=display_filename,
            refresh_required=refresh_required,
        )
        if result.get("status") == "published" and result.get("document_id") != safe_document_id:
            # The old version remains an unpublished metadata record, but its
            # temporary source is no longer a valid reindex input after the
            # replacement is published.
            self._document_paths.pop(safe_document_id, None)
            self._document_order.pop(safe_document_id, None)
            self._document_filenames.pop(safe_document_id, None)
        return result

    def retry(
        self,
        job_id: str,
        *,
        source: object,
        filename: str,
        workspace_id: str,
        allowed_collection_ids: Iterable[str],
        tenant_id: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Run an explicit new attempt using caller-supplied bounded content.

        Failed sources are not retained merely to make a retry convenient. A
        client must resubmit bounded input, keeping the process-local storage
        lifetime finite. The failed attempt remains immutable; the returned job
        is a new attempt and cannot relabel an already-published document.
        """
        refresh_required = [False]
        with self._admitted_operation():
            with self._mutation_guard():
                allowed_collection_ids = list(allowed_collection_ids)
                job = self._jobs.get(job_id)
                if job is None or not self._visible(
                    job, tenant_id=tenant_id, workspace_id=workspace_id,
                    allowed_collection_ids=allowed_collection_ids
                ):
                    return None
                status = _value(job, "status")
                if status not in {"failed", "cancelled"} or not _retryable(_value(job, "error_code")):
                    raise IngestionApplicationError("conflict", "This job is not retryable.")
                retry_count = self._retry_counts.get(job_id, 0)
                if retry_count >= DEFAULT_MAX_RETRIES:
                    raise IngestionApplicationError("conflict", "Retry budget exhausted.")
                # Consume the budget before executing. A malformed or failed new
                # attempt must not create an unbounded retry oracle.
                self._retry_counts[job_id] = retry_count + 1
                persisted_retry_budget = self._journal_upsert(
                    job,
                    self._job_paths.get(job_id),
                    retry_count=retry_count + 1,
                    acl_snapshot={
                        "tenant_id": _value(job, "tenant_id"),
                        "workspace_id": workspace_id,
                        "collection_id": _value(job, "collection_id"),
                        "allowed_collection_ids": allowed_collection_ids,
                    },
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                if self.job_journal is not None and not persisted_retry_budget:
                    # A process-memory counter is not sufficient when the
                    # service advertises restart recovery. Refuse the attempt
                    # rather than allowing a restart to reset the retry budget.
                    self._retry_counts[job_id] = retry_count
                    raise IngestionApplicationError(
                        "storage_unavailable", "Retry durability is unavailable."
                    )
                collection_id = _value(job, "collection_id")
                if not isinstance(collection_id, str) or not collection_id:
                    raise IngestionApplicationError("validation_error", "Invalid job scope.")
                retry_tenant = _safe_identifier(_value(job, "tenant_id"), max_length=128)
                if retry_tenant is None:
                    raise IngestionApplicationError("validation_error", "Invalid job scope.")
                result = self._upload(
                    source,
                    filename=filename,
                    collection_id=collection_id,
                    workspace_id=workspace_id,
                    tenant_id=retry_tenant,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    refresh_required=refresh_required,
                )
            if refresh_required[0]:
                self._refresh()
        return result

    def delete_document(
        self,
        document_id: str,
        *,
        workspace_id: str,
        allowed_collection_ids: Iterable[str],
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        refresh_required = [False]
        try:
            with self._admitted_operation():
                with self._mutation_guard():
                    result = self._delete_document(
                        document_id,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        allowed_collection_ids=allowed_collection_ids,
                        refresh_required=refresh_required,
                    )
                if refresh_required[0]:
                    self._refresh()
        except IngestionApplicationError:
            raise
        return result

    def _delete_document(
        self,
        document_id: str,
        *,
        workspace_id: str,
        allowed_collection_ids: Iterable[str],
        tenant_id: str | None = None,
        refresh_required: list[bool] | None = None,
    ) -> dict[str, Any] | None:
        """Delete one authorized document with a compensating local transaction.

        The in-memory knowledge/vector implementations are the local phase
        adapters. A bounded point/metadata snapshot restores the prior
        published state when either half fails; an adapter without a restore
        seam is hidden from the public library instead of being reported as a
        successful delete.
        """
        safe_document_id = _safe_identifier(document_id, max_length=256)
        if not safe_document_id:
            return None
        knowledge = getattr(self.ingestion, "knowledge", None)
        vectors = getattr(self.ingestion, "vectors", None)
        getter = getattr(knowledge, "get_document", None)
        if not callable(getter) or vectors is None:
            raise IngestionApplicationError("storage_unavailable", "Document storage is unavailable.")
        document = getter(safe_document_id)
        if document is None or _value(document, "status") == "deleted":
            return None
        document_tenant = _value(document, "tenant_id")
        if not isinstance(document_tenant, str) or not document_tenant or document_tenant != tenant_id:
            return None
        if _value(document, "workspace_id") != workspace_id:
            return None
        collection_id = _value(document, "collection_id")
        allowed = set(allowed_collection_ids)
        if not isinstance(collection_id, str) or (collection_id not in allowed and "*" not in allowed):
            return None

        delete_points = getattr(vectors, "delete_document", None)
        delete_metadata = getattr(knowledge, "delete_document", None)
        if not callable(delete_points) or not callable(delete_metadata):
            raise IngestionApplicationError("storage_unavailable", "Document storage is unavailable.")

        # Local adapters expose a bounded point snapshot, allowing the
        # metadata tombstone to be compensated if either half of the delete
        # fails. A production adapter without this seam must fail closed below
        # rather than claim a stronger distributed transaction than it has.
        point_snapshot: list[dict] = []
        all_points = getattr(vectors, "all_points", None)
        point_snapshot_available = callable(all_points)
        if callable(all_points):
            try:
                try:
                    points = all_points(limit=MAX_POINT_SNAPSHOT)
                except TypeError:
                    points = all_points()
                for index, point in enumerate(islice(points, MAX_POINT_SNAPSHOT + 1)):
                    if index == MAX_POINT_SNAPSHOT:
                        raise ValueError("complete point snapshot exceeds read limit")
                    payload = point.get("payload") if isinstance(point, Mapping) else None
                    if (
                        isinstance(point, Mapping)
                        and isinstance(payload, Mapping)
                        and payload.get("document_id") == safe_document_id
                        and payload.get("collection_id") == collection_id
                    ):
                        point_copy = dict(point)
                        point_copy["payload"] = dict(payload)
                        if isinstance(point_copy.get("vector"), (list, tuple)):
                            point_copy["vector"] = list(point_copy["vector"])
                        point_snapshot.append(point_copy)
            except Exception:
                raise IngestionApplicationError(
                    "storage_unavailable", "Could not snapshot document for deletion."
                ) from None
        document_snapshot = copy.deepcopy(document)
        get_chunks = getattr(knowledge, "get_chunks", None)
        try:
            if not callable(get_chunks):
                raise RuntimeError("chunk snapshot is unavailable")
            chunk_snapshot = copy.deepcopy(get_chunks(safe_document_id))
            if not isinstance(chunk_snapshot, list):
                raise RuntimeError("chunk snapshot is incomplete")
        except Exception:
            raise IngestionApplicationError(
                "storage_unavailable", "Could not snapshot document for deletion."
            ) from None
        try:
            deleted_points = int(delete_points(safe_document_id, collection_id))
            deleted_chunks = int(delete_metadata(safe_document_id))
        except Exception:
            points_restored = False
            if point_snapshot_available:
                try:
                    if point_snapshot:
                        for offset in range(0, len(point_snapshot), 1_000):
                            batch = point_snapshot[offset:offset + 1_000]
                            if vectors.upsert_points(batch) != len(batch):
                                raise RuntimeError("incomplete compensation write")
                    points_restored = True
                except Exception:
                    pass
            metadata_restored = False
            restore_document = getattr(knowledge, "upsert_document", None)
            if callable(restore_document):
                try:
                    restore_document(copy.deepcopy(document_snapshot))
                    replace_chunks = getattr(knowledge, "replace_document_chunks", None)
                    if callable(replace_chunks):
                        replace_chunks(safe_document_id, chunk_snapshot)
                    metadata_restored = True
                except Exception:
                    pass
            if not (points_restored and metadata_restored):
                # If either side of the pair cannot prove restoration, hide
                # the record from the public library until reconciliation
                # repairs the storage pair. In particular, restored vectors
                # must never be searchable behind a tombstoned/unknown
                # metadata record.
                set_status = getattr(knowledge, "set_document_status", None)
                if callable(set_status):
                    try:
                        set_status(safe_document_id, "unpublished")
                    except Exception:
                        pass
            if refresh_required is not None:
                refresh_required[0] = True
            raise IngestionApplicationError("storage_unavailable", "Could not delete document.") from None

        path = self._document_paths.pop(safe_document_id, None)
        self._document_order.pop(safe_document_id, None)
        self._document_filenames.pop(safe_document_id, None)
        if path is not None:
            owners = [
                (job_id, job)
                for job_id, job_path in self._job_paths.items()
                if job_path == path and (job := self._jobs.get(job_id)) is not None
            ]
            path_has_other_document_owner = path in self._document_paths.values()
            if owners:
                for job_id, job in owners:
                    if path_has_other_document_owner:
                        self._job_paths.pop(job_id, None)
                        self._journal_upsert(job, None)
                    else:
                        self._cleanup_job_source(job_id, job, path)
            else:
                self._remove_or_quarantine(
                    path,
                    scope=(tenant_id, workspace_id, collection_id),
                )
        if refresh_required is not None:
            refresh_required[0] = True
        return {
            "document_id": safe_document_id,
            "workspace_id": workspace_id,
            "collection_id": collection_id,
            "deleted": True,
            "deleted_points": deleted_points,
            "deleted_chunks": deleted_chunks,
        }

    # --------------------------------------------------------------- jobs ----
    @staticmethod
    def _visible(
        job: object,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        allowed_collection_ids: Iterable[str] | None,
    ) -> bool:
        job_tenant = _value(job, "tenant_id")
        job_workspace = _value(job, "workspace_id")
        job_collection = _value(job, "collection_id")
        if not all(isinstance(value, str) and value for value in (job_tenant, job_workspace, job_collection)):
            return False
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            return False
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            return False
        if allowed_collection_ids is None:
            return False
        if job_tenant != tenant_id.strip():
            return False
        if job_workspace != workspace_id.strip():
            return False
        collection = job_collection
        allowed = set(allowed_collection_ids)
        if collection not in allowed and "*" not in allowed:
            return False
        return True

    @classmethod
    def _job_matches_scope(
        cls,
        job: object,
        *,
        document_id: str,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        require_document_id: bool = False,
    ) -> bool:
        """Require a canonical adapter result to preserve the request scope."""
        return cls._visible(
            job,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            allowed_collection_ids=[collection_id],
        ) and (
            not require_document_id
            or bool(_safe_identifier(_value(job, "document_id"), max_length=256))
        )

    def get_status(
        self,
        job_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            return self._get_status(
                job_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                allowed_collection_ids=allowed_collection_ids,
            )

    def _get_status(
        self,
        job_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if job is None or not self._visible(
            job, tenant_id=tenant_id, workspace_id=workspace_id,
            allowed_collection_ids=allowed_collection_ids,
        ):
            return None
        return safe_job_json(job)

    status = get_status

    def cancel(
        self,
        job_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> dict[str, Any] | None:
        with self._admitted_operation():
            return self._cancel(
                job_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                allowed_collection_ids=allowed_collection_ids,
            )

    def _cancel(
        self,
        job_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> dict[str, Any] | None:
        # Signal cooperatively before waiting on the canonical mutation guard.
        # Provider/parser I/O can take time, and cancellation must be able to
        # reach the pipeline while an async attempt owns that guard. The final
        # reconciliation below still takes the guard before app state, so a
        # publication that crossed its gate remains authoritative.
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or not self._visible(
                job, tenant_id=tenant_id, workspace_id=workspace_id,
                allowed_collection_ids=allowed_collection_ids,
            ):
                return None
            if _value(job, "status") in _TERMINAL_STATES:
                result = safe_job_json(job)
                result["cancelled"] = False
                return result
            cancel_event = self._cancel_events.get(job_id)
            if cancel_event is None:
                result = safe_job_json(job)
                result["cancelled"] = False
                return result
            cancel_event.set()

        changed = False
        try:
            changed = bool(self.ingestion.cancel(job_id))
        except Exception:
            changed = False

        guard = getattr(self.ingestion, "operation_guard", None)
        with guard() if callable(guard) else nullcontext():
            with self._lock:
                job = self._jobs.get(job_id) or job
                canonical_job = None
                status_getter = getattr(self.ingestion, "get_status", None)
                if callable(status_getter):
                    try:
                        canonical_job = status_getter(job_id)
                    except Exception:
                        canonical_job = None
                if canonical_job is not None and self._visible(
                    canonical_job,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    allowed_collection_ids=allowed_collection_ids,
                ) and _value(canonical_job, "status") in _TERMINAL_STATES:
                    # A publication that won before cancellation is
                    # authoritative. A canonical cancellation/failure is also
                    # adopted so the response cannot contradict package state.
                    job = canonical_job
                    self._jobs[job_id] = canonical_job
                    changed = _value(canonical_job, "status") == "cancelled"
                    self._journal_upsert(canonical_job, self._job_paths.get(job_id))
                else:
                    # If the adapter has no status lookup, the event is still
                    # the safe cooperative cancellation request.
                    changed = True if canonical_job is None else changed
                    if isinstance(job, dict):
                        job.update({
                            "status": "cancelled",
                            "stage": "cancelled",
                            "cancel_requested": True,
                            "finished_at": time.time(),
                        })
                        self._journal_upsert(job, self._job_paths.get(job_id))

                if (
                    job_id not in self._scheduled_jobs
                    and _value(job, "status") == "cancelled"
                ):
                    path = self._job_paths.get(job_id)
                    self._cancel_events.pop(job_id, None)
                    if path is not None and path not in self._document_paths.values():
                        self._cleanup_job_source(job_id, job, path)
                    elif path is not None:
                        # A cancelled retry may still point at the prior
                        # published source. That source belongs to the
                        # document, not to the cancelled attempt.
                        self._job_paths.pop(job_id, None)
                        self._journal_upsert(job, None)
                result = safe_job_json(job)
                result["cancelled"] = changed
                return result

    cancel_job = cancel

    def list_jobs(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return self._list_jobs(
                workspace_id=workspace_id,
                tenant_id=tenant_id,
                allowed_collection_ids=allowed_collection_ids,
                limit=limit,
            )

    def _list_jobs(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            bounded_limit = min(100, max(1, int(limit)))
        except (TypeError, ValueError):
            bounded_limit = 100
        jobs = [
            job
            for job in self._jobs.values()
            if self._visible(
                job, tenant_id=tenant_id, workspace_id=workspace_id,
                allowed_collection_ids=allowed_collection_ids,
            )
        ]
        jobs.sort(key=lambda item: float(_value(item, "created_at", 0.0) or 0.0), reverse=True)
        return [safe_job_json(job) for job in jobs[:bounded_limit]]

    def _cancel_queued_for_shutdown(
        self,
        *,
        deadline: float | None = None,
        nonblocking: bool = False,
    ) -> tuple[list[dict[str, object]], bool]:
        """Cancel queued futures without waiting past the shared deadline."""

        cancelled_events: list[dict[str, object]] = []
        if nonblocking:
            acquired = self._lock.acquire(blocking=False)
        elif deadline is None:
            acquired = self._lock.acquire()
        else:
            acquired = self._lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
        if not acquired:
            return [], False
        complete = True
        try:
            for job_id, future in list(self._scheduled_futures.items()):
                if deadline is not None and time.monotonic() >= deadline:
                    complete = False
                    break
                start_gate = self._start_gates.get(job_id)
                if start_gate is not None:
                    # A submission can be between future start and the
                    # enqueued-event callback. Releasing this gate prevents a
                    # reentrant shutdown from waiting on that callback.
                    start_gate.set()
                cancel = getattr(future, "cancel", None)
                if not callable(cancel) or not cancel():
                    # A running future cannot be preempted. Its event is set
                    # so cooperative package stages stop before publication;
                    # shutdown(wait=True) then preserves cleanup ordering.
                    cancel_event = self._cancel_events.get(job_id)
                    if cancel_event is not None:
                        cancel_event.set()
                    continue

                job = self._jobs.get(job_id)
                path = self._job_paths.get(job_id)
                if isinstance(job, dict):
                    job.update({
                        "status": "cancelled",
                        "stage": "cancelled",
                        "cancel_requested": True,
                        "finished_at": time.time(),
                    })
                    if path is not None and path in self._document_paths.values():
                        self._job_paths.pop(job_id, None)
                        self._journal_upsert(job, None)
                    else:
                        self._cleanup_job_source(job_id, job, path)
                    cancelled_events.append(
                        self._job_event_fields(job, worker_id="app-shutdown")
                    )
                elif path is not None:
                    self._remove_path(path)
                self._scheduled_futures.pop(job_id, None)
                self._start_gates.pop(job_id, None)
                self._scheduled_jobs.discard(job_id)
                self._cancel_events.pop(job_id, None)
                self._async_pending = max(0, self._async_pending - 1)
        finally:
            self._lock.release()
        return cancelled_events, complete

    def _executor_threads_alive(self) -> bool:
        return any(thread.is_alive() for thread in getattr(self._executor, "_threads", ()))

    def _request_pending_shutdown_cancellation(
        self,
        *,
        deadline: float | None,
        nonblocking: bool,
    ) -> bool:
        """Signal work that the bounded reconciler could not enumerate.

        ``ThreadPoolExecutor.shutdown(cancel_futures=True)`` can cancel a
        future without entering the application callback that owns its
        staging path, job row, and pending counter. When the lifecycle
        deadline expires before our reconciler visits every future, leave the
        futures runnable and make their cooperative entry path perform the
        normal terminal cleanup instead.
        """
        if nonblocking:
            acquired = self._lock.acquire(blocking=False)
        elif deadline is None:
            acquired = self._lock.acquire()
        else:
            acquired = self._lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
        if not acquired:
            return False
        try:
            for job_id in tuple(self._scheduled_futures):
                cancel_event = self._cancel_events.get(job_id)
                if cancel_event is not None:
                    cancel_event.set()
                start_gate = self._start_gates.get(job_id)
                if start_gate is not None:
                    start_gate.set()
        finally:
            self._lock.release()
        return True

    def _deliver_shutdown_events(
        self,
        events: list[dict[str, object]],
        *,
        deadline: float | None,
    ) -> None:
        """Deliver shutdown telemetry without making a finite stop unbounded.

        A caller-owned event sink is deliberately outside the ingestion
        correctness boundary. With a finite deadline it therefore receives a
        best-effort daemon delivery and cannot hold up worker/store shutdown;
        the normal no-deadline path remains synchronous for deterministic
        local callers.
        """
        if not events:
            return
        if deadline is None:
            for fields in events:
                self._emit_event_fields("worker.ingestion.cancelled", fields)
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0 or self.event_sink is None:
            return
        delivered = Event()

        def deliver() -> None:
            try:
                for fields in events:
                    self._emit_event_fields("worker.ingestion.cancelled", fields)
            finally:
                delivered.set()

        try:
            Thread(
                target=deliver,
                name="rick-ingestion-shutdown-telemetry",
                daemon=True,
            ).start()
        except RuntimeError:
            return
        delivered.wait(max(0.0, deadline - time.monotonic()))

    def close(self, *, timeout: float | None = 5.0) -> bool:
        """Shutdown and remove only an automatically created private root."""

        if timeout is not None:
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or timeout < 0
                or not math.isfinite(float(timeout))
            ):
                raise ValueError("close timeout must be finite and non-negative")
            timeout = float(timeout)
        deadline = None if timeout is None else time.monotonic() + timeout
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        if not self.shutdown(wait=True, timeout=remaining):
            return False
        if not self._owns_staging_root:
            return True

        with self._shutdown_lock:
            if self._staging_root_closed:
                return True
            root = self.staging_root
            temporary_root = Path(tempfile.gettempdir()).resolve()
            try:
                if root.is_symlink() or root.parent != temporary_root or not root.name.startswith("rick-ingestion-"):
                    return False
            except OSError:
                return False

            cleanup_thread = self._staging_cleanup_thread
            if cleanup_thread is None:
                self._staging_cleanup_error = None

                def remove_root() -> None:
                    try:
                        shutil.rmtree(root)
                    except FileNotFoundError:
                        return
                    except Exception as exc:  # pragma: no cover - OS boundary
                        self._staging_cleanup_error = exc

                cleanup_thread = Thread(
                    target=remove_root,
                    name="rick-ingestion-staging-cleanup",
                    daemon=True,
                )
                self._staging_cleanup_thread = cleanup_thread
                try:
                    cleanup_thread.start()
                except RuntimeError:  # pragma: no cover - interpreter boundary
                    self._staging_cleanup_thread = None
                    return False

        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        if remaining is None:
            cleanup_thread.join()
        else:
            cleanup_thread.join(remaining)
        if cleanup_thread.is_alive():
            return False

        with self._shutdown_lock:
            if self._staging_root_closed:
                return True
            cleanup_error = self._staging_cleanup_error
            self._staging_cleanup_thread = None
            self._staging_cleanup_error = None
            if cleanup_error is not None:
                return False
            self._staging_root_closed = True
            return True

    def shutdown(self, *, wait: bool = False, timeout: float | None = None) -> bool:
        """Stop admission, cancel queued work, and release executor threads.

        The admission flag is separate from ``ThreadPoolExecutor``'s private
        state so a concurrent request cannot stage a new source while the
        executor is being closed. Repeated calls are safe; a later
        ``wait=True`` call still joins a shutdown previously requested with
        ``wait=False``. When a finite ``timeout`` is supplied, a
        cancellation-resistant worker returns ``False`` without closing or
        preempting that thread; callers must keep dependent resources open.
        """

        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0 or not math.isfinite(float(timeout)):
                raise ValueError("shutdown timeout must be finite and non-negative")
            timeout = float(timeout)

        # Start the deadline before queued-source cleanup and telemetry. A
        # finite shutdown budget covers the complete local stop operation.
        deadline = (
            time.monotonic() + timeout
            if timeout is not None
            else (time.monotonic() if not wait else None)
        )

        # Admission is a separate, short critical section. A synchronous
        # mutation may legitimately hold the application lock while doing
        # canonical I/O; shutdown must still close admission immediately and
        # then wait/bound that in-flight operation.
        self._set_accepting_work(False)
        cleanup_events_deadline = None if (not wait or timeout is None) else deadline
        cancelled_events, cleanup_complete = self._cancel_queued_for_shutdown(
            deadline=cleanup_events_deadline,
            nonblocking=not wait,
        )
        if not cleanup_complete:
            # Do not let the executor cancel futures behind the application's
            # bookkeeping boundary. Their cooperative callback must run so it
            # can release private staging references and pending counters.
            self._request_pending_shutdown_cancellation(
                deadline=deadline,
                nonblocking=not wait,
            )
        self._deliver_shutdown_events(cancelled_events, deadline=deadline)
        with self._admission_condition:
            reentrant_operation = self._active_operation_threads.get(get_ident(), 0) > 0
            reentrant_event_callback = self._event_callback_threads.get(get_ident(), 0) > 0
        with self._shutdown_lock:
            if not wait:
                self._executor.shutdown(wait=False, cancel_futures=cleanup_complete)
                with self._admission_condition:
                    no_admitted_work = self._active_operations == 0 and self._event_callbacks == 0
                return cleanup_complete and not self._executor_threads_alive() and no_admitted_work
            if reentrant_operation:
                # A sink or adapter can call shutdown synchronously from an
                # admitted operation. It must release queued gates without
                # waiting for the operation that is currently on this stack;
                # the owning caller can retry after it returns.
                self._executor.shutdown(wait=False, cancel_futures=cleanup_complete)
                return False
            if reentrant_event_callback:
                # A bounded sink callback may synchronously call shutdown from
                # its own delivery thread. Waiting for the caller that is
                # waiting for this callback would deadlock; leave cleanup
                # retryable and let the outer caller finish the callback.
                self._executor.shutdown(wait=False, cancel_futures=cleanup_complete)
                return False
            if current_thread() in getattr(self._executor, "_threads", ()):
                # A worker cannot join itself. Returning a visible incomplete
                # result is safer than deadlocking or closing its stores.
                return False
            self._executor.shutdown(wait=False, cancel_futures=cleanup_complete)
            if not cleanup_complete:
                return False
            if not self._wait_for_active_operations(deadline):
                return False
            if timeout is None:
                # The active-operation wait above includes the local worker;
                # the executor join is therefore only normal bookkeeping.
                self._executor.shutdown(wait=True, cancel_futures=True)
                return True

            waiter = Event()
            while self._executor_threads_alive():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                waiter.wait(min(0.01, remaining))
            # The threads are already gone, so this join is non-blocking but
            # completes the executor's normal shutdown bookkeeping.
            self._executor.shutdown(wait=True, cancel_futures=True)
            return time.monotonic() <= deadline


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_JOBS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MAX_STAGED_BYTES",
    "DEFAULT_READ_CHUNK_BYTES",
    "IngestionApplicationError",
    "IngestionApplicationService",
    "SUPPORTED_EXTENSIONS",
    "job_to_json",
    "safe_job_json",
    "serialize_job",
]
