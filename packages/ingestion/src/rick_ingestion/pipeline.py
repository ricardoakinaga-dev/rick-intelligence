"""Canonical ingestion pipeline: acquire→validate→parse→chunk→embed→index→verify→publish.

Idempotency: stable document/chunk/point IDs — re-ingesting unchanged content
upserts the same identities with no duplicate drift. Changed content produces a
new document version; stale vectors for replaced versions are pruned. Partial
failures never publish: processing → partial/failed → published only after verify.

No HTTP/FastAPI/Redis/OpenAI/qdrant-client imports. RequestContext/correlation
flow through events; document text never enters logs.
"""

from __future__ import annotations

import math
import hashlib
import struct
from asyncio import CancelledError
import inspect
import json
from copy import deepcopy
from dataclasses import asdict
from contextlib import ExitStack, contextmanager, nullcontext
from itertools import islice
from numbers import Real
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from rick_ingestion.chunking import CHUNKER_VERSION, ChunkPlan, RecursiveChunkingStrategy
from rick_ingestion.jobs import DEFAULT_MAX_JOBS, IngestionJob, is_retryable
from rick_ingestion.parsers import (
    DEFAULT_PARSER_LIMITS,
    DEFAULT_PARSER_TIMEOUT_SECONDS,
    PARSER_VERSION,
    ParserLimits,
    ParserRunner,
    ParsedDocument,
    ParsedPage,
    ParseError,
    checksum_file,
    execute_parser,
    parser_for,
    sanitize_display_filename,
    validate_file,
)
from rick_knowledge import (
    Collection,
    Document,
    KnowledgeStore,
    chunk_id_for_document,
    document_id_for_content,
    legacy_document_id_for_content,
    document_version,
    normalize_collection_id,
    normalize_tenant_id,
)
from rick_knowledge.fencing import ATTEMPT_METADATA_KEY, OwnershipLostError, require_owner
from rick_knowledge.publication import publication_snapshot, validate_publication_snapshot


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    def upsert_points(self, points: list[dict]) -> int: ...
    def delete_document(self, document_id: str, collection_id: str) -> int: ...
    def count_for_document(self, document_id: str, collection_id: str) -> int: ...


MAX_POINT_SNAPSHOT = 100_000
MAX_POINT_SNAPSHOT_BYTES = 64 * 1024 * 1024
MAX_EMBEDDING_BATCH = 256
# Projections may retain diagnostics, never effect-control fields.
RECOVERY_DIAGNOSTIC_METADATA = frozenset({
    "request_id", "correlation_id", "traceparent", "tracestate",
    "durability", "restart_recovery",
    "publication_guard_error_after_commit", "completion_notification_error_after_commit",
})
_TYPED_PROVIDER_ERROR_CODES = frozenset({
    "timeout", "unavailable", "rate_limit", "server_error",
    "malformed_response", "missing_field", "invalid_json", "invalid_model",
    "embedding_dimension_mismatch", "model_not_found", "http_error",
    "invalid_configuration", "cancelled", "internal_error",
})
_PROVIDER_RETRYABLE_CODES = frozenset({"timeout", "unavailable", "rate_limit", "server_error"})


def _accepts_scope(method: object) -> bool:
    """Detect the additive scoped adapter seam without catching inner errors."""

    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    names = {parameter.name for parameter in parameters}
    return {"tenant_id", "workspace_id"}.issubset(names) or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )


def _scoped_call(
    method: Callable[..., Any],
    *args: Any,
    tenant_id: str | None,
    workspace_id: str | None,
    **kwargs: Any,
) -> Any:
    """Call a scoped adapter when it advertises the scope contract.

    Local compatibility stores retain their historical one-argument methods;
    external stores opt into the keyword pair. Signature inspection avoids
    turning a real adapter failure into an unsafe unscoped retry.
    """

    if isinstance(tenant_id, str) and isinstance(workspace_id, str) and _accepts_scope(method):
        return method(
            *args,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            **kwargs,
        )
    return method(*args, **kwargs)


def _safe_document_metadata(value: Mapping[str, object] | None) -> dict[str, object]:
    """Keep only bounded object provenance needed by durable ingestion."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("document metadata must be a mapping")
    result: dict[str, object] = {}
    for key in ("object_key", "object_source_id", "created_by"):
        raw = value.get(key)
        if raw is None:
            continue
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 512:
            raise ValueError("document metadata is invalid")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw):
            raise ValueError("document metadata is invalid")
        result[key] = raw.strip()
    byte_size = value.get("byte_size")
    if byte_size is not None:
        if isinstance(byte_size, bool) or not isinstance(byte_size, int) or not 0 <= byte_size <= 50 * 1024 * 1024:
            raise ValueError("document metadata is invalid")
        result["byte_size"] = byte_size
    return result


class IngestionEvents(Protocol):
    def emit(self, event: dict) -> None: ...


class NullEvents:
    def emit(self, event: dict) -> None:
        pass


class _ExecutionOwnershipLost(OwnershipLostError):
    """An expired execution cannot cancel, finish, or compensate its checkpoint."""


class _CancellationRequested(Exception):
    """Internal cooperative cancellation signal."""


def _embedding_is_valid(embedding: object, dimensions: int) -> bool:
    return (
        isinstance(embedding, (list, tuple))
        and len(embedding) == dimensions
        and all(
            isinstance(v, Real)
            and not isinstance(v, bool)
            and math.isfinite(float(v))
            for v in embedding
        )
    )


def _validate_embeddings(vectors: object, *, expected_count: int, dimensions: int) -> list[list[float]]:
    """Validate the complete provider response before any domain/index write."""
    if not isinstance(vectors, (list, tuple)) or len(vectors) != expected_count:
        actual_count = len(vectors) if isinstance(vectors, (list, tuple)) else "unknown"
        raise ValueError(
            f"Embedding count mismatch: expected {expected_count}, got {actual_count}. "
            "Refusing to write incomplete vectors."
        )
    if not isinstance(dimensions, int) or isinstance(dimensions, bool) or dimensions <= 0:
        raise ValueError("Embedding dimensions must be a positive integer.")
    for vector in vectors:
        if not _embedding_is_valid(vector, dimensions):
            raise ValueError(
                f"Embedding dimension or value mismatch: expected {dimensions} finite values. "
                "Refusing to write incompatible vectors; reindex required on model change."
            )
    return [list(vector) for vector in vectors]


class _EmbeddingBatchError(Exception):
    """Deterministic bounded-batch embedding failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _embedding_batch_failure(exc: Exception) -> _EmbeddingBatchError:
    code = getattr(exc, "code", None)
    if code in _TYPED_PROVIDER_ERROR_CODES:
        retryable = code in _PROVIDER_RETRYABLE_CODES or bool(
            getattr(exc, "retryable", False)
        )
        return _EmbeddingBatchError(
            "provider_timeout" if retryable else "validation_error",
            "Embedding batch rejected by provider.",
        )
    if isinstance(exc, ValueError):
        return _EmbeddingBatchError("validation_error", "Embedding batch is invalid.")
    return _EmbeddingBatchError(
        "provider_unavailable", "Embedding provider failed during a bounded batch."
    )


def _embed_in_batches(
    service: "IngestionService",
    job: "IngestionJob",
    plans: list,
    cancel_check: Callable[[], bool] | None,
) -> list[list[float]]:
    """Embed chunk texts in provider-bounded sequential batches.

    Batch order follows the chunk plan; every batch is validated for count,
    dimensions, and finite values before the next call. Deterministic typed
    failures stay non-retryable, and any failure leaves nothing written.
    """

    texts = [plan.text for plan in plans]
    dimensions = service.embeddings.dimensions
    phase = getattr(job, '_phase_checkpoint', None)
    vectors: list[list[float]] = deepcopy(phase['artifacts'].get('vectors', [])) if phase else []
    if vectors:
        vectors = _validate_embeddings(vectors, expected_count=len(vectors), dimensions=dimensions)
    if len(vectors) > len(texts) or (len(vectors) != len(texts) and len(vectors) % MAX_EMBEDDING_BATCH):
        raise OwnershipLostError('checkpoint embedding batch boundary changed')
    for offset in range(len(vectors), len(texts), MAX_EMBEDDING_BATCH):
        service._checkpoint(job, cancel_check)
        batch = texts[offset:offset + MAX_EMBEDDING_BATCH]
        try:
            response = service.embeddings.embed(batch)
            validated = _validate_embeddings(
                response, expected_count=len(batch), dimensions=dimensions,
            )
        except _CancellationRequested:
            raise
        except Exception as exc:
            raise _embedding_batch_failure(exc) from None
        vectors.extend(validated)
        if phase is not None:
            phase['artifacts']['vectors'] = deepcopy(vectors)
            service.knowledge.save_ingestion_checkpoint(job, fingerprint=phase['fingerprint'], artifacts=phase['artifacts'])
            service._checkpoint(job, cancel_check)
    return vectors


