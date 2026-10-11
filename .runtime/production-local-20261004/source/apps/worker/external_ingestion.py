"""Worker handler that hydrates a durable object into canonical ingestion."""

from __future__ import annotations

from collections.abc import Mapping
import base64
import binascii
import hashlib
from pathlib import Path
import os
import re
import tempfile

from rick_ingestion.parsers import SUPPORTED_EXTENSIONS, sanitize_display_filename

try:
    from core.otel import record_safe_exception, stage_span
except ImportError:  # pragma: no cover - standalone worker package import
    from contextlib import nullcontext

    def stage_span(_name, **_kwargs):
        return nullcontext(None)

    def record_safe_exception(_span, _error) -> None:
        return None


class ExternalIngestionError(RuntimeError):
    def __init__(self, code: str = "ingestion_failed") -> None:
        self.code = code if code in {
            "validation_error", "storage_unavailable", "provider_timeout",
            "provider_unavailable", "vector_store_unavailable", "lock_unavailable",
            "ingestion_failed", "cancelled", "recovery_required",
        } else "ingestion_failed"
        super().__init__(self.code)


class _LeaseGuard:
    def __init__(self, lost: object) -> None:
        self._lost = lost

    def __enter__(self):
        self.check()
        return self

    def check(self):
        """Revalidate immediately before the publication commit."""
        if callable(self._lost) and self._lost():
            raise ExternalIngestionError("lock_unavailable")

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None and callable(self._lost) and self._lost():
            raise ExternalIngestionError("lock_unavailable")
        return False


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _recovery_metadata(record):
    metadata = {'queue_attempt': _field(record, 'attempt_count', _field(record, 'attempts', 1))}
    for key in ('created_at', 'started_at'):
        value = _field(record, key)
        if value is not None:
            metadata['queue_' + key] = value
    return metadata


