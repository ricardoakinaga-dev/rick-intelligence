"""Worker handler that hydrates a durable object into canonical ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import os
import tempfile

from rick_storage import ObjectScope


class ExternalIngestionError(RuntimeError):
    def __init__(self, code: str = "ingestion_failed") -> None:
        self.code = code if code in {
            "validation_error", "storage_unavailable", "provider_timeout",
            "provider_unavailable", "vector_store_unavailable", "lock_unavailable",
            "ingestion_failed", "cancelled",
        } else "ingestion_failed"
        super().__init__(self.code)


class _LeaseGuard:
    def __init__(self, lost: object) -> None:
        self._lost = lost

    def __enter__(self):
        if callable(self._lost) and self._lost():
            raise ExternalIngestionError("lock_unavailable")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None and callable(self._lost) and self._lost():
            raise ExternalIngestionError("lock_unavailable")
        return False


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


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
        filename = payload.get("display_filename")
        if not all(isinstance(value, str) and value.strip() for value in (job_id, tenant_id, workspace_id, collection_id, source_id, object_key, filename)):
            raise ExternalIngestionError("validation_error")
        try:
            source = self.object_store.get(
                ObjectScope(tenant_id=tenant_id, workspace_id=workspace_id, source_id=source_id),
                object_key,
                max_bytes=self.max_bytes,
            )
        except Exception:
            raise ExternalIngestionError("storage_unavailable") from None
        if not isinstance(source, bytes) or not source:
            raise ExternalIngestionError("storage_unavailable")
        if len(source) > self.max_bytes:
            raise ExternalIngestionError("validation_error")
        path = self._temp_root / f"job-{job_id}.source"
        try:
            with path.open("xb") as target:
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
                    display_filename=filename,
                    job_id=job_id,
                    publication_guard=lambda: _LeaseGuard(lease_lost_check),
                    document_metadata=metadata,
                )
            elif operation == "ingest":
                result = self.ingestion.ingest(
                    path,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    collection_id=collection_id,
                    display_filename=filename,
                    job_id=job_id,
                    publication_guard=lambda: _LeaseGuard(lease_lost_check),
                    document_metadata=metadata,
                )
            else:
                raise ExternalIngestionError("validation_error")
            status = _field(result, "status")
            if status == "cancelled":
                raise ExternalIngestionError("cancelled")
            if status != "published":
                raise ExternalIngestionError(str(_field(result, "error_code") or "ingestion_failed"))
            return result
        finally:
            try:
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