class IngestionService:
    """Deliberate interface: ingest / reindex / cancel / get_status."""

    def __init__(self, *, knowledge: KnowledgeStore, vectors: VectorStore, embeddings: EmbeddingProvider,
                 events: IngestionEvents | None = None,
                 chunker=None, embedding_version: str = "emb-v1",
                 max_jobs: int = DEFAULT_MAX_JOBS,
                 parser_limits: ParserLimits | None = None,
                 parser_runner: ParserRunner | None = None,
                 parser_timeout_seconds: float | None = None) -> None:
        if isinstance(max_jobs, bool) or not isinstance(max_jobs, int) or not 0 < max_jobs <= 1024:
            raise ValueError("max_jobs is out of range")
        self.knowledge = knowledge
        self.vectors = vectors
        self.embeddings = embeddings
        self.events = events or NullEvents()
        self.chunker = chunker or RecursiveChunkingStrategy()
        self.embedding_version = embedding_version
        self.max_jobs = max_jobs
        if parser_limits is not None and not isinstance(parser_limits, ParserLimits):
            raise ValueError("parser_limits must be ParserLimits")
        self.parser_limits = parser_limits
        self.parser_runner = parser_runner
        self.parser_timeout_seconds = (
            parser_timeout_seconds
            if parser_timeout_seconds is not None
            else (parser_limits.parser_timeout_seconds if parser_limits is not None
                  else DEFAULT_PARSER_TIMEOUT_SECONDS)
        )
        self._jobs: dict[str, IngestionJob] = {}
        self._lock = RLock()
        # Cancellation remains a request while this attempt's commit outcome
        # is unresolved. Only its publication owner can terminalize the job.
        self._publication_pending: set[str] = set()
        self._publication_recovery: dict[str, Callable[[], IngestionJob]] = {}
        # Local compensations operate on whole documents, so overlapping
        # attempts cannot safely share those identities. Separate this lock
        # from cancellation, which must remain responsive during provider I/O.
        self._operation_lock = RLock()

    # -- jobs ----------------------------------------------------------
    def operation_guard(self):
        """Serialize local document mutations, including adapter-side deletes."""
        return self._operation_lock

    def get_status(self, job_id: str) -> IngestionJob | None:
        return self._jobs.get(job_id)

    def reconcile_publication(self, job_id: str) -> IngestionJob | None:
        """Retry an explicitly unresolved commit without starting a new attempt.

        Recovery is bounded. Cancellation stays a request
        until the authoritative owned outcome can be read under the effect fence.
        """
        with self._operation_lock:
            recover = self._publication_recovery.get(job_id)
            try:
                if recover is not None:
                    return recover()
                job = self.get_status(job_id)
                if job is not None and (job.metadata.get("publication_outcome_unknown") or job.metadata.get('retirement_pending')):
                    return self.recover_publication(job_id, tenant_id=job.tenant_id,
                        workspace_id=job.workspace_id, collection_id=job.collection_id,
                        snapshot=job)
                return job
            finally:
                with self._lock:
                    job = self.get_status(job_id)
                    if job_id not in self._publication_recovery and not (
                            job is not None and job.metadata.get("publication_outcome_unknown")):
                        self._publication_pending.discard(job_id)

    def recover_publication(self, job_id: str, *, tenant_id: str, workspace_id: str,
                            collection_id: str, snapshot=None) -> IngestionJob | None:
        """Reconstruct a scoped commit owner without parser/provider/vector replay.

        An unavailable receipt or outcome remains verifying. Three reads are
        the per-call ceiling; polling never creates another ingestion attempt.
        A committed receipt is immutable even after later document maintenance.
        """
        with self._operation_lock:
            getter = getattr(self.knowledge, "get_publication", None)
            if not callable(getter):
                return None
            def field(name, default=None):
                return snapshot.get(name, default) if isinstance(snapshot, Mapping) else getattr(snapshot, name, default)
            if snapshot is not None and field('job_id', job_id) != job_id:
                raise OwnershipLostError('publication snapshot job changed')
            if snapshot is not None and tuple(field(k) for k in
                    ("tenant_id", "workspace_id", "collection_id")) != (tenant_id, workspace_id, collection_id):
                raise OwnershipLostError("publication snapshot scope changed")
            existing = self._jobs.get(job_id)
            if existing is not None and (existing.tenant_id, existing.workspace_id, existing.collection_id) != (tenant_id, workspace_id, collection_id):
                raise OwnershipLostError("publication scope changed")
            record = None
            for _ in range(3):
                try:
                    record = getter(job_id, tenant_id=tenant_id, workspace_id=workspace_id,
                                    collection_id=collection_id)
                    break
                except (Exception, CancelledError):
                    continue
            else:
                # Even the intent read is unavailable: the caller must retain
                # its running lease/job rather than treat this as no receipt.
                raise RuntimeError("publication authority unavailable")
            checkpoint = None
            if record is None or record["outcome"] != "committed":
                checkpoint_getter = getattr(self.knowledge, 'get_ingestion_checkpoint', None)
                checkpoint = checkpoint_getter(job_id, tenant_id=tenant_id,
                    workspace_id=workspace_id, collection_id=collection_id) if callable(checkpoint_getter) else None
            # Current pre-intent cancellation outranks an older failed receipt.
            current_cancel = (checkpoint is not None and checkpoint['cancel_requested']
                and checkpoint['state'] in {'active', 'cancelled'}
                and (record is None or (record['outcome'] == 'failed'
                    and checkpoint['job_snapshot']['attempt'] > record['job_snapshot']['attempt'])))
            if current_cancel:
                expected = (field('metadata', {}) or {}).get('publication_attempt')
                if expected is not None and expected != checkpoint['attempt_id']:
                    raise OwnershipLostError('cancelled checkpoint attempt changed')
                if existing is not None and existing.metadata.get('publication_attempt') != checkpoint['attempt_id']:
                    raise OwnershipLostError('cached cancellation attempt changed')
                if snapshot is not None and field('document_id', checkpoint['document_id']) != checkpoint['document_id']:
                    raise OwnershipLostError('cancelled checkpoint document changed')
                saved = deepcopy(checkpoint['job_snapshot'])
                job = IngestionJob(job_id=job_id, tenant_id=tenant_id,
                    workspace_id=workspace_id, collection_id=collection_id,
                    document_id=checkpoint['document_id'], status='verifying', stage='verifying',
                    cancel_requested=True, **saved)
                # Request authority plus a durable matching checkpoint can
                # retire only this attempt's effects, without hydrating source.
                # A vanished receipt beside an owned published document is
                # ambiguous and must never be compensated as pre-intent work.
                if job.document_id is not None:
                    with self.knowledge.mutation_guard('document:' + job.document_id):
                        document = _scoped_call(self.knowledge.get_document, job.document_id,
                            tenant_id=tenant_id, workspace_id=workspace_id)
                        if document is None and not self._vectors_confirmed_empty(
                                job.document_id, collection_id, tenant_id, workspace_id):
                            self._cancellation_cleanup_pending(job)
                            self._register_job(job)
                            return job
                        if document is not None and document.collection_id != collection_id:
                            raise OwnershipLostError('checkpoint document collection changed')
                        if document is not None and document.metadata.get(ATTEMPT_METADATA_KEY) == checkpoint['attempt_id']:
                            if document.status == 'published':
                                raise RuntimeError('checkpoint cancellation outcome unavailable')
                            complete = self._cleanup_failed_document(job.document_id, collection_id,
                                document_written=True, tenant_id=tenant_id, workspace_id=workspace_id,
                                attempt_id=checkpoint['attempt_id'], confirm_vectors=True)
                            if not complete:
                                self._cancellation_cleanup_pending(job)
                                self._register_job(job)
                                return job
                job.metadata.pop('cancellation_cleanup_pending', None)
                finished = job.finished_at
                job.transition('cancelled', message='Cancelled by operator.')
                if finished is not None or checkpoint['state'] == 'cancelled':
                    job.finished_at = finished
                self.knowledge.finish_ingestion_checkpoint(job)
                self._register_job(job)
                return job
            if (record is not None and record['outcome'] == 'failed'
                    and checkpoint is not None and checkpoint['state'] == 'active'
                    and checkpoint['job_snapshot']['attempt'] > record['job_snapshot']['attempt']
                    and (field('metadata', {}) or {}).get('publication_attempt', checkpoint['attempt_id']) == checkpoint['attempt_id']):
                return None
            if record is None:
                return None
            if (record["job_id"], record["tenant_id"], record["workspace_id"], record["collection_id"]) != (
                    job_id, tenant_id, workspace_id, collection_id):
                raise OwnershipLostError("publication receipt scope changed")
            expected = (field("metadata", {}) or {}).get("publication_attempt")
            if record['outcome'] != 'committed' and expected is not None and expected != record["attempt_id"]:
                raise OwnershipLostError("publication attempt changed")
            saved = deepcopy(record.get('job_snapshot') or {})
            validate_publication_snapshot(saved, attempt_id=record['attempt_id'], document_attempt=record['document_attempt'])
            if snapshot is not None and field('document_id', record['document_id']) != record['document_id']:
                raise OwnershipLostError('publication snapshot document changed')
            # Only named diagnostics cross from caller projection to authority.
            diagnostics = {k: deepcopy(v) for k, v in (field('metadata', {}) or {}).items()
                if k in RECOVERY_DIAGNOSTIC_METADATA}
            saved['metadata'] = {**diagnostics, **saved['metadata']}
            validate_publication_snapshot(saved, attempt_id=record['attempt_id'], document_attempt=record['document_attempt'])
            job = existing or IngestionJob(job_id=job_id, tenant_id=tenant_id,
                workspace_id=workspace_id, collection_id=collection_id,
                document_id=record["document_id"], status="verifying", stage="verifying",
                progress=.9, cancel_requested=field("cancel_requested", False),
                **saved)
            if existing is not None:
                if existing.document_id is not None and existing.document_id != record['document_id']:
                    raise OwnershipLostError('cached publication document changed')
                if record['outcome'] != 'committed' and existing.metadata.get('publication_attempt') != record['attempt_id']:
                    raise OwnershipLostError('cached publication attempt changed')
                job.document_id = record['document_id']
                for key, value in saved.items():
                    setattr(job, key, deepcopy(value))
            job.cancel_requested = job.cancel_requested or bool(record.get("cancel_requested"))
            if existing is None:
                self._register_job(job)
            job.metadata["publication_outcome_unknown"] = True
            self._publication_pending.add(job_id)
            outcome = record["outcome"]
            if outcome == "pending":
                if job.status != 'verifying':
                    # A cached terminal label cannot resolve a pending receipt.
                    job.status = job.stage = 'verifying'
                    job.finished_at = None
                for _ in range(3):
                    try:
                        with self.knowledge.collection_guard(tenant_id=tenant_id,
                                workspace_id=workspace_id, collection_id=collection_id), self.knowledge.mutation_guard("document:" + record["document_id"]), self.knowledge.publication_decision_guard(record):
                            # Re-read the receipt under the effect fence. A
                            # commit may have finished since the first read.
                            record = getter(job_id, tenant_id=tenant_id, workspace_id=workspace_id,
                                            collection_id=collection_id)
                            if record is None or record["attempt_id"] != job.metadata["publication_attempt"]:
                                raise OwnershipLostError("publication attempt changed under the effect fence")
                            job.cancel_requested = job.cancel_requested or bool(record.get('cancel_requested'))
                            if record["outcome"] != "pending":
                                outcome = record['outcome']
                                break
                            document = _scoped_call(self.knowledge.get_document, record["document_id"],
                                tenant_id=tenant_id, workspace_id=workspace_id)
                            owned = self.knowledge._publication_matches(record, document)
                            if owned and document.status == "published":
                                # An existing publication is a separate winner
                                # from this deduplication intent. Cancellation
                                # and catalog admission still fence its receipt.
                                if record['document_attempt'] != record['attempt_id']:
                                    collection = self.knowledge.get_collection(workspace_id, collection_id, tenant_id=tenant_id)
                                    outcome = ('cancelled' if job.cancel_requested else 'failed'
                                        if collection is None or collection.status != 'active' else 'committed')
                                else:
                                    outcome = 'committed'
                                record = self.knowledge.resolve_publication(record, outcome)
                                outcome = record['outcome']
                            elif owned and record.get('ready_count', 0) and not job.cancel_requested:
                                collection = self.knowledge.get_collection(workspace_id, collection_id, tenant_id=tenant_id)
                                if collection is None or collection.status != 'active' or document.status != 'processing':
                                    self._cleanup_failed_document(record['document_id'], collection_id,
                                        document_written=True, tenant_id=tenant_id, workspace_id=workspace_id,
                                        attempt_id=record['document_attempt'])
                                    record = self.knowledge.resolve_publication(record, 'failed')
                                    outcome = record['outcome']
                                else:
                                    chunks = _scoped_call(self.knowledge.get_chunks, record['document_id'],
                                        tenant_id=tenant_id, workspace_id=workspace_id)
                                    if not self._verify_pending_points(record, document, chunks):
                                        # Cardinality alone cannot authorize a publication.
                                        return job
                                    _scoped_call(self.knowledge.set_document_status, record['document_id'], 'published',
                                        tenant_id=tenant_id, workspace_id=workspace_id)
                                    decided = getter(job_id, tenant_id=tenant_id, workspace_id=workspace_id,
                                        collection_id=collection_id)
                                    if (decided is None or any(decided[key] != record[key] for key in
                                            ('job_id', 'tenant_id', 'workspace_id', 'collection_id',
                                             'document_id', 'attempt_id', 'document_attempt'))):
                                        raise OwnershipLostError('publication decision identity changed')
                                    record = decided
                                    outcome = record['outcome']
                                    if outcome != 'committed':
                                        return job
                            else:
                                if (job.cancel_requested and document is None
                                        and not self._vectors_confirmed_empty(record['document_id'],
                                            collection_id, tenant_id, workspace_id)):
                                    self._cancellation_cleanup_pending(job)
                                    return job
                                if owned:
                                    complete = self._cleanup_failed_document(record["document_id"], collection_id,
                                        document_written=True, tenant_id=tenant_id,
                                        workspace_id=workspace_id, attempt_id=record["attempt_id"], confirm_vectors=job.cancel_requested)
                                    if job.cancel_requested and not complete:
                                        self._cancellation_cleanup_pending(job)
                                        return job
                                with self._lock:
                                    outcome = "cancelled" if job.cancel_requested else "failed"
                                    resolved = self.knowledge.resolve_publication(record, outcome)
                                    outcome = resolved["outcome"]
                                    job.cancel_requested = job.cancel_requested or bool(resolved.get("cancel_requested"))
                                    record = resolved
                            break
                    except OwnershipLostError:
                        raise
                    except (Exception, CancelledError):
                        continue
                else:
                    return job
            target = "published" if outcome == "committed" else outcome
            # A decision under the effect fence may have observed a newer
            # same-token snapshot. Its persisted facts remain authoritative.
            authority = deepcopy(record['job_snapshot'])
            validate_publication_snapshot(authority, attempt_id=record['attempt_id'], document_attempt=record['document_attempt'])
            checkpoint_getter = getattr(self.knowledge, 'get_ingestion_checkpoint', None)
            terminal_checkpoint = (checkpoint_getter(job_id, tenant_id=tenant_id,
                workspace_id=workspace_id, collection_id=collection_id)
                if callable(checkpoint_getter) else None)
            if (outcome == 'committed' and terminal_checkpoint is not None
                    and terminal_checkpoint['state'] == 'committed'
                    and terminal_checkpoint['document_id'] is None):
                repair = getattr(self.knowledge, 'repair_deduplicated_checkpoint', None)
                if callable(repair) and repair(job):
                    terminal_checkpoint = checkpoint_getter(job_id, tenant_id=tenant_id,
                        workspace_id=workspace_id, collection_id=collection_id)
            if (terminal_checkpoint is not None
                    and terminal_checkpoint['attempt_id'] == record['attempt_id']
                    and terminal_checkpoint['state'] == outcome):
                saved_finish = terminal_checkpoint['job_snapshot']
                if (terminal_checkpoint['document_id'] != record['document_id']
                        or any(saved_finish[k] != authority[k]
                            for k in ('attempt', 'created_at', 'started_at'))
                        or (authority['finished_at'] is not None and saved_finish['finished_at'] is not None
                            and authority['finished_at'] != saved_finish['finished_at'])):
                    raise OwnershipLostError('terminal checkpoint facts changed')
                # Preserve installed terminal checkpoint authority when an old
                # receipt lacks a finish. Known receipt facts cannot change.
                if authority['finished_at'] is None:
                    authority['finished_at'] = saved_finish['finished_at']
            for key in ('attempt', 'created_at', 'started_at', 'finished_at'):
                setattr(job, key, authority[key])
            if job.status != target or job.finished_at is None:
                if job.status != 'verifying':
                    # Durable terminal authority repairs a stale local cache;
                    # ordinary job transitions still cannot reopen an attempt.
                    job.status = job.stage = 'verifying'
                    job.finished_at = authority['finished_at']
                finished_at = job.finished_at
                job.transition(target, progress=1.0 if target == "published" else job.progress,
                    error_code="lock_unavailable" if target == "failed" else None)
                # Every terminal outcome uses decision/checkpoint authority;
                # a regressed clock or old unknown finish remains unknown.
                job.finished_at = finished_at
                job.started_at = authority['started_at']
            job.metadata.pop("publication_outcome_unknown", None)
            self._publication_pending.discard(job_id)
            if target == 'published':
                self._recover_retirement(job)
            checkpoint_getter = getattr(self.knowledge, 'get_ingestion_checkpoint', None)
            if callable(checkpoint_getter):
                try:
                    checkpoint = checkpoint_getter(job_id, tenant_id=tenant_id,
                        workspace_id=workspace_id, collection_id=collection_id)
                    if checkpoint is not None and checkpoint['attempt_id'] == record['attempt_id']:
                        self.knowledge.finish_ingestion_checkpoint(job)
                except (Exception, CancelledError):
                    job.metadata['checkpoint_cleanup_pending'] = True
            try:
                self.knowledge.save_publication_snapshot(job)
            except OwnershipLostError:
                raise
            except (Exception, CancelledError):
                job.metadata['publication_snapshot_pending'] = True
            return job

    def _verify_pending_points(self, record, document, chunks):
        """Verify the exact durable effects under the document/decision fence.

        Legacy intents without completed effect facts remain pending. No
        provider call or cardinality inference can reconstruct those facts.
        """
        checkpoint = self.knowledge.get_ingestion_checkpoint(record['job_id'],
            tenant_id=record['tenant_id'], workspace_id=record['workspace_id'],
            collection_id=record['collection_id'])
        if (checkpoint is None or checkpoint['attempt_id'] != record['attempt_id']
                or checkpoint['document_id'] != record['document_id']
                or checkpoint['state'] != 'active'):
            return False
        artifacts = checkpoint['artifacts']
        manifest, vectors = artifacts.get('point_manifest'), artifacts.get('vectors')
        fingerprint = checkpoint.get('fingerprint') or {}
        if (not isinstance(manifest, str) or not isinstance(vectors, list)
                or len(chunks) != record['ready_count'] or len(vectors) != len(chunks)
                or fingerprint.get('checksum') != document.content_checksum
                or fingerprint.get('document_id') != document.document_id):
            return False
        from rick_knowledge import build_point_payload
        chunks = sorted(chunks, key=lambda c: c.chunk_index)
        expected = [dict(point_id=self._point_id(c.chunk_id), vector=v,
                         payload=build_point_payload(chunk=c, document=document))
                    for c, v in zip(chunks, vectors)]
        planner = getattr(self.vectors, 'plan_upsert_batches', None)
        if callable(planner):
            expected = [p for batch in planner(expected) for p in batch]
        if self._point_manifest(expected) != manifest:
            return False
        observed = self._snapshot_points(self.vectors, record['document_id'],
            record['collection_id'], tenant_id=record['tenant_id'],
            workspace_id=record['workspace_id'])
        return self._point_manifest(observed) == manifest

    @staticmethod
    def _point_manifest(points):
        """Bind IDs, complete payloads and dense/sparse vectors, independent of order.

        Vector transport/storage uses binary32. Compare exact values at that
        representation rather than accepting an arbitrary numeric tolerance.
        The manifest contains no caller projection or provider execution claim.
        """
        def binary32(values):
            if not isinstance(values, (list, tuple)) or any(
                    isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v)
                    for v in values):
                raise ValueError('invalid point vector')
            return [struct.unpack('!f', struct.pack('!f', v))[0] for v in values]
        facts = []
        for p in points:
            fact = dict(point_id=p['point_id'], payload=deepcopy(p['payload']),
                        vector=binary32(p['vector']))
            if 'sparse_vector' in p:
                sparse = p['sparse_vector']
                fact['sparse_vector'] = dict(indices=list(sparse['indices']), values=binary32(sparse['values']))
            facts.append(fact)
        if len(facts) > MAX_POINT_SNAPSHOT or len({p['point_id'] for p in facts}) != len(facts):
            raise ValueError('point manifest contains duplicate or excessive identities')
        encoded = json.dumps(sorted(facts, key=lambda p: p['point_id']), sort_keys=True,
            ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_POINT_SNAPSHOT_BYTES:
            raise ValueError('point manifest exceeds byte limit')
        return hashlib.sha256(encoded).hexdigest()

    def _recover_retirement(self, job):
        """Committed receipt owns bounded cleanup, fenced against both successors."""
        if not job.metadata.get('retirement_pending'):
            return
        old_id = job.metadata['previous_document_id']
        if old_id == job.document_id:
            job.metadata['retirement_pending'] = False
            return
        try:
            with ExitStack() as guards:
                for identity in sorted({old_id, job.document_id}):
                    guards.enter_context(self.knowledge.mutation_guard('document:' + identity))
                new = _scoped_call(self.knowledge.get_document, job.document_id,
                    tenant_id=job.tenant_id, workspace_id=job.workspace_id)
                old = _scoped_call(self.knowledge.get_document, old_id,
                    tenant_id=job.tenant_id, workspace_id=job.workspace_id)
                if (new is None or new.status != 'published' or new.collection_id != job.collection_id
                    or (new.tenant_id, new.workspace_id) != (job.tenant_id, job.workspace_id)
                    or new.metadata.get(ATTEMPT_METADATA_KEY) != job.metadata.get('published_document_attempt', job.metadata['publication_attempt'])
                    or old is None or old.collection_id != job.collection_id
                    or (old.tenant_id, old.workspace_id) != (job.tenant_id, job.workspace_id)
                    or old.metadata.get(ATTEMPT_METADATA_KEY) != job.metadata.get('previous_document_attempt')):
                    # A successor owns these effects; this cleanup has no authority.
                    job.metadata['retirement_pending'] = False
                    job.metadata['retirement_superseded'] = True
                    return
                if job.metadata.get('index_activation_required'):
                    return
                if new.metadata.get('vector_index') and new.metadata.get('vector_index') != old.metadata.get('vector_index'):
                    job.metadata['index_activation_required'] = True
                    return
                if old.status not in {'published', 'unpublished'}:
                    job.metadata['retirement_pending'] = False
                    return
                if old.status == 'published':
                    # Use the same complete, bounded snapshot and compensation
                    # as live replacement while BOTH effect guards remain held.
                    # A committed new receipt cannot be rolled back or relabelled.
                    self._retire_replacement(job, old_id, tenant_id=job.tenant_id,
                        workspace_id=job.workspace_id, collection_id=job.collection_id,
                        retirement_documents=(deepcopy(old), deepcopy(new)))
                    return
                # Hide old effects before deleting: partial external delete is
                # still safely owned and retryable after a process restart.
                # An already-hidden version may have an incomplete index; it
                # cannot be restored from the remaining points alone.
                _scoped_call(self.knowledge.set_document_status, old_id, 'unpublished',
                    tenant_id=job.tenant_id, workspace_id=job.workspace_id)
                _scoped_call(self.vectors.delete_document, old_id, job.collection_id,
                    tenant_id=job.tenant_id, workspace_id=job.workspace_id)
                job.metadata['retirement_pending'] = False
                job.metadata.pop('retirement_deferred', None)
        except (Exception, CancelledError):
            job.metadata['retirement_deferred'] = 'storage_unavailable'
            job.metadata['retirement_error_after_commit'] = True

    def _evict_jobs(self) -> None:
        """Keep the package registry finite while preserving active jobs."""

        terminal = [
            (job_id, job)
            for job_id, job in self._jobs.items()
            if job.status in {"published", "failed", "cancelled"}
        ]
        terminal.sort(key=lambda pair: (pair[1].created_at, pair[0]))
        while len(self._jobs) >= self.max_jobs and terminal:
            job_id, _job = terminal.pop(0)
            self._jobs.pop(job_id, None)

    def _register_job(self, job: IngestionJob) -> None:
        self._evict_jobs()
        if len(self._jobs) >= self.max_jobs:
            # A concurrent active workload must apply backpressure instead of
            # allowing the supposedly bounded status registry to grow forever.
            raise RuntimeError("ingestion job capacity is exhausted")
        self._jobs[job.job_id] = job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in ("published", "failed", "cancelled"):
                return False
            job.cancel_requested = True
            durable_cancel = getattr(self.knowledge, 'request_ingestion_cancel', None)
            if callable(durable_cancel):
                try:
                    durable_cancel(job)
                except (Exception, CancelledError):
                    job.metadata['cancellation_persistence_unavailable'] = True
            if job_id in self._publication_pending:
                request = getattr(self.knowledge, "request_publication_cancel", None)
                if callable(request):
                    try:
                        request(job)
                    except (Exception, CancelledError):
                        # The request remains nonterminal. Local owners also
                        # persist it in their job journal for restart recovery.
                        job.metadata["cancellation_persistence_unavailable"] = True
                return True
            job.transition("cancelled", message="Cancelled by operator.")
            job.metadata['cancellation_notification_attempted'] = True
            try:
                self.events.emit({"type": "ingestion.cancelled", "job_id": job_id})
            except CancelledError:
                # Notification follows the terminal decision. Delivery may
                # already have occurred; record it without replay or rollback.
                job.metadata['cancellation_notification_cancelled'] = True
            # The active execution or recovery owner compensates its effects
            # before finishing the checkpoint. The durable cancellation request
            # remains active until that owner settles it.
            return True

    def _checkpoint(self, job: IngestionJob, cancel_check: Callable[[], bool] | None) -> None:
        lease_lost = getattr(job, '_lease_lost_check', None)
        if callable(lease_lost) and lease_lost():
            raise _ExecutionOwnershipLost('execution lease changed')
        getter = getattr(self.knowledge, 'get_ingestion_checkpoint', None)
        if callable(getter):
            checkpoint = getter(job.job_id, tenant_id=job.tenant_id,
                workspace_id=job.workspace_id, collection_id=job.collection_id)
            if checkpoint is not None:
                if checkpoint['attempt_id'] != job.metadata['publication_attempt']:
                    raise OwnershipLostError('checkpoint attempt changed')
                job.cancel_requested = job.cancel_requested or bool(checkpoint['cancel_requested'])
        if job.status == "cancelled" or job.cancel_requested:
            raise _CancellationRequested
        if callable(cancel_check) and cancel_check():
            if job.status not in {"published", "failed", "cancelled"}:
                self.cancel(job.job_id)
            raise _CancellationRequested

    def _cleanup_failed_document(
        self,
        document_id: str | None,
        collection_id: str,
        *,
        document_written: bool,
        tenant_id: str,
        workspace_id: str,
        attempt_id: str,
        confirm_vectors: bool = False,
    ) -> bool:
        """Hide partial writes and report whether their compensation completed.

        Failed jobs retain their historical best-effort visibility barrier.
        Cancellation additionally needs confirmed cleanup before its durable
        checkpoint can become terminal and leave the recovery queue.
        """
        if not document_id or not document_written:
            return True
        try:
            with self._effect_guard(document_id, attempt_id, tenant_id, workspace_id,
                                    collection_id=collection_id, allow_tombstone=True):
                return self._cleanup_owned_document(document_id, collection_id, tenant_id, workspace_id,
                    attempt_id, confirm_vectors=confirm_vectors)
        except OwnershipLostError:
            # A missing row cannot establish that its scoped vectors vanished.
            # A retained foreign owner instead supersedes our compensation.
            if confirm_vectors:
                try:
                    with self.knowledge.mutation_guard('document:' + document_id):
                        document = _scoped_call(self.knowledge.get_document, document_id,
                            tenant_id=tenant_id, workspace_id=workspace_id)
                        if document is None:
                            return self._vectors_confirmed_empty(document_id, collection_id,
                                tenant_id, workspace_id)
                except (Exception, CancelledError):
                    return False
            return True
        except (Exception, CancelledError):
            try:
                self.events.emit({"type": "ingestion.compensation.pending", "document_id": document_id,
                                  "error_code": "storage_unavailable"})
            except (Exception, CancelledError):
                pass
            return False

    def _vectors_confirmed_empty(self, document_id, collection_id, tenant_id, workspace_id):
        try:
            remaining = _scoped_call(self.vectors.count_for_document, document_id, collection_id,
                tenant_id=tenant_id, workspace_id=workspace_id)
            return type(remaining) is int and remaining == 0
        except (Exception, CancelledError):
            return False

    @staticmethod
    def _cancellation_cleanup_pending(job):
        job.status = job.stage = 'verifying'
        job.finished_at = None
        job.cancel_requested = True
        job.metadata['cancellation_cleanup_pending'] = True
        job.message = 'Cancellation cleanup pending.'

    @contextmanager
    def _effect_guard(self, document_id, attempt_id, tenant_id, workspace_id,
                      job=None, cancel_check=None, collection_id=None, allow_tombstone=False):
        def require_effect_owner(document):
            if (allow_tombstone and document is not None and document.status == 'deleted'
                    and document.metadata.get(ATTEMPT_METADATA_KEY) == attempt_id):
                return
            require_owner(document, attempt_id)

        expected_collection = job.collection_id if job is not None else collection_id
        with self.knowledge.mutation_guard("document:" + document_id):
            document = _scoped_call(self.knowledge.get_document, document_id,
                                    tenant_id=tenant_id, workspace_id=workspace_id)
            require_effect_owner(document)
            if expected_collection is not None and document.collection_id != expected_collection:
                raise OwnershipLostError('document collection changed')
            if job is not None:
                self._checkpoint(job, cancel_check)
                collection = self.knowledge.get_collection(workspace_id, document.collection_id, tenant_id=tenant_id)
                if collection is None or collection.status != "active":
                    raise ParseError("validation_error", "Collection is archived.")
            yield
            # Covers reentrant test adapters and a revoked owner returning
            # from a partially acknowledged effect.
            document = _scoped_call(self.knowledge.get_document, document_id,
                                    tenant_id=tenant_id, workspace_id=workspace_id)
            require_effect_owner(document)
            if expected_collection is not None and document.collection_id != expected_collection:
                raise OwnershipLostError('document collection changed')

    def _cleanup_owned_document(self, document_id, collection_id, tenant_id, workspace_id, attempt_id,
                                *, confirm_vectors=False):
        vectors_clean = False
        try:
            with self._effect_guard(document_id, attempt_id, tenant_id, workspace_id,
                                    collection_id=collection_id, allow_tombstone=True):
                _scoped_call(self.vectors.delete_document, document_id, collection_id,
                             tenant_id=tenant_id, workspace_id=workspace_id)
                vectors_clean = True
        except OwnershipLostError:
            raise
        except (Exception, CancelledError):
            # A failed index delete must not hide the failed job or leak the
            # original exception. The retrieval status gate is the second line
            # of defense for this case.
            pass
        # A lost delete acknowledgement can still be settled by an exact
        # scoped zero count. Unavailable/malformed confirmation stays pending.
        if confirm_vectors:
            vectors_clean = False
            try:
                with self._effect_guard(document_id, attempt_id, tenant_id, workspace_id,
                                        collection_id=collection_id, allow_tombstone=True):
                    remaining = _scoped_call(self.vectors.count_for_document, document_id, collection_id,
                        tenant_id=tenant_id, workspace_id=workspace_id)
                    vectors_clean = type(remaining) is int and remaining == 0
            except OwnershipLostError:
                raise
            except (Exception, CancelledError):
                pass
        document = _scoped_call(self.knowledge.get_document, document_id,
            tenant_id=tenant_id, workspace_id=workspace_id)
        if document is not None and document.status == 'deleted':
            # Cleanup never revives an operator's retained deletion marker.
            return vectors_clean
        set_status = getattr(self.knowledge, "set_document_status", None)
        if callable(set_status):
            try:
                clear_chunks = getattr(self.knowledge, "replace_document_chunks", None)
                if callable(clear_chunks):
                    with self._effect_guard(document_id, attempt_id, tenant_id, workspace_id,
                                            collection_id=collection_id):
                        _scoped_call(clear_chunks, document_id, [], tenant_id=tenant_id, workspace_id=workspace_id)
                with self._effect_guard(document_id, attempt_id, tenant_id, workspace_id,
                                        collection_id=collection_id):
                    _scoped_call(set_status, document_id, "failed", tenant_id=tenant_id, workspace_id=workspace_id)
                return vectors_clean
            except OwnershipLostError:
                raise
            except (Exception, CancelledError):
                pass
        # A minimal external adapter may not expose the failed-state update;
        # tombstone it as the last-resort visibility barrier.
        delete_document = getattr(self.knowledge, "delete_document", None)
        # Retain ownership authority for a later retry while vectors remain.
        if vectors_clean and callable(delete_document):
            try:
                with self._effect_guard(document_id, attempt_id, tenant_id, workspace_id,
                                        collection_id=collection_id):
                    _scoped_call(delete_document, document_id, tenant_id=tenant_id, workspace_id=workspace_id)
            except OwnershipLostError:
                raise
            except (Exception, CancelledError):
                pass
        return False

    @staticmethod
    def _snapshot_points(
        vectors: object,
        document_id: str,
        collection_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> list[dict]:
        """Take a complete, scoped, bounded compensation snapshot."""

        scoped_snapshot = getattr(vectors, "snapshot_document", None)
        all_points = getattr(vectors, "all_points", None)
        if callable(scoped_snapshot):
            try:
                points = scoped_snapshot(
                    document_id,
                    collection_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )
            except Exception:
                raise RuntimeError("could not obtain complete compensation snapshot") from None
        elif callable(all_points):
            try:
                try:
                    points = all_points(limit=MAX_POINT_SNAPSHOT)
                except TypeError:
                    points = all_points()
            except Exception:
                raise RuntimeError("could not obtain complete compensation snapshot") from None
        else:
            raise RuntimeError("vector adapter cannot provide a compensation snapshot")
        snapshot: list[dict] = []
        total_bytes = 0
        for index, point in enumerate(islice(points, MAX_POINT_SNAPSHOT + 1)):
            if index == MAX_POINT_SNAPSHOT:
                raise RuntimeError("complete compensation snapshot exceeds read limit")
            if not isinstance(point, dict):
                continue
            payload = point.get("payload")
            if not isinstance(payload, dict):
                continue
            if (
                payload.get("document_id") != document_id
                or payload.get("collection_id") != collection_id
                or payload.get("tenant_id") != tenant_id
                or payload.get("workspace_id") != workspace_id
            ):
                continue
            copied = dict(point)
            copied["payload"] = dict(payload)
            vector = copied.get("vector")
            if isinstance(vector, (list, tuple)):
                copied["vector"] = list(vector)
            try:
                encoded = json.dumps(
                    copied, allow_nan=False, ensure_ascii=False, separators=(",", ":"),
                ).encode("utf-8")
            except (TypeError, ValueError, OverflowError):
                raise RuntimeError("compensation snapshot contains an invalid point") from None
            total_bytes += len(encoded)
            if total_bytes > MAX_POINT_SNAPSHOT_BYTES:
                raise RuntimeError("complete compensation snapshot exceeds byte limit")
            snapshot.append(copied)
        return snapshot

    def _mark_document_failed(self, document_id: str) -> None:
        replace_chunks = getattr(self.knowledge, "replace_document_chunks", None)
        if callable(replace_chunks):
            try:
                replace_chunks(document_id, [])
            except Exception:
                pass
        set_status = getattr(self.knowledge, "set_document_status", None)
        if callable(set_status):
            try:
                set_status(document_id, "failed")
                return
            except Exception:
                pass
        delete_document = getattr(self.knowledge, "delete_document", None)
        if callable(delete_document):
            try:
                delete_document(document_id)
            except Exception:
                pass

    def _rollback_replacement(
        self,
        job: IngestionJob,
        *,
        old_document_id: str,
        collection_id: str,
        old_points: list[dict],
        tenant_id: str,
        workspace_id: str,
        retirement_started: bool = True,
    ) -> None:
        """Restore old effects while retaining the committed new publication."""

        restored = not retirement_started
        if retirement_started and old_points:
            try:
                configured_batch_size = getattr(
                    getattr(self.vectors, "limits", None), "max_points", 1_000,
                )
                batch_size = (
                    min(1_000, configured_batch_size)
                    if type(configured_batch_size) is int and configured_batch_size > 0
                    else 1_000
                )
                planner = getattr(self.vectors, "plan_upsert_batches", None)
                batches = planner(old_points) if callable(planner) else (
                    old_points[offset:offset + batch_size]
                    for offset in range(0, len(old_points), batch_size)
                )
                restored_points = 0
                for batch in batches:
                    if (
                        not isinstance(batch, (list, tuple))
                        or not batch
                        or len(batch) > batch_size
                        or restored_points + len(batch) > len(old_points)
                    ):
                        raise RuntimeError("invalid compensation batch plan")
                    if self.vectors.upsert_points(batch) != len(batch):
                        raise RuntimeError("incomplete compensation write")
                    restored_points += len(batch)
                if restored_points != len(old_points):
                    raise RuntimeError("incomplete compensation batch plan")
                restored = _scoped_call(
                    self.vectors.count_for_document,
                    old_document_id,
                    collection_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                ) == len(old_points)
            except (Exception, CancelledError):
                restored = False
        try:
            _scoped_call(
                self.knowledge.set_document_status,
                old_document_id,
                "published" if restored else "unpublished",
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
        except (Exception, CancelledError):
            # A failed restore is safer as unpublished than as a misleading
            # published record with an unknown index state.
            restored = False
            try:
                _scoped_call(
                    self.knowledge.set_document_status,
                    old_document_id,
                    "unpublished",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )
            except (Exception, CancelledError):
                pass
        job.metadata['retirement_pending'] = True
        job.metadata["retirement_deferred"] = "storage_unavailable"
        job.metadata["retirement_error_after_commit"] = True
        job.metadata["previous_document_id"] = old_document_id
        job.metadata["previous_publication_restored"] = restored
    @staticmethod
    def _failure_code(job: IngestionJob) -> str:
        """Classify infrastructure failures without exposing exception text."""
        if job.stage == "embedding":
            return "provider_unavailable"
        if job.stage in {"indexing", "verifying"}:
            return "storage_unavailable"
        return "ingestion_failed"    # -- ingest --------------------------------------------------------
    def ingest(self, path: Path, *, workspace_id: str, collection_id: str,
               tenant_id: str,
               display_filename: str | None = None, request_id: str | None = None,
               correlation_id: str | None = None, job_id: str | None = None,
               cancel_check: Callable[[], bool] | None = None,
               lease_lost_check: Callable[[], bool] | None = None,
               publication_guard: Callable[[], object] | None = None,
               document_metadata: Mapping[str, object] | None = None,
               declared_mime: str | None = None, _recovery_metadata=None) -> IngestionJob:
        with self._operation_lock:
            return self._ingest(
                path, workspace_id=workspace_id, collection_id=collection_id,
                tenant_id=tenant_id, display_filename=display_filename,
                request_id=request_id, correlation_id=correlation_id, job_id=job_id,
                cancel_check=cancel_check, lease_lost_check=lease_lost_check,
                publication_guard=publication_guard,
                document_metadata=document_metadata, declared_mime=declared_mime,
                _recovery_metadata=_recovery_metadata,
            )

    def _ingest(self, path: Path, *, workspace_id: str, collection_id: str,
                tenant_id: str, display_filename: str | None = None,
                request_id: str | None = None, correlation_id: str | None = None,
                job_id: str | None = None,
                cancel_check: Callable[[], bool] | None = None,
                lease_lost_check: Callable[[], bool] | None = None,
                publication_guard: Callable[[], object] | None = None,
                document_metadata: Mapping[str, object] | None = None,
                declared_mime: str | None = None, _recovery_metadata=None) -> IngestionJob:
        tenant_id = normalize_tenant_id(tenant_id)
        collection_id = normalize_collection_id(collection_id)
        recovered = None
        if job_id is not None:
            recovered = self.recover_publication(job_id, tenant_id=tenant_id,
                workspace_id=workspace_id, collection_id=collection_id)
            if recovered is not None and recovered.status in {"verifying", "published", "cancelled"}:
                return recovered
        safe_document_metadata = _safe_document_metadata(document_metadata)
        attempt_id = (_recovery_metadata or {}).get('publication_attempt') or uuid4().hex
        safe_document_metadata[ATTEMPT_METADATA_KEY] = attempt_id
        job_kwargs = {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "collection_id": collection_id,
        }
        if job_id is not None:
            job_kwargs["job_id"] = job_id
        job = IngestionJob(**job_kwargs)
        if job_id is not None and recovered is not None:
            job.attempt = recovered.attempt + 1
            job.created_at = recovered.created_at
            job.metadata.update(deepcopy(recovered.metadata))
        job.metadata.update(_recovery_metadata or {})
        if 'queue_attempt' in job.metadata:
            job.attempt = job.metadata['queue_attempt']
        for key in ('created_at', 'started_at'):
            if 'queue_' + key in job.metadata:
                setattr(job, key, job.metadata['queue_' + key])
        checkpoint = None
        resumed_outputs = False
        checkpoint_getter = getattr(self.knowledge, 'get_ingestion_checkpoint', None)
        if callable(checkpoint_getter):
            checkpoint = checkpoint_getter(job.job_id, tenant_id=tenant_id,
                workspace_id=workspace_id, collection_id=collection_id)
            if checkpoint is not None and (recovered is None or checkpoint['job_snapshot']['attempt'] == job.attempt):
                saved = checkpoint['job_snapshot']
                canonical_attempt = (_recovery_metadata or {}).get('queue_attempt')
                if checkpoint['state'] in {'active', 'cancelled'} and (canonical_attempt is None or canonical_attempt == saved['attempt']):
                    if (_recovery_metadata or {}).get('publication_attempt', checkpoint['attempt_id']) != checkpoint['attempt_id']:
                        raise OwnershipLostError('canonical checkpoint attempt changed')
                    attempt_id = checkpoint['attempt_id']
                    resumed_outputs = bool(checkpoint['artifacts'])
                    for key, value in saved.items():
                        setattr(job, key, deepcopy(value))
                    job.cancel_requested = bool(checkpoint['cancel_requested'])
                elif canonical_attempt is None:
                    job.attempt = saved['attempt'] + 1
                    job.created_at = saved['created_at']
        job.metadata["publication_attempt"] = attempt_id
        safe_document_metadata[ATTEMPT_METADATA_KEY] = attempt_id
        publication_snapshot(job)
        begin_checkpoint = getattr(self.knowledge, 'begin_ingestion_checkpoint', None)
        if callable(begin_checkpoint):
            checkpoint = begin_checkpoint(job)
            job.cancel_requested = bool(checkpoint['cancel_requested'])
        job._lease_lost_check = lease_lost_check
        self._register_job(job)
        document_id: str | None = None
        document_written = False
        publication_committed = False
        publication_attempted = False
        base_event = {"job_id": job.job_id, "workspace_id": workspace_id,
                      "collection_id": collection_id, "request_id": request_id,
                      "correlation_id": correlation_id}

        def advance(to_status: str, **kwargs: Any) -> None:
            self._checkpoint(job, cancel_check)
            job.transition(to_status, **kwargs)

        def heartbeat(**fields: Any) -> None:
            self._checkpoint(job, cancel_check)
            job.heartbeat(**fields)

        def project_publication():
            # The document commit is the point of no return. Lease loss on
            # guard exit cannot rewrite that outcome or erase its data.
            with self._lock:
                # The adapter's commit decision also owns normal completion;
                # do not substitute the later notification/transition clock.
                receipt = self.knowledge.get_publication(job.job_id, tenant_id=tenant_id,
                    workspace_id=workspace_id, collection_id=collection_id)
                if (receipt is None or receipt['outcome'] != 'committed'
                        or receipt['attempt_id'] != job.metadata['publication_attempt']
                        or receipt['document_id'] != job.document_id):
                    raise OwnershipLostError('publication completion authority changed')
                saved = receipt['job_snapshot']
                validate_publication_snapshot(saved, attempt_id=receipt['attempt_id'],
                                              document_attempt=receipt['document_attempt'])
                if any(getattr(job, key) != saved[key] for key in ('attempt', 'created_at', 'started_at')):
                    raise OwnershipLostError('publication completion attempt facts changed')
                if job.status != "published":
                    job.transition("published", progress=1.0)
                job.finished_at = saved['finished_at']
        def finish_publication(*, guard_error=False):
            project_publication()
            if guard_error:
                job.metadata["publication_guard_error_after_commit"] = True
            finish_checkpoint = getattr(self.knowledge, 'finish_ingestion_checkpoint', None)
            if callable(finish_checkpoint):
                try:
                    finish_checkpoint(job)
                except (Exception, CancelledError):
                    job.metadata['checkpoint_cleanup_pending'] = True
            save = getattr(self.knowledge, 'save_publication_snapshot', None)
            if callable(save):
                try:
                    save(job)
                except (Exception, CancelledError):
                    job.metadata['publication_snapshot_pending'] = True
            try:
                self.events.emit({**base_event, "type": "ingestion.completed", "document_id": document_id,
                                  **({"deduplicated": True} if job.metadata.get("deduplicated") else
                                     {"chunks": len(chunks), "points": indexed})})
            except (Exception, CancelledError):
                # Completion is a notification of an authoritative commit.
                # Delivery may have happened before the callback raised; do
                # not replay it, compensate, or misreport the public outcome.
                job.metadata["completion_notification_error_after_commit"] = True
            return job

        def publish_duplicate():
            nonlocal publication_committed, publication_attempted
            job.metadata["deduplicated"] = True
            if job.status == "validating":
                for stage, progress in (("parsing", .5), ("chunking", .7), ("embedding", .8), ("indexing", .9)):
                    advance(stage, progress=progress)
            advance("verifying", progress=.95)
            publish_context = publication_guard() if callable(publication_guard) else nullcontext()
            with publish_context as guard:
                check = getattr(guard, "check", None)
                if callable(check):
                    check()
                # Order is collection -> document -> local job state. The
                # final catalog read and publication decision share the same
                # guard used by every catalog writer, including archive.
                with self.knowledge.collection_guard(tenant_id=tenant_id,
                        workspace_id=workspace_id, collection_id=collection_id):
                    with self.knowledge.mutation_guard("document:" + document_id):
                        self._checkpoint(job, cancel_check)
                        current = _scoped_call(self.knowledge.get_document, document_id,
                                               tenant_id=tenant_id, workspace_id=workspace_id)
                        if current is None or current.status != "published":
                            raise OwnershipLostError("publication changed before deduplication")
                        collection = self.knowledge.get_collection(workspace_id, collection_id, tenant_id=tenant_id)
                        if collection is None or collection.status != "active":
                            raise ParseError("validation_error", "Collection is archived.")
                        with self._lock:
                            self._checkpoint(job, cancel_check)
                            begin = getattr(self.knowledge, "begin_publication", None)
                            job.metadata['published_document_attempt'] = current.metadata.get(ATTEMPT_METADATA_KEY)
                            if callable(begin):
                                begin(job, document_attempt=current.metadata.get(ATTEMPT_METADATA_KEY))
                                publication_attempted = True
                                self._publication_pending.add(job.job_id)
                                receipt = self.knowledge.get_publication(job.job_id, tenant_id=tenant_id,
                                    workspace_id=workspace_id, collection_id=collection_id)
                                if receipt['cancel_requested']:
                                    job.cancel_requested = True
                                    raise _CancellationRequested()
                                self.knowledge.resolve_publication(receipt, "committed")
                            publication_committed = True
                            project_publication()
            return finish_publication()

        def recover_attempt(exc):
            nonlocal publication_committed
            receipt = None
            # Commit outcome precedes error classification. Typed parser or
            # embedding errors may also originate in a guard's exit/callback;
            # no postcommit category has authority to compensate publication.
            if publication_attempted and not publication_committed:
                # An adapter can commit and then lose its acknowledgement.
                # Resolve that uncertainty under the actual effect fence;
                # another attempt's published document is never our commit.
                for _ in range(3):
                    try:
                        with self.knowledge.mutation_guard("document:" + document_id):
                            committed_document = _scoped_call(self.knowledge.get_document, document_id,
                                tenant_id=tenant_id, workspace_id=workspace_id)
                            owned_commit = bool(committed_document is not None
                                and committed_document.status == "published"
                                and committed_document.metadata.get(ATTEMPT_METADATA_KEY) == attempt_id)
                            if callable(getattr(self.knowledge, "get_publication", None)):
                                receipt = self.knowledge.get_publication(job.job_id, tenant_id=tenant_id,
                                    workspace_id=workspace_id, collection_id=collection_id)
                                if receipt is None or receipt['attempt_id'] != attempt_id:
                                    raise OwnershipLostError('publication attempt changed')
                                job.cancel_requested = job.cancel_requested or receipt['cancel_requested']
                                owned_commit = receipt['outcome'] == 'committed' or owned_commit
                        publication_committed = owned_commit
                        break
                    except (Exception, CancelledError):
                        continue
                else:
                    # A failed read is not evidence that publication failed.
                    # Keep cancellation nonterminal and retain every effect
                    # until explicit reconciliation can establish the outcome.
                    with self._lock:
                        job.metadata["publication_outcome_unknown"] = True
                        self._publication_recovery[job.job_id] = lambda: recover_attempt(exc)
                    return job
            if receipt is not None and receipt['outcome'] == 'pending' and not publication_committed:
                # An already-ready intent has one durable recovery owner in
                # both the live process and a restart. A captured exception
                # must not discard verified work when the authority returns.
                recovered = self.recover_publication(job.job_id, tenant_id=tenant_id,
                    workspace_id=workspace_id, collection_id=collection_id, snapshot=job)
                if recovered.status == 'verifying':
                    with self._lock:
                        self._publication_recovery[job.job_id] = lambda: recover_attempt(exc)
                    return recovered
                with self._lock:
                    self._publication_recovery.pop(job.job_id, None)
                if recovered.status == 'published':
                    publication_committed = True
                    return finish_publication(guard_error=True)
                try:
                    self.events.emit({**base_event, 'type': 'ingestion.' + recovered.status,
                        'error_code': recovered.error_code})
                except (Exception, CancelledError):
                    pass
                return recovered
            with self._lock:
                job.metadata.pop("publication_outcome_unknown", None)
                self._publication_recovery.pop(job.job_id, None)
            if publication_committed:
                return finish_publication(guard_error=True)
            cleanup_complete = self._cleanup_failed_document(
                document_id, collection_id, document_written=document_written,
                tenant_id=tenant_id, workspace_id=workspace_id, attempt_id=attempt_id,
                confirm_vectors=(isinstance(exc, _CancellationRequested)
                    or job.status == "cancelled" or job.cancel_requested),
            )
            with self._lock:
                cancelled = (isinstance(exc, _CancellationRequested)
                             or job.status == "cancelled" or job.cancel_requested)
                if cancelled:
                    job.cancel_requested = True
                    if not cleanup_complete:
                        self._cancellation_cleanup_pending(job)
                        return job
                    job.metadata.pop('cancellation_cleanup_pending', None)
                    if job.status != "cancelled":
                        job.transition("cancelled", message="Cancelled by operator.")
                else:
                    if isinstance(exc, (ParseError, _EmbeddingBatchError)):
                        error_code = exc.code
                        message = exc.args[0] if exc.args else "Ingestion failed."
                    else:
                        error_code = "lock_unavailable" if getattr(exc, "code", None) == "lock_unavailable" else self._failure_code(job)
                        message = "Ingestion failed."
                    job.transition("failed", error_code=error_code, message=message)
            finish_checkpoint = getattr(self.knowledge, 'finish_ingestion_checkpoint', None)
            if callable(finish_checkpoint):
                finish_checkpoint(job)
            if cancelled:
                if job.metadata.get('cancellation_notification_attempted'):
                    return job
                try:
                    self.events.emit({**base_event, "type": "ingestion.cancelled"})
                except CancelledError:
                    job.metadata["failure_notification_cancelled"] = True
                return job
            try:
                self.events.emit({**base_event, "type": "ingestion.failed", "error_code": error_code,
                                  "retryable": is_retryable(error_code)})
            except CancelledError:
                # The cancellation has been compensated and terminalized.
                # A cancelled notification cannot orphan the durable outcome.
                job.metadata["failure_notification_cancelled"] = True
            return job

        try:
            self.events.emit({**base_event, "type": "ingestion.start", "stage": "validating"})
            advance("validating", progress=0.05)
            if self.parser_limits is None and declared_mime is None:
                # Preserve the historical validator call shape for narrow
                # adapters that replace it in an embedding application.
                validate_file(path)
            else:
                validate_file(
                    path,
                    limits=self.parser_limits or DEFAULT_PARSER_LIMITS,
                    declared_mime=declared_mime,
                )
            self._checkpoint(job, cancel_check)
            checksum = checksum_file(path)
            collection = self.knowledge.get_collection(workspace_id, collection_id, tenant_id=tenant_id)
            if collection is not None and collection.status != "active":
                raise ParseError("validation_error", "Collection is archived.")
            # The HTTP adapter negotiates dense/sparse schema before parsing,
            # deduplication or any knowledge/index mutation. Local adapters
            # continue to use the minimal VectorStore protocol.
            prepare_index = getattr(self.vectors, "prepare_index", None)
            prepared_schema = None
            if callable(prepare_index):
                prepared_schema = prepare_index(vector_dimensions=self.embeddings.dimensions)
                job.metadata["index_mode"] = (
                    "hybrid" if getattr(prepared_schema, "sparse_enabled", False) else "dense"
                )
            document_id = document_id_for_content(
                workspace_id=workspace_id,
                collection_id=collection_id,
                checksum=checksum,
                tenant_id=tenant_id,
            )
            legacy_id = legacy_document_id_for_content(workspace_id=workspace_id,
                collection_id=collection_id, checksum=checksum, tenant_id=tenant_id)
            index_key = getattr(self.vectors, "ingestion_index_key", None)
            if callable(index_key):
                contract = index_key(
                    embedding_model=self.embeddings.model, embedding_version=self.embedding_version,
                )
                # A representation is a separate publication candidate. Its
                # failed batches must never overwrite/delete the published
                # points for the same content under a previous index contract.
                document_id = str(uuid5(NAMESPACE_URL, f"rick-index:{document_id}:{contract}"))
                legacy_id = str(uuid5(NAMESPACE_URL, f"rick-index:{legacy_id}:{contract}"))
                safe_document_metadata["vector_index"] = self.vectors.collection
                safe_document_metadata["index_contract"] = contract
                job.metadata["index_contract"] = contract
            # Explicit compatibility lookup: retain deployed identities and
            # citation references only when the complete scope/checksum agrees.
            legacy = _scoped_call(self.knowledge.get_document, legacy_id,
                                  tenant_id=tenant_id, workspace_id=workspace_id)
            if (legacy is not None and legacy.tenant_id == tenant_id
                    and legacy.workspace_id == workspace_id and legacy.collection_id == collection_id
                    and legacy.content_checksum == checksum):
                document_id = legacy_id
                job.metadata["identity_encoding"] = "legacy-v1"
            else:
                job.metadata["identity_encoding"] = "legacy-compatible-v1" if document_id == legacy_id else "tuple-v2"
            job.document_id = document_id

            existing = _scoped_call(
                self.knowledge.get_document,
                document_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            phase = None
            if checkpoint is not None:
                fingerprint = dict(checksum=checksum, document_id=document_id,
                    parser_version=PARSER_VERSION, chunker_version=CHUNKER_VERSION,
                    chunker_type=type(self.chunker).__module__ + '.' + type(self.chunker).__qualname__,
                    chunker_options=vars(self.chunker) if hasattr(self.chunker, '__dict__') else {},
                    parser_limits=asdict(self.parser_limits or DEFAULT_PARSER_LIMITS),
                    embedding_model=self.embeddings.model, embedding_version=self.embedding_version,
                    dimensions=self.embeddings.dimensions, index_contract=job.metadata.get('index_contract'),
                    declared_mime=declared_mime, filename=sanitize_display_filename(display_filename or path.name),
                    document_metadata=safe_document_metadata)
                phase = self.knowledge.save_ingestion_checkpoint(job, fingerprint=fingerprint,
                    artifacts=checkpoint['artifacts'])
                job._phase_checkpoint = phase
                self._checkpoint(job, cancel_check)
            if existing is not None and existing.status == "published":
                # Persist the document identity before the deduplication
                # decision too: its terminal checkpoint must be recoverable.
                return publish_duplicate()
            advance("parsing", progress=0.15)
            heartbeat()
            if self.parser_limits is None:
                # Preserve the historical parser factory call shape for
                # integrations that replace it with a narrow test adapter.
                parser = parser_for(path, pdf_heartbeat=heartbeat)
            else:
                parser = parser_for(path, pdf_heartbeat=heartbeat, limits=self.parser_limits)
            if phase is not None and 'parsed' in phase['artifacts']:
                raw = phase['artifacts']['parsed']
                parsed = ParsedDocument(text=raw['text'], pages=[ParsedPage(**p) for p in raw['pages']])
            else:
                parsed = execute_parser(parser, path, workspace_id=workspace_id,
                    runner=self.parser_runner, timeout_seconds=self.parser_timeout_seconds)
                if phase is not None:
                    phase['artifacts']['parsed'] = dict(text=parsed.text, pages=[asdict(p) for p in parsed.pages])
                    self.knowledge.save_ingestion_checkpoint(job, fingerprint=phase['fingerprint'], artifacts=phase['artifacts'])
                    self._checkpoint(job, cancel_check)

            advance("chunking", progress=0.35)
            if phase is not None and 'plans' in phase['artifacts']:
                plans = [ChunkPlan(**p) for p in phase['artifacts']['plans']]
            else:
                plans = self.chunker.chunk(text=parsed.text,
                    pages=[(p.page_number, p.text) for p in parsed.pages], document_id=document_id)
                if not plans:
                    raise ParseError("validation_error", "Document produced no chunks.")
                if phase is not None:
                    phase['artifacts']['plans'] = [asdict(p) for p in plans]
                    self.knowledge.save_ingestion_checkpoint(job, fingerprint=phase['fingerprint'], artifacts=phase['artifacts'])
                    self._checkpoint(job, cancel_check)

            advance("embedding", progress=0.55)
            vectors = _embed_in_batches(self, job, plans, cancel_check)

            advance("indexing", progress=0.75)
            version = document_version(checksum)
            document = Document(
                document_id=document_id, workspace_id=workspace_id, collection_id=collection_id,
                tenant_id=tenant_id,
                document_version=version, content_checksum=checksum,
                filename=sanitize_display_filename(display_filename or path.name),
                display_filename=sanitize_display_filename(display_filename or path.name),
                title=sanitize_display_filename(display_filename or path.name),
                source_type=path.suffix.lower().lstrip(".") or "unknown",
                status="processing", parser_version=PARSER_VERSION,
                chunker_version=CHUNKER_VERSION,
                embedding_model=self.embeddings.model, embedding_version=self.embedding_version,
                metadata=safe_document_metadata,
            )
            collection = self.knowledge.ensure_collection(Collection(
                workspace_id=workspace_id, collection_id=collection_id,
                tenant_id=tenant_id, title=collection_id,
                metadata=(
                    {"created_by": safe_document_metadata["created_by"]}
                    if "created_by" in safe_document_metadata else {}
                ),
            ))
            if collection.status != "active":
                raise ParseError("validation_error", "Collection is archived.")
            became_published = False
            with self.knowledge.mutation_guard("document:" + document_id):
                self._checkpoint(job, cancel_check)
                collection = self.knowledge.get_collection(workspace_id, collection_id, tenant_id=tenant_id)
                if collection is None or collection.status != "active":
                    raise ParseError("validation_error", "Collection is archived.")
                current = _scoped_call(self.knowledge.get_document, document_id,
                                       tenant_id=tenant_id, workspace_id=workspace_id)
                if current is not None and current.status == "published":
                    became_published = True
                else:
                    if current is not None and current.status == "deleted":
                        raise ParseError("validation_error", "Deleted document cannot be reingested.")
                    if resumed_outputs and current is not None and current.metadata.get(ATTEMPT_METADATA_KEY) != attempt_id:
                        raise OwnershipLostError('resumed checkpoint no longer owns document')
                    if resumed_outputs and current is not None:
                        # Preserve the original lineage/timestamps so replay
                        # cannot change an already authorized point manifest.
                        document = deepcopy(current)
                    document_written = True
                    self.knowledge.upsert_document(document)
                    require_owner(_scoped_call(self.knowledge.get_document, document_id,
                        tenant_id=tenant_id, workspace_id=workspace_id), attempt_id)
                    if current is not None and current.metadata.get(ATTEMPT_METADATA_KEY) != attempt_id:
                        # Retire the former owner's partial vectors before this
                        # attempt starts. A takeover must repair, not ignore them.
                        _scoped_call(self.vectors.delete_document, document_id, collection_id,
                                     tenant_id=tenant_id, workspace_id=workspace_id)
                        require_owner(_scoped_call(self.knowledge.get_document, document_id,
                            tenant_id=tenant_id, workspace_id=workspace_id), attempt_id)
            if became_published:
                # Release the claim's document guard before acquiring the
                # publication collection guard, so the lock order cannot invert.
                return publish_duplicate()
            from rick_knowledge import Chunk as KnowledgeChunk

            chunks = [
                KnowledgeChunk(
                    chunk_id=chunk_id_for_document(document_id, plan.chunk_index),
                    document_id=document_id, tenant_id=tenant_id,
                    chunk_index=plan.chunk_index, text=plan.text,
                    page_start=plan.page_start,
                    page_end=plan.page_end if plan.page_end is not None else plan.page_start,
                    checksum=plan.checksum, parser_version=PARSER_VERSION,
                    chunker_version=CHUNKER_VERSION,
                    embedding_version=self.embedding_version,
                )
                for plan in plans
            ]
            with self._effect_guard(document_id, attempt_id, tenant_id, workspace_id, job, cancel_check):
                _scoped_call(self.knowledge.replace_document_chunks, document_id, chunks,
                             tenant_id=tenant_id, workspace_id=workspace_id)
            from rick_knowledge import build_point_payload

            points = []
            for chunk, vector in zip(chunks, vectors):
                payload = build_point_payload(chunk=chunk, document=document)
                points.append({"point_id": self._point_id(chunk.chunk_id),
                               "vector": vector, "payload": payload})
            planner = getattr(self.vectors, "plan_upsert_batches", None)
            batches = planner(points) if callable(planner) else tuple(
                points[offset:offset + MAX_EMBEDDING_BATCH]
                for offset in range(0, len(points), MAX_EMBEDDING_BATCH)
            )
            if phase is not None:
                # Authorize the adapter's exact effect representation before
                # issuing any point write. Batches remain bounded by its planner.
                batches = tuple(batches)
                phase['artifacts']['point_manifest'] = self._point_manifest(
                    [p for batch in batches for p in batch])
                self.knowledge.save_ingestion_checkpoint(job, fingerprint=phase['fingerprint'],
                    artifacts=phase['artifacts'])
            indexed = 0
            for batch in batches:
                with self._effect_guard(document_id, attempt_id, tenant_id, workspace_id, job, cancel_check):
                    batch_indexed = self.vectors.upsert_points(batch)
                if type(batch_indexed) is not int or batch_indexed != len(batch):
                    raise RuntimeError("index failed: batch result differs from point count")
                indexed += batch_indexed

            advance("verifying", progress=0.9)
            if _scoped_call(
                self.vectors.count_for_document,
                document_id,
                collection_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            ) < len(chunks):
                raise RuntimeError("verify failed: indexed points below chunk count")
            if callable(prepare_index) and prepare_index(
                vector_dimensions=self.embeddings.dimensions,
            ) != prepared_schema:
                raise RuntimeError("index schema changed before publication")
            publish_context = publication_guard() if callable(publication_guard) else nullcontext()
            with publish_context as guard:
                check = getattr(guard, "check", None)
                if callable(check):
                    check()
                with self.knowledge.collection_guard(tenant_id=tenant_id,
                        workspace_id=workspace_id, collection_id=collection_id):
                    with self._effect_guard(document_id, attempt_id, tenant_id, workspace_id, job, cancel_check):
                        with self._lock:
                            self._checkpoint(job, cancel_check)
                            begin = getattr(self.knowledge, "begin_publication", None)
                            if callable(begin):
                                begin(job, ready_count=len(chunks))
                            publication_attempted = True
                            self._publication_pending.add(job.job_id)
                            receipt = self.knowledge.get_publication(job.job_id, tenant_id=tenant_id,
                                workspace_id=workspace_id, collection_id=collection_id) if callable(begin) else None
                            if receipt is not None:
                                if receipt['attempt_id'] != attempt_id or receipt['outcome'] != 'pending':
                                    raise OwnershipLostError('publication decision changed')
                                if receipt['cancel_requested']:
                                    job.cancel_requested = True
                                    raise _CancellationRequested()
                            _scoped_call(self.knowledge.set_document_status, document_id, 'published',
                                tenant_id=tenant_id, workspace_id=workspace_id)
                            publication_committed = True
                            project_publication()
            return finish_publication()
        except (Exception, CancelledError) as exc:
            if not publication_committed and (isinstance(exc, _ExecutionOwnershipLost)
                    or callable(lease_lost_check) and lease_lost_check()):
                # This execution lost its lease. The checkpoint/recovery owner
                # retains all durable work and effects; loss is not cancellation.
                raise _ExecutionOwnershipLost('execution lease changed') from exc
            if isinstance(exc, OwnershipLostError) and not document_written:
                raise
            return recover_attempt(exc)
        finally:
            job.__dict__.pop('_phase_checkpoint', None)
            job.__dict__.pop('_lease_lost_check', None)
            with self._lock:
                if job.job_id not in self._publication_recovery:
                    self._publication_pending.discard(job.job_id)

    def reindex(self, document_id: str, path: Path, **kwargs: Any) -> IngestionJob:
        """Changed content → new version; stale vectors for replaced versions pruned."""
        with self._operation_lock:
            return self._reindex(document_id, path, **kwargs)

    def _reindex(self, document_id: str, path: Path, **kwargs: Any) -> IngestionJob:
        previous = deepcopy(_scoped_call(
            self.knowledge.get_document,
            document_id,
            tenant_id=kwargs.get("tenant_id"),
            workspace_id=kwargs.get("workspace_id"),
        ))
        recovery_metadata = dict(kwargs.pop('_recovery_metadata', None) or {})
        if previous is not None and (previous.tenant_id, previous.workspace_id, previous.collection_id) != (
                kwargs.get('tenant_id'), kwargs.get('workspace_id'), normalize_collection_id(kwargs.get('collection_id'))):
            raise OwnershipLostError('replacement scope changed')
        if previous is not None:
            recovery_metadata.update(previous_document_id=document_id,
                previous_document_attempt=previous.metadata.get(ATTEMPT_METADATA_KEY), retirement_pending=True)
        job = self.ingest(path, _recovery_metadata=recovery_metadata, **kwargs)
        try:
            result = self._finalize_reindex(job, document_id, previous, **kwargs)
            if result.status == 'published':
                self.knowledge.save_publication_snapshot(result)
            return result
        except (Exception, CancelledError):
            # The new publication has already committed. A callback, guard
            # acquisition or scoped read error can defer retirement, but it
            # cannot turn that real outcome into an exception to the worker.
            if job.status == "published":
                job.metadata["retirement_deferred"] = "lock_unavailable"
                job.metadata["retirement_error_after_commit"] = True
                job.metadata["previous_document_id"] = document_id
                try:
                    self.knowledge.save_publication_snapshot(job)
                except (Exception, CancelledError):
                    job.metadata['publication_snapshot_pending'] = True
            return job

    def _finalize_reindex(self, job, document_id, previous, **kwargs):
        # A failed replacement must not remove the currently published
        # version. Only commit the old-version retirement after the new
        # attempt has crossed the publication gate.
        if (
            previous is not None
            and job.status == "published"
            and job.document_id
            and job.document_id != document_id
        ):
            # A replay of a committed job retains its original retirement
            # authority. Today's old-document owner cannot replace the owner
            # persisted with that publication, even after recovery deferred it.
            if (job.metadata.get('previous_document_id') != document_id
                    or job.metadata.get('previous_document_attempt') !=
                        previous.metadata.get(ATTEMPT_METADATA_KEY)):
                job.metadata['retirement_superseded'] = True
                return job
            if job.metadata.get("publication_guard_error_after_commit"):
                job.metadata["retirement_deferred"] = "lock_unavailable"
                job.metadata["previous_document_id"] = document_id
                return job
            index_key = getattr(self.vectors, "ingestion_index_key", None)
            previous_index = (getattr(previous, "metadata", None) or {}).get("vector_index")
            if callable(index_key) and previous_index != getattr(self.vectors, "collection", None):
                # A cross-index rebuild does not retire the old publication.
                # Alias activation is a separate manifest-checked operation;
                # leave the old document and vectors readable for rollback.
                job.metadata["previous_document_id"] = document_id
                job.metadata["index_activation_required"] = True
                self.events.emit({
                    "type": "ingestion.reindex.staged", "job_id": job.job_id,
                    "document_id": job.document_id, "previous_document_id": document_id,
                })
                return job
            # Publication already committed. A lease lost on its guard exit
            # defers retirement; it cannot roll back the committed document.
            cancel_check = kwargs.get("cancel_check")
            if callable(cancel_check) and cancel_check():
                job.metadata["retirement_deferred"] = "lock_unavailable"
                return job
            with ExitStack() as guards:
                for identity in sorted({document_id, job.document_id}):
                    guards.enter_context(self.knowledge.mutation_guard("document:" + identity))
                if callable(cancel_check) and cancel_check():
                    job.metadata["retirement_deferred"] = "lock_unavailable"
                    job.metadata["previous_document_id"] = document_id
                    return job
                current_old = _scoped_call(self.knowledge.get_document, document_id,
                    tenant_id=kwargs["tenant_id"], workspace_id=kwargs["workspace_id"])
                current_new = _scoped_call(self.knowledge.get_document, job.document_id,
                    tenant_id=kwargs["tenant_id"], workspace_id=kwargs["workspace_id"])
                if (current_old is None or current_old.status != previous.status
                    or current_old.collection_id != job.collection_id
                    or current_old.metadata.get(ATTEMPT_METADATA_KEY) != previous.metadata.get(ATTEMPT_METADATA_KEY)
                    or current_new is None or current_new.status != "published"
                    or current_new.collection_id != job.collection_id
                    or (not job.metadata.get("deduplicated") and
                        current_new.metadata.get(ATTEMPT_METADATA_KEY) != job.metadata["publication_attempt"])):
                    job.metadata["retirement_deferred"] = "lock_unavailable"
                    return job
                if current_old.status == 'unpublished':
                    # A hidden index can already be partial. Retire its
                    # remaining effects without treating them as a snapshot
                    # from which the old publication could be restored.
                    _scoped_call(self.vectors.delete_document, document_id,
                        job.collection_id, tenant_id=job.tenant_id,
                        workspace_id=job.workspace_id)
                    job.metadata['retirement_pending'] = False
                    return job
                self._retire_replacement(job, document_id,
                    retirement_documents=(deepcopy(current_old), deepcopy(current_new)),
                    **kwargs)
        return job

    def _retire_replacement(self, job, document_id, **kwargs):
        """Caller holds both document guards through retirement AND rollback."""
        if job.status == "published":
            old_points: list[dict] = []
            retirement_started = False
            incomplete_snapshot = False
            owners = kwargs.get('retirement_documents')

            def still_owned():
                if owners is None:
                    return True
                for saved in owners:
                    current = _scoped_call(self.knowledge.get_document, saved.document_id,
                        tenant_id=kwargs['tenant_id'], workspace_id=kwargs['workspace_id'])
                    if (current is None or current.status not in {'published', 'unpublished'}
                            or (saved.document_id == job.document_id and current.status != 'published')
                            or any(getattr(current, key) != getattr(saved, key) for key in
                                ('tenant_id', 'workspace_id', 'collection_id', 'content_checksum',
                                 'document_version', 'object_ref', 'filename'))
                            or current.metadata.get(ATTEMPT_METADATA_KEY) != saved.metadata.get(ATTEMPT_METADATA_KEY)):
                        return False
                return True

            try:
                collection_id = normalize_collection_id(kwargs.get("collection_id", "rag_phase0"))
                old_count = _scoped_call(
                    self.vectors.count_for_document,
                    document_id,
                    collection_id,
                    tenant_id=kwargs["tenant_id"],
                    workspace_id=kwargs["workspace_id"],
                )
                if type(old_count) is not int or old_count <= 0:
                    incomplete_snapshot = owners is not None and type(old_count) is int and old_count == 0
                    raise RuntimeError("published replacement has no restorable vectors")
                old_points = self._snapshot_points(
                    self.vectors,
                    document_id,
                    collection_id,
                    tenant_id=kwargs["tenant_id"],
                    workspace_id=kwargs["workspace_id"],
                )
                if len(old_points) != old_count:
                    incomplete_snapshot = owners is not None
                    raise RuntimeError("compensation snapshot does not match scoped point count")
                if owners is not None:
                    old = owners[0]
                    chunks = _scoped_call(self.knowledge.get_chunks, document_id,
                        tenant_id=kwargs['tenant_id'], workspace_id=kwargs['workspace_id'])
                    from rick_knowledge import build_point_payload
                    expected = {self._point_id(chunk.chunk_id): build_point_payload(chunk=chunk, document=old)
                                for chunk in chunks}
                    source_fields = ('chunk_id', 'document_version', 'ingestion_version', 'checksum',
                                     'object_ref', 'source', 'text', 'parser_version', 'chunker_version',
                                     'embedding_model', 'embedding_version')
                    if (len(expected) != old_count or len({point['point_id'] for point in old_points}) != old_count
                            or any(point['point_id'] not in expected or any(
                                point['payload'].get(key) != expected[point['point_id']].get(key)
                                for key in source_fields) for point in old_points)):
                        incomplete_snapshot = True
                        raise RuntimeError('compensation snapshot source facts changed')
                retirement_started = True
                _scoped_call(
                    self.vectors.delete_document,
                    document_id,
                    collection_id,
                    tenant_id=kwargs["tenant_id"],
                    workspace_id=kwargs["workspace_id"],
                )
                _scoped_call(
                    self.knowledge.set_document_status,
                    document_id,
                    "unpublished",
                    tenant_id=kwargs["tenant_id"],
                    workspace_id=kwargs["workspace_id"],
                )
            except (Exception, CancelledError) as exc:
                if not still_owned():
                    job.metadata['retirement_pending'] = False
                    job.metadata['retirement_superseded'] = True
                    return job
                if incomplete_snapshot:
                    # Conclusive missing/foreign source facts are not a
                    # complete restoration snapshot. Hide only the still-owned
                    # old version and leave its partial vectors untouched.
                    old_points = []
                    retirement_started = True
                self._rollback_replacement(
                    job,
                    old_document_id=document_id,
                    collection_id=normalize_collection_id(kwargs.get("collection_id", "rag_phase0")),
                    old_points=old_points,
                    tenant_id=kwargs["tenant_id"],
                    workspace_id=kwargs["workspace_id"],
                    retirement_started=retirement_started,
                )
            else:
                job.metadata['retirement_pending'] = False
        return job

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        from rick_knowledge import point_id_for_chunk

        return point_id_for_chunk(chunk_id)