class ExternalIngestionHandler:
    """Read one queue record and execute the canonical pipeline once."""

    def __init__(
        self,
        ingestion: object,
        object_store: object,
        *,
        max_bytes: int = 50 * 1024 * 1024,
        temp_root: str | Path | None = None,
        created_by: str | None = None,
    ) -> None:
        if ingestion is None or not callable(getattr(ingestion, "ingest", None)):
            raise ValueError("canonical ingestion is required")
        if object_store is None or not callable(getattr(object_store, "get", None)):
            raise ValueError("object store is required")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 50 * 1024 * 1024:
            raise ValueError("max_bytes is out of range")
        if created_by is not None and (not isinstance(created_by, str) or not created_by.strip() or len(created_by) > 256):
            raise ValueError("created_by is invalid")
        self.ingestion = ingestion
        self.object_store = object_store
        self.max_bytes = max_bytes
        self.created_by = created_by.strip() if isinstance(created_by, str) else None
        if temp_root is None:
            self._temp_root = Path(tempfile.mkdtemp(prefix="rick-worker-"))
            self._owns_temp_root = True
        else:
            self._temp_root = Path(temp_root)
            self._temp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._owns_temp_root = False
        try:
            os.chmod(self._temp_root, 0o700)
        except OSError as exc:
            raise ValueError("worker temporary storage is unavailable") from exc

    def recover_job(self, job):
        """Queue owner seam: return an authoritative JobResult, None, or defer.

        None means no commit intent or a resolved failed attempt. An
        unavailable outcome raises recovery_required and must keep the queue
        nonterminal without consuming another attempt.
        """
        from rick_jobs import JobResult
        import time

        recover = getattr(self.ingestion, "recover_publication", None)
        if not callable(recover):
            return None
        try:
            knowledge = getattr(self.ingestion, 'knowledge', None)
            getter = getattr(knowledge, 'get_publication', None)
            if callable(getter):
                receipt = getter(str(_field(job, 'job_id')), **{k: _field(job,k) for k in ('tenant_id','workspace_id','collection_id')})
                saved = (receipt or {}).get('job_snapshot') or {}
                queue_attempt = saved.get('metadata', {}).get('queue_attempt', saved.get('attempt'))
                if queue_attempt is not None and queue_attempt != _field(job, 'attempt_count', _field(job, 'attempts', queue_attempt)):
                    raise ExternalIngestionError('recovery_required')
            result = recover(str(_field(job, "job_id")), tenant_id=_field(job, "tenant_id"),
                workspace_id=_field(job, "workspace_id"), collection_id=_field(job, "collection_id"))
        except Exception:
            raise ExternalIngestionError("recovery_required") from None
        if result is not None and _field(result, "status") == "cancelled":
            raise ExternalIngestionError("cancelled")
        if result is None or _field(result, "status") == "failed":
            return None
        if _field(result, "status") != "published":
            raise ExternalIngestionError("recovery_required")
        payload = _field(job, "payload", {})
        key = payload.get("object_key") if isinstance(payload, Mapping) else None
        return JobResult(document_id=_field(result, "document_id"),
            output_refs={"object_key": key} if isinstance(key, str) and key else {},
            completed_at=max(float(_field(result, 'finished_at') or time.time()), float(_field(job, "updated_at", 0))))

    def request_publication_cancel(self, job):
        """Persist an owner cancellation without reconstructing or replaying effects."""
        from rick_ingestion.jobs import IngestionJob
        knowledge = getattr(self.ingestion, "knowledge", None)
        getter = getattr(knowledge, "get_publication", None)
        if not callable(getter):
            return
        try:
            scope = {key: _field(job, key) for key in ('tenant_id', 'workspace_id', 'collection_id')}
            receipt = getter(str(_field(job, 'job_id')), **scope)
            if receipt is not None and receipt['outcome'] == 'pending':
                owner = IngestionJob(job_id=str(_field(job, 'job_id')), **scope,
                    metadata={'publication_attempt': receipt['attempt_id']})
                knowledge.request_publication_cancel(owner)
        except Exception:
            raise ExternalIngestionError('recovery_required') from None

    def __call__(self, record: object, *, lease_lost_check=None) -> object:
        payload = _field(record, "payload", {})
        if not isinstance(payload, Mapping):
            raise ExternalIngestionError("validation_error")
        job_id = _field(record, "job_id")
        tenant_id = _field(record, "tenant_id")
        workspace_id = _field(record, "workspace_id")
        collection_id = _field(record, "collection_id")
        source_id = payload.get("object_source_id") or job_id
        object_key = payload.get("object_key")
        expected_checksum = payload.get("checksum")
        if not isinstance(expected_checksum, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_checksum) is None:
            raise ExternalIngestionError("validation_error")
        encoded_filename = payload.get("filename_ref")
        if encoded_filename is not None:
            if not isinstance(encoded_filename, str) or not encoded_filename or len(encoded_filename) > 512:
                raise ExternalIngestionError("validation_error")
            try:
                padding = "=" * (-len(encoded_filename) % 4)
                filename = base64.b64decode(
                    encoded_filename + padding,
                    altchars=b"-_",
                    validate=True,
                ).decode("utf-8")
            except (binascii.Error, ValueError, UnicodeDecodeError):
                raise ExternalIngestionError("validation_error") from None
        else:
            filename = payload.get("display_filename")
        if not all(isinstance(value, str) and value.strip() for value in (job_id, tenant_id, workspace_id, collection_id, source_id, object_key, filename)):
            raise ExternalIngestionError("validation_error")
        recover = getattr(self.ingestion, "recover_publication", None)
        if callable(recover):
            try:
                recovered = recover(job_id, tenant_id=tenant_id, workspace_id=workspace_id,
                                    collection_id=collection_id)
            except Exception:
                raise ExternalIngestionError("recovery_required") from None
            if recovered is not None:
                if _field(recovered, "status") == "published":
                    return recovered
                if _field(recovered, "status") == "verifying":
                    raise ExternalIngestionError("recovery_required")
                if _field(recovered, "status") == "cancelled":
                    raise ExternalIngestionError("cancelled")
        # Resolve the external storage graph at execution, as the composition
        # root does. Importing this handler for local API/domain tests must not
        # eagerly require optional external adapters or construct their graph.
        from rick_storage import ObjectScope

        with stage_span("stores.object_store.get", attributes={"storage.operation": "get"}) as span:
            try:
                source = self.object_store.get(
                    ObjectScope(tenant_id=tenant_id, workspace_id=workspace_id, source_id=source_id),
                    object_key,
                    max_bytes=self.max_bytes,
                )
            except Exception as exc:
                record_safe_exception(span, exc)
                raise ExternalIngestionError("storage_unavailable") from None
        if not isinstance(source, bytes) or not source:
            raise ExternalIngestionError("storage_unavailable")
        if len(source) > self.max_bytes:
            raise ExternalIngestionError("validation_error")
        if f"sha256:{hashlib.sha256(source).hexdigest()}" != expected_checksum:
            raise ExternalIngestionError("validation_error")
        display_filename = sanitize_display_filename(filename)
        suffix = Path(display_filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ExternalIngestionError("validation_error")
        path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix="job-", suffix=suffix, dir=self._temp_root,
            )
            path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as target:
                os.chmod(path, 0o600)
                target.write(source)
            metadata = {
                "object_key": object_key,
                "object_source_id": source_id,
                "byte_size": len(source),
            }
            if self.created_by:
                metadata["created_by"] = self.created_by
            operation = payload.get("operation") or "ingest"
            if operation == "reindex":
                target_document = payload.get("document_id")
                reindex = getattr(self.ingestion, "reindex", None)
                if not callable(reindex) or not isinstance(target_document, str) or not target_document:
                    raise ExternalIngestionError("validation_error")
                result = reindex(
                    target_document,
                    path,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    collection_id=collection_id,
                    display_filename=display_filename,
                    job_id=job_id,
                    publication_guard=lambda: _LeaseGuard(lease_lost_check),
                    cancel_check=lease_lost_check,
                    document_metadata=metadata,
                    _recovery_metadata=_recovery_metadata(record),
                )
            elif operation == "ingest":
                result = self.ingestion.ingest(
                    path,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    collection_id=collection_id,
                    display_filename=display_filename,
                    job_id=job_id,
                    publication_guard=lambda: _LeaseGuard(lease_lost_check),
                    cancel_check=lease_lost_check,
                    document_metadata=metadata,
                    _recovery_metadata=_recovery_metadata(record),
                )
            else:
                raise ExternalIngestionError("validation_error")
            status = _field(result, "status")
            if status == "cancelled":
                raise ExternalIngestionError("cancelled")
            if status != "published":
                metadata = _field(result, "metadata", {})
                if status == "verifying" and isinstance(metadata, Mapping) and metadata.get("publication_outcome_unknown") is True:
                    raise ExternalIngestionError("recovery_required")
                raise ExternalIngestionError(str(_field(result, "error_code") or "ingestion_failed"))
            return result
        finally:
            try:
                if path is not None:
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    def close(self) -> None:
        if not self._owns_temp_root:
            return
        try:
            self._temp_root.rmdir()
        except OSError:
            return


__all__ = ["ExternalIngestionError", "ExternalIngestionHandler"]
