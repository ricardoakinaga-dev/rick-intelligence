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
    def __init__(self, code: str = "ingestion_failed", *, recovery_reason: str | None = None) -> None:
        self.code = code if code in {
            "validation_error", "storage_unavailable", "provider_timeout",
            "provider_unavailable", "vector_store_unavailable", "lock_unavailable",
            "ingestion_failed", "cancelled", "recovery_required",
        } else "ingestion_failed"
        self.recovery_reason = recovery_reason
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
    """Canonical attempt facts shared by execution and public cancellation.

    The token is derived from persisted attempt facts, independent of a caller
    cache or a lease heartbeat. Full Job and facade records yield the same key.
    """
    import json
    from uuid import NAMESPACE_URL, uuid5
    attempts = _field(record, 'attempts', 1)
    count = _field(record, 'attempt_count', attempts if type(attempts) is int else len(attempts))
    started = _field(record, 'started_at')
    if started is None and isinstance(attempts, (list, tuple)) and attempts:
        started = _field(attempts[-1], 'started_at')
    metadata = {'queue_attempt': count}
    for key, value in (('created_at', _field(record, 'created_at')), ('started_at', started)):
        if value is not None:
            metadata['queue_' + key] = value
    if started is not None:
        identity = [_field(record, k) for k in ('tenant_id', 'workspace_id', 'collection_id', 'job_id')]
        identity += [count, float(started)]
        metadata['publication_attempt'] = uuid5(NAMESPACE_URL,
            'rick-canonical-attempt:' + json.dumps(identity, separators=(',', ':'), allow_nan=False)).hex
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

        JobContinuation transfers an expired lease for active pre-intent work.
        None means no checkpoint/commit intent or a resolved failed attempt. An
        unavailable outcome raises recovery_required and must keep the queue
        nonterminal without consuming another attempt.
        """
        from rick_jobs import (JobContinuation, JobScope, JobPublicationFacts,
            JobPublicationResult, JobPublicationCancellation)

        recover = getattr(self.ingestion, "recover_publication", None)
        if not callable(recover):
            return None
        receipt = None
        try:
            knowledge = getattr(self.ingestion, 'knowledge', None)
            scope = {k: _field(job, k) for k in ('tenant_id', 'workspace_id', 'collection_id')}
            getter = getattr(knowledge, 'get_publication', None)
            receipt = getter(str(_field(job, 'job_id')), **scope) if callable(getter) else None
            checkpoint_getter = getattr(knowledge, 'get_ingestion_checkpoint', None)
            checkpoint = (checkpoint_getter(str(_field(job, 'job_id')), **scope)
                if callable(checkpoint_getter) else None)
            metadata = _recovery_metadata(job)
            current_checkpoint = (checkpoint is not None
                and checkpoint['attempt_id'] == metadata.get('publication_attempt')
                and checkpoint['job_snapshot']['attempt'] == metadata['queue_attempt']
                and checkpoint['job_snapshot']['created_at'] == metadata.get('queue_created_at')
                and checkpoint['job_snapshot']['started_at'] == metadata.get('queue_started_at'))
            if (checkpoint is not None and checkpoint['state'] == 'active'
                    and not current_checkpoint and (receipt is None or receipt['outcome'] != 'committed')):
                raise ExternalIngestionError('recovery_required')
            # A committed receipt repairs stale counters. A current checkpoint
            # is considered before older failed receipts, including cancellation.
            if receipt is not None and receipt['outcome'] != 'committed':
                saved = receipt['job_snapshot']
                if saved['attempt'] != metadata['queue_attempt'] and not (
                        current_checkpoint and receipt['outcome'] == 'failed'
                        and saved['attempt'] < metadata['queue_attempt']):
                    raise ExternalIngestionError('recovery_required')
            from rick_ingestion.jobs import IngestionJob
            snapshot = IngestionJob(job_id=_field(job, 'job_id'), **scope,
                document_id=(checkpoint['document_id'] if current_checkpoint
                    and (receipt is None or receipt['outcome'] == 'failed') else
                    (receipt or {}).get('document_id')), metadata=metadata)
            result = recover(_field(job, "job_id"), tenant_id=_field(job, "tenant_id"),
                workspace_id=_field(job, "workspace_id"), collection_id=_field(job, "collection_id"), snapshot=snapshot)
        except Exception:
            raise ExternalIngestionError("recovery_required") from None
        if result is not None and _field(result, "status") == "cancelled":
            # Only the scoped service's durable terminal authority crosses
            # this seam. A caller's polling clock cannot supply its history.
            if _field(result, 'started_at') is None:
                raise ExternalIngestionError('recovery_required', recovery_reason='publication_facts_unknown')
            cancellation = JobPublicationCancellation(facts=JobPublicationFacts(
                job_id=_field(result, 'job_id'), scope=JobScope(**scope),
                attempt=_field(result, 'attempt'), created_at=_field(result, 'created_at'),
                started_at=_field(result, 'started_at'),
                attempt_id=_field(result, 'metadata')['publication_attempt']),
                completed_at=_field(result, 'finished_at'))
            error = ExternalIngestionError('cancelled')
            error.publication_cancellation = cancellation
            raise error
        if result is None or _field(result, "status") == "failed":
            if current_checkpoint and checkpoint['state'] == 'active':
                # Expiry transfers a lease, not business-attempt ownership.
                # The execution path revalidates source and processing facts
                # before reusing any persisted parser/chunker/provider output.
                saved = checkpoint['job_snapshot']
                if checkpoint['cancel_requested']:
                    raise ExternalIngestionError('recovery_required')
                return JobContinuation(job_id=_field(job, 'job_id'), scope=JobScope(**scope),
                    attempt=saved['attempt'], created_at=saved['created_at'],
                    started_at=saved['started_at'], attempt_id=checkpoint['attempt_id'])
            return None
        if _field(result, "status") != "published":
            raise ExternalIngestionError("recovery_required")
        payload = _field(job, "payload", {})
        key = payload.get("object_key") if isinstance(payload, Mapping) else None
        if _field(result, 'finished_at') is None:
            raise ExternalIngestionError('recovery_required', recovery_reason='publication_finish_unknown')
        if _field(result, 'started_at') is None:
            raise ExternalIngestionError('recovery_required', recovery_reason='publication_facts_unknown')
        return JobPublicationResult(document_id=_field(result, "document_id"),
            output_refs={"object_key": key} if isinstance(key, str) and key else {},
            completed_at=_field(result, 'finished_at'),
            facts=JobPublicationFacts(job_id=_field(result, 'job_id'), scope=JobScope(**scope),
                attempt=_field(result, 'attempt'), created_at=_field(result, 'created_at'),
                started_at=_field(result, 'started_at'),
                attempt_id=_field(result, 'metadata')['publication_attempt']))

    def request_publication_cancel(self, job):
        """Persist only the scoped current canonical attempt's cancellation."""
        from rick_ingestion.jobs import IngestionJob
        knowledge = getattr(self.ingestion, "knowledge", None)
        request = getattr(knowledge, 'request_ingestion_cancel', None)
        if not callable(request):
            raise ExternalIngestionError('recovery_required')
        try:
            metadata = _recovery_metadata(job)
            if 'publication_attempt' not in metadata:
                raise ExternalIngestionError('recovery_required')
            scope = {key: _field(job, key) for key in ('tenant_id', 'workspace_id', 'collection_id')}
            owner = IngestionJob(job_id=_field(job, 'job_id'), **scope,
                attempt=metadata['queue_attempt'], created_at=metadata['queue_created_at'],
                started_at=metadata['queue_started_at'], metadata=metadata)
            request(owner)
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
                recovery_snapshot = dict(job_id=job_id, tenant_id=tenant_id,
                    workspace_id=workspace_id, collection_id=collection_id,
                    metadata=_recovery_metadata(record))
                knowledge = getattr(self.ingestion, 'knowledge', None)
                receipt_getter = getattr(knowledge, 'get_publication', None)
                receipt = (receipt_getter(job_id, tenant_id=tenant_id,
                    workspace_id=workspace_id, collection_id=collection_id)
                    if callable(receipt_getter) else None)
                if receipt is not None and receipt['outcome'] == 'failed':
                    saved = receipt['job_snapshot']
                    current = recovery_snapshot['metadata']
                    checkpoint_getter = getattr(knowledge, 'get_ingestion_checkpoint', None)
                    checkpoint = (checkpoint_getter(job_id, tenant_id=tenant_id,
                        workspace_id=workspace_id, collection_id=collection_id)
                        if callable(checkpoint_getter) else None)
                    current_checkpoint = (checkpoint is not None
                        and checkpoint['job_snapshot']['attempt'] == current.get('queue_attempt')
                        and checkpoint['state'] in {'active', 'cancelled'})
                    if (saved['attempt'] < current.get('queue_attempt', 1)
                            and saved['created_at'] == current.get('queue_created_at')
                            and not current_checkpoint):
                        # Resolve only the pinned older failed attempt before
                        # starting this canonical retry. A current checkpoint
                        # (including cancellation) keeps current authority;
                        # a receipt race still meets the service's token fence.
                        recovery_snapshot['metadata'] = dict(saved['metadata'])
                        recovery_snapshot['document_id'] = receipt['document_id']
                recovered = recover(job_id, tenant_id=tenant_id, workspace_id=workspace_id,
                    collection_id=collection_id, snapshot=recovery_snapshot)
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
                    lease_lost_check=lease_lost_check,
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
                    lease_lost_check=lease_lost_check,
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
