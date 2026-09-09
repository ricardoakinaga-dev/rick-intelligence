"""API boundary for object storage plus the transactional ingestion queue.

Uploads are copied once into a tenant/workspace/source namespace, then a small
queue payload is committed. Parsing and vector publication happen in the
separate worker handler. This module does not start a thread or open a client;
all durable adapters are injected by the composition root.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import base64
import hashlib
import inspect
from pathlib import Path
import time
import uuid

from core.telemetry import emit_safely, opaque_ref
from rick_ingestion.parsers import SUPPORTED_EXTENSIONS, sanitize_display_filename
from rick_storage import ObjectScope

from services.ingestion_service import IngestionApplicationError


_MAX_FILENAME = 256
_MAX_IDEMPOTENCY_KEY = 128
_PUBLIC_ERROR_CODES = frozenset({
    "validation_error", "unsupported_media_type", "request_too_large",
    "not_found", "storage_unavailable", "provider_timeout",
    "provider_unavailable", "vector_store_unavailable", "lock_unavailable",
    "ingestion_failed", "recovery_required", "conflict",
})
_QUEUE_STATUS = frozenset({"queued", "leased", "processing", "published", "failed", "cancelled", "dead"})


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _required_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise IngestionApplicationError("validation_error")
    candidate = value.strip()
    if not candidate or len(candidate) > maximum or any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate):
        raise IngestionApplicationError("validation_error")
    return candidate


def _read_source(source: object, *, max_bytes: int) -> bytes:
    """Read a synchronous upload source with one finite byte budget."""

    if isinstance(source, str):
        data = source.encode("utf-8")
        if not data or len(data) > max_bytes:
            raise IngestionApplicationError("request_too_large" if len(data) > max_bytes else "validation_error")
        return data
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
        if not data or len(data) > max_bytes:
            raise IngestionApplicationError("request_too_large" if len(data) > max_bytes else "validation_error")
        return data

    file_object = getattr(source, "file", None)
    reader = getattr(file_object, "read", None) if file_object is not None else None
    if not callable(reader):
        reader = getattr(source, "read", None)
    if callable(reader):
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = reader(min(64 * 1024, max_bytes + 1 - total))
            if inspect.isawaitable(chunk):
                raise IngestionApplicationError("validation_error")
            if not chunk:
                break
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise IngestionApplicationError("validation_error")
            raw = bytes(chunk)
            total += len(raw)
            if total > max_bytes:
                raise IngestionApplicationError("request_too_large")
            chunks.append(raw)
        if not chunks:
            raise IngestionApplicationError("validation_error")
        return b"".join(chunks)

    if isinstance(source, Iterable):
        chunks = []
        total = 0
        for chunk in source:
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise IngestionApplicationError("validation_error")
            raw = bytes(chunk)
            total += len(raw)
            if total > max_bytes:
                raise IngestionApplicationError("request_too_large")
            chunks.append(raw)
        if not chunks:
            raise IngestionApplicationError("validation_error")
        return b"".join(chunks)
    raise IngestionApplicationError("validation_error")


def _accepts_scope(method: object) -> bool:
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    names = {parameter.name for parameter in parameters}
    return {"tenant_id", "workspace_id"}.issubset(names) or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )


def _scoped_call(method: Callable[..., object], *args: object, tenant_id: str, workspace_id: str, **kwargs: object) -> object:
    if not _accepts_scope(method):
        raise TypeError("durable adapter does not accept tenant/workspace scope")
    return method(*args, tenant_id=tenant_id, workspace_id=workspace_id, **kwargs)


def _safe_error_code(value: object) -> str | None:
    return value if isinstance(value, str) and value in _PUBLIC_ERROR_CODES else None


class PostgresIngestionApplicationService:
    """Durable upload/job facade consumed by the API routes."""

    runtime_metadata = {
        "execution": "external-worker",
        "durability": "postgres-s3",
    }

    def __init__(
        self,
        *,
        queue: object,
        object_store: object,
        knowledge: object | None = None,
        vectors: object | None = None,
        max_bytes: int = 50 * 1024 * 1024,
        max_jobs: int = 256,
        event_sink: object | None = None,
    ) -> None:
        if queue is None or not callable(getattr(queue, "enqueue", None)):
            raise ValueError("durable queue is required")
        if not callable(getattr(queue, "get_by_idempotency", None)):
            raise ValueError("durable queue must expose scoped idempotency reads")
        if object_store is None or not callable(getattr(object_store, "put", None)):
            raise ValueError("object store is required")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 50 * 1024 * 1024:
            raise ValueError("max_bytes is out of range")
        if isinstance(max_jobs, bool) or not isinstance(max_jobs, int) or not 1 <= max_jobs <= 100_000:
            raise ValueError("max_jobs is out of range")
        self.queue = queue
        self.object_store = object_store
        self.knowledge = knowledge
        self.vectors = vectors
        self.max_bytes = max_bytes
        self.max_jobs = max_jobs
        self.event_sink = event_sink
        self._closed = False

    def health_check(self) -> bool:
        checker = getattr(self.queue, "health_check", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return not self._closed

    def _emit(self, name: str, **fields: object) -> None:
        emit_safely(self.event_sink, name, fields)

    @staticmethod
    def _job_id(idempotency_key: str) -> str:
        return f"ing-{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:40]}"

    @staticmethod
    def _source_key(checksum: str) -> str:
        digest = checksum.removeprefix("sha256:")
        return f"uploads/{digest}"

    def _public_job(self, record: object) -> dict[str, object]:
        raw_status = str(_field(record, "status", "failed"))
        if raw_status not in _QUEUE_STATUS:
            raw_status = "failed"
        status = "processing" if raw_status in {"leased", "processing"} else "failed" if raw_status == "dead" else raw_status
        stage = "processing" if raw_status in {"leased", "processing"} else status
        payload = _field(record, "payload", {})
        payload = payload if isinstance(payload, Mapping) else {}
        document_id = _field(record, "document_id") or payload.get("document_id")
        last_error = _safe_error_code(_field(record, "last_error"))
        if raw_status == "dead":
            last_error = "recovery_required"
        attempts = _field(record, "attempts", 0)
        try:
            attempt = min(64, max(1, int(attempts)))
        except (TypeError, ValueError):
            attempt = 1
        created_at = _field(record, "created_at", time.time())
        try:
            created_at = float(created_at)
        except (TypeError, ValueError):
            created_at = time.time()
        return {
            "job_id": str(_field(record, "job_id", "unknown-job")),
            "document_id": document_id if isinstance(document_id, str) else None,
            "status": status,
            "stage": stage,
            "progress": 1.0 if status == "published" else 0.0 if status in {"failed", "cancelled"} else 0.1,
            "attempt": attempt,
            "error_code": last_error,
            "cancel_requested": status == "cancelled",
            "retryable": last_error in {"provider_timeout", "provider_unavailable", "storage_unavailable", "lock_unavailable"},
            "tenant_id": _field(record, "tenant_id"),
            "workspace_id": _field(record, "workspace_id"),
            "collection_id": _field(record, "collection_id"),
            "created_at": created_at,
            "started_at": None,
            "finished_at": created_at if status in {"published", "failed", "cancelled"} else None,
            "metadata": {
                "execution": "external-worker",
                "durability": "postgres-s3",
                "restart_recovery": True,
                "storage": "object-store",
            },
        }

    def _record_for_scope(self, job_id: str, *, tenant_id: str, workspace_id: str) -> object | None:
        getter = getattr(self.queue, "get", None)
        if not callable(getter):
            return None
        try:
            return getter(job_id, tenant_id=tenant_id, workspace_id=workspace_id)
        except TypeError:
            # A durable queue without the scoped read contract cannot be
            # queried through this boundary. Never widen to a global lookup.
            return None

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
        idempotency_key: str | None = None,
        operation: str = "ingest",
        document_id: str | None = None,
    ) -> dict[str, object]:
        if self._closed:
            raise IngestionApplicationError("storage_unavailable")
        tenant = _required_text(tenant_id, maximum=128)
        workspace = _required_text(workspace_id, maximum=128)
        collection = _required_text(collection_id, maximum=128)
        display_filename = sanitize_display_filename(_required_text(filename, maximum=_MAX_FILENAME))
        filename_ref = base64.urlsafe_b64encode(display_filename.encode("utf-8")).decode("ascii")
        if len(filename_ref) > 512:
            raise IngestionApplicationError("validation_error")
        suffix = Path(display_filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise IngestionApplicationError("unsupported_media_type")
        if operation not in {"ingest", "reindex"}:
            raise IngestionApplicationError("validation_error")
        key = _required_text(idempotency_key or f"{operation}:{uuid.uuid4().hex}", maximum=_MAX_IDEMPOTENCY_KEY)
        job_id = self._job_id(f"{tenant}:{workspace}:{collection}:{key}")
        data = _read_source(source, max_bytes=self.max_bytes)
        checksum_ref = f"sha256:{hashlib.sha256(data).hexdigest()}"
        source_key = self._source_key(checksum_ref)
        scope = ObjectScope(tenant_id=tenant, workspace_id=workspace, source_id=job_id)
        payload = {
            "object_key": source_key,
            "object_source_id": job_id,
            "filename_ref": filename_ref,
            "operation": operation,
            "checksum": checksum_ref,
            "byte_size": str(len(data)),
        }
        if document_id:
            payload["document_id"] = document_id
        try:
            lookup = getattr(self.queue, "get_by_idempotency", None)
            existing = None
            if callable(lookup):
                existing = lookup(
                    tenant_id=tenant,
                    workspace_id=workspace,
                    collection_id=collection,
                    idempotency_key=key,
                )
            if existing is not None:
                existing_payload = _field(existing, "payload", {})
                if not isinstance(existing_payload, Mapping) or dict(existing_payload) != payload:
                    raise IngestionApplicationError("conflict")
                record = existing
            else:
                metadata = self.object_store.put(scope, source_key, data)
                observed_checksum = str(getattr(metadata, "checksum", "") or checksum_ref)
                try:
                    observed_size = int(getattr(metadata, "size", len(data)))
                except (TypeError, ValueError):
                    raise IngestionApplicationError("storage_unavailable") from None
                if observed_checksum != checksum_ref or observed_size != len(data):
                    raise IngestionApplicationError("storage_unavailable")
            if existing is None:
                record = self.queue.enqueue(
                    job_id=job_id,
                    idempotency_key=key,
                    payload=payload,
                    tenant_id=tenant,
                    workspace_id=workspace,
                    collection_id=collection,
                )
        except IngestionApplicationError:
            # The object key is content addressed and the idempotency lookup
            # plus enqueue are separate durable operations.  A concurrent
            # request may have published the same object/job while this
            # request is failing, so this boundary cannot safely determine
            # ownership and delete the object.  Unreferenced objects are
            # reclaimed by storage retention/GC after the durable reference
            # window, never by a losing request.
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            # See the IngestionApplicationError branch above.  In particular,
            # never delete after a queue race: the same content-addressed
            # object may already be referenced by the winning enqueue.
            if code == "capacity":
                raise IngestionApplicationError("storage_unavailable") from None
            if code == "idempotency":
                raise IngestionApplicationError("conflict") from None
            raise IngestionApplicationError("storage_unavailable") from None
        self._emit("worker.ingestion.enqueued", job_ref=opaque_ref(job_id),
                   request_ref=opaque_ref(request_id) if request_id else None,
                   correlation_ref=opaque_ref(correlation_id) if correlation_id else None)
        return self._public_job(record)

    upload = submit_upload

    def get_status(
        self,
        job_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> dict[str, object] | None:
        record = self._record_for_scope(
            _required_text(job_id, maximum=128), tenant_id=_required_text(tenant_id, maximum=128),
            workspace_id=_required_text(workspace_id, maximum=128),
        )
        if record is None:
            return None
        collection = _field(record, "collection_id")
        allowed = set(allowed_collection_ids or [])
        if not isinstance(collection, str) or ("*" not in allowed and collection not in allowed):
            return None
        return self._public_job(record)

    status = get_status

    def list_jobs(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        allowed_collection_ids: Iterable[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        listing = getattr(self.queue, "list", None)
        if not callable(listing):
            return []
        try:
            records = listing(limit=min(100, max(1, int(limit))), tenant_id=tenant_id, workspace_id=workspace_id)
        except TypeError:
            return []
        allowed = set(allowed_collection_ids or [])
        return [
            self._public_job(record)
            for record in records
            if _field(record, "tenant_id") == tenant_id
            and _field(record, "workspace_id") == workspace_id
            and ("*" in allowed or _field(record, "collection_id") in allowed)
        ]

    def cancel(
        self,
        job_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> dict[str, object] | None:
        tenant = _required_text(tenant_id, maximum=128)
        workspace = _required_text(workspace_id, maximum=128)
        record = self.get_status(job_id, tenant_id=tenant, workspace_id=workspace, allowed_collection_ids=allowed_collection_ids)
        if record is None:
            return None
        raw = self._record_for_scope(job_id, tenant_id=tenant, workspace_id=workspace)
        if raw is None:
            return None
        if _field(raw, "status") in {"published", "failed", "cancelled", "dead"}:
            result = dict(record)
            result["cancelled"] = False
            return result
        canceller = getattr(self.queue, "cancel", None)
        if not callable(canceller):
            return record
        try:
            after = canceller(job_id, tenant_id=tenant, workspace_id=workspace)
        except TypeError:
            # A durable queue without the scoped mutation contract cannot be
            # used through this boundary.
            result = dict(record)
            result["cancelled"] = False
            return result
        except Exception:
            result = dict(record)
            result["cancelled"] = False
            return result
        result = self._public_job(after)
        result["cancelled"] = result.get("status") == "cancelled"
        return result

    cancel_job = cancel

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
    ) -> dict[str, object] | None:
        tenant = _required_text(tenant_id, maximum=128)
        workspace = _required_text(workspace_id, maximum=128)
        record = self._record_for_scope(job_id, tenant_id=tenant, workspace_id=workspace)
        allowed = set(allowed_collection_ids or [])
        if record is None or ("*" not in allowed and _field(record, "collection_id") not in allowed):
            return None
        if _field(record, "status") not in {"failed", "cancelled", "dead"}:
            raise IngestionApplicationError("conflict")
        return self.submit_upload(
            source,
            filename=filename,
            collection_id=str(_field(record, "collection_id")),
            workspace_id=workspace,
            tenant_id=tenant,
            request_id=request_id,
            correlation_id=correlation_id,
            idempotency_key=f"retry:{job_id}:{uuid.uuid4().hex}",
        )

    def reindex(
        self,
        document_id: str,
        *,
        collection_id: str,
        tenant_id: str,
        workspace_id: str,
        source: object | None,
        filename: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, object]:
        if source is None:
            if self.knowledge is None:
                raise IngestionApplicationError("storage_unavailable")
            getter = getattr(self.knowledge, "get_document", None)
            if not callable(getter):
                raise IngestionApplicationError("storage_unavailable")
            document = _scoped_call(getter, document_id, tenant_id=tenant_id, workspace_id=workspace_id)
            if document is None:
                raise IngestionApplicationError("not_found")
            metadata = _field(document, "metadata", {})
            metadata = metadata if isinstance(metadata, Mapping) else {}
            key = metadata.get("object_key")
            source_id = metadata.get("object_source_id")
            if not isinstance(key, str) or not isinstance(source_id, str):
                raise IngestionApplicationError("storage_unavailable")
            try:
                source = self.object_store.get(
                    ObjectScope(tenant_id=tenant_id, workspace_id=workspace_id, source_id=source_id),
                    key,
                    max_bytes=self.max_bytes,
                )
            except Exception:
                raise IngestionApplicationError("storage_unavailable") from None
        return self.submit_upload(
            source,
            filename=filename,
            collection_id=collection_id,
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            request_id=request_id,
            correlation_id=correlation_id,
            idempotency_key=f"reindex:{document_id}:{uuid.uuid4().hex}",
            operation="reindex",
            document_id=document_id,
        )

    def delete_document(
        self,
        document_id: str,
        *,
        workspace_id: str,
        allowed_collection_ids: Iterable[str],
        tenant_id: str | None = None,
    ) -> dict[str, object] | None:
        tenant = _required_text(tenant_id, maximum=128)
        if self.knowledge is None:
            raise IngestionApplicationError("storage_unavailable")
        getter = getattr(self.knowledge, "get_document", None)
        deleter = getattr(self.knowledge, "delete_document", None)
        if not callable(getter) or not callable(deleter):
            raise IngestionApplicationError("storage_unavailable")
        document = _scoped_call(getter, document_id, tenant_id=tenant, workspace_id=workspace_id)
        collection = _field(document, "collection_id") if document is not None else None
        if document is None or not isinstance(collection, str) or ("*" not in set(allowed_collection_ids or []) and collection not in set(allowed_collection_ids or [])):
            return None
        try:
            deleted_points = 0
            if self.vectors is not None:
                vector_delete = getattr(self.vectors, "delete_document", None)
                if callable(vector_delete):
                    deleted_points = _scoped_call(vector_delete, document_id, collection, tenant_id=tenant, workspace_id=workspace_id) or 0
            deleted_chunks = _scoped_call(deleter, document_id, tenant_id=tenant, workspace_id=workspace_id)
            deleted_chunks = int(deleted_chunks or 0)
        except Exception:
            raise IngestionApplicationError("storage_unavailable") from None
        metadata = _field(document, "metadata", {})
        if isinstance(metadata, Mapping) and isinstance(metadata.get("object_key"), str) and isinstance(metadata.get("object_source_id"), str):
            try:
                self.object_store.delete(
                    ObjectScope(tenant_id=tenant, workspace_id=workspace_id, source_id=metadata["object_source_id"]),
                    metadata["object_key"],
                )
            except Exception:
                # The metadata tombstone is authoritative; reconciliation can
                # remove a private orphan later without reviving the document.
                pass
        return {
            "document_id": document_id,
            "workspace_id": workspace_id,
            "collection_id": collection,
            "deleted": True,
            "deleted_chunks": deleted_chunks,
            "deleted_points": int(deleted_points or 0),
        }

    def close(self) -> None:
        self._closed = True

    shutdown = close


__all__ = ["PostgresIngestionApplicationService"]
