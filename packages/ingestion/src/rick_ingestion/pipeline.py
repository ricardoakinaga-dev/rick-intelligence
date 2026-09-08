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
import inspect
from contextlib import nullcontext
from itertools import islice
from numbers import Real
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Protocol

from rick_ingestion.chunking import CHUNKER_VERSION, RecursiveChunkingStrategy
from rick_ingestion.jobs import DEFAULT_MAX_JOBS, IngestionJob, is_retryable
from rick_ingestion.parsers import (
    PARSER_VERSION,
    ParseError,
    checksum_file,
    parser_for,
    sanitize_display_filename,
    validate_file,
)
from rick_knowledge import (
    Collection,
    Document,
    InMemoryKnowledgeStore,
    chunk_id_for_document,
    document_id_for_content,
    document_version,
    normalize_collection_id,
    normalize_tenant_id,
)


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    def upsert_points(self, points: list[dict]) -> int: ...
    def delete_document(self, document_id: str, collection_id: str) -> int: ...
    def count_for_document(self, document_id: str, collection_id: str) -> int: ...


MAX_POINT_SNAPSHOT = 100_000


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


class IngestionService:
    """Deliberate interface: ingest / reindex / cancel / get_status."""

    def __init__(self, *, knowledge, vectors: VectorStore, embeddings: EmbeddingProvider,
                 events: IngestionEvents | None = None,
                 chunker=None, embedding_version: str = "emb-v1",
                 max_jobs: int = DEFAULT_MAX_JOBS) -> None:
        if isinstance(max_jobs, bool) or not isinstance(max_jobs, int) or not 0 < max_jobs <= 1024:
            raise ValueError("max_jobs is out of range")
        self.knowledge = knowledge
        self.vectors = vectors
        self.embeddings = embeddings
        self.events = events or NullEvents()
        self.chunker = chunker or RecursiveChunkingStrategy()
        self.embedding_version = embedding_version
        self.max_jobs = max_jobs
        self._jobs: dict[str, IngestionJob] = {}
        self._lock = RLock()
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
            job.transition("cancelled", message="Cancelled by operator.")
            self.events.emit({"type": "ingestion.cancelled", "job_id": job_id})
            return True

    def _checkpoint(self, job: IngestionJob, cancel_check: Callable[[], bool] | None) -> None:
        if job.status == "cancelled":
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
    ) -> None:
        """Compensate every local write made before publication.

        The package protocols intentionally stay small, so this is a best-effort
        compensating transaction rather than a claim of distributed atomicity.
        Retrieval also revalidates document publication status, which protects
        the read path when an external adapter cannot complete its delete call.
        """
        if not document_id or not document_written:
            return
        try:
            _scoped_call(
                self.vectors.delete_document,
                document_id,
                collection_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
        except Exception:
            # A failed index delete must not hide the failed job or leak the
            # original exception. The retrieval status gate is the second line
            # of defense for this case.
            pass
        set_status = getattr(self.knowledge, "set_document_status", None)
        if callable(set_status):
            try:
                clear_chunks = getattr(self.knowledge, "replace_document_chunks", None)
                if callable(clear_chunks):
                    _scoped_call(
                        clear_chunks,
                        document_id,
                        [],
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                    )
                _scoped_call(
                    set_status,
                    document_id,
                    "failed",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )
                return
            except Exception:
                pass
        # A minimal external adapter may not expose the failed-state update;
        # tombstone it as the last-resort visibility barrier.
        delete_document = getattr(self.knowledge, "delete_document", None)
        if callable(delete_document):
            try:
                _scoped_call(
                    delete_document,
                    document_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )
            except Exception:
                pass

    @staticmethod
    def _snapshot_points(vectors: object, document_id: str, collection_id: str) -> list[dict]:
        """Take a local compensation snapshot when the adapter exposes points."""

        all_points = getattr(vectors, "all_points", None)
        if not callable(all_points):
            return []
        try:
            try:
                points = all_points(limit=MAX_POINT_SNAPSHOT)
            except TypeError:
                points = all_points()
        except Exception:
            raise RuntimeError("could not obtain complete compensation snapshot") from None
        snapshot: list[dict] = []
        for index, point in enumerate(islice(points, MAX_POINT_SNAPSHOT + 1)):
            if index == MAX_POINT_SNAPSHOT:
                raise RuntimeError("complete compensation snapshot exceeds read limit")
            if not isinstance(point, dict):
                continue
            payload = point.get("payload")
            if not isinstance(payload, dict):
                continue
            if payload.get("document_id") != document_id or payload.get("collection_id") != collection_id:
                continue
            copied = dict(point)
            copied["payload"] = dict(payload)
            vector = copied.get("vector")
            if isinstance(vector, (list, tuple)):
                copied["vector"] = list(vector)
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
        new_document_id: str,
        old_document_id: str,
        collection_id: str,
        old_points: list[dict],
        tenant_id: str,
        workspace_id: str,
        retirement_started: bool = True,
    ) -> None:
        """Make a failed replacement non-searchable and restore old points."""

        # A deduplicated target belongs to an earlier publication, not this
        # replacement attempt. Compensation must never delete its data.
        if not job.metadata.get("deduplicated", False):
            try:
                _scoped_call(
                    self.vectors.delete_document,
                    new_document_id,
                    collection_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )
            except Exception:
                pass
            self._mark_document_failed(new_document_id)

        restored = not retirement_started
        if retirement_started and old_points:
            try:
                for offset in range(0, len(old_points), 1_000):
                    batch = old_points[offset:offset + 1_000]
                    if self.vectors.upsert_points(batch) != len(batch):
                        raise RuntimeError("incomplete compensation write")
                restored = _scoped_call(
                    self.vectors.count_for_document,
                    old_document_id,
                    collection_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                ) == len(old_points)
            except Exception:
                restored = False
        try:
            _scoped_call(
                self.knowledge.set_document_status,
                old_document_id,
                "published" if restored else "unpublished",
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
        except Exception:
            # A failed restore is safer as unpublished than as a misleading
            # published record with an unknown index state.
            try:
                _scoped_call(
                    self.knowledge.set_document_status,
                    old_document_id,
                    "unpublished",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )
            except Exception:
                pass
        try:
            job.compensate_published_failure(
                error_code="storage_unavailable",
                message="Replacement retirement failed.",
            )
        except Exception:
            # The job is already terminal in the only expected call path; do
            # not turn a safe storage rollback into an exception leak.
            pass
        self.events.emit({
            "type": "ingestion.reindex.rollback",
            "job_id": job.job_id,
            "document_id": new_document_id,
            "previous_document_id": old_document_id,
            "error_code": "storage_unavailable",
        })

    @staticmethod
    def _failure_code(job: IngestionJob) -> str:
        """Classify infrastructure failures without exposing exception text."""
        if job.stage == "embedding":
            return "provider_unavailable"
        if job.stage in {"indexing", "verifying"}:
            return "storage_unavailable"
        return "ingestion_failed"

    # -- ingest --------------------------------------------------------
    def ingest(self, path: Path, *, workspace_id: str, collection_id: str,
               tenant_id: str,
               display_filename: str | None = None, request_id: str | None = None,
               correlation_id: str | None = None, job_id: str | None = None,
               cancel_check: Callable[[], bool] | None = None,
               publication_guard: Callable[[], object] | None = None,
               document_metadata: Mapping[str, object] | None = None) -> IngestionJob:
        with self._operation_lock:
            return self._ingest(
                path, workspace_id=workspace_id, collection_id=collection_id,
                tenant_id=tenant_id, display_filename=display_filename,
                request_id=request_id, correlation_id=correlation_id, job_id=job_id,
                cancel_check=cancel_check, publication_guard=publication_guard,
                document_metadata=document_metadata,
            )

    def _ingest(self, path: Path, *, workspace_id: str, collection_id: str,
                tenant_id: str, display_filename: str | None = None,
                request_id: str | None = None, correlation_id: str | None = None,
                job_id: str | None = None,
                cancel_check: Callable[[], bool] | None = None,
                publication_guard: Callable[[], object] | None = None,
                document_metadata: Mapping[str, object] | None = None) -> IngestionJob:
        tenant_id = normalize_tenant_id(tenant_id)
        collection_id = normalize_collection_id(collection_id)
        safe_document_metadata = _safe_document_metadata(document_metadata)
        job_kwargs = {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "collection_id": collection_id,
        }
        if job_id is not None:
            job_kwargs["job_id"] = job_id
        job = IngestionJob(**job_kwargs)
        self._register_job(job)
        document_id: str | None = None
        document_written = False
        base_event = {"job_id": job.job_id, "workspace_id": workspace_id,
                      "collection_id": collection_id, "request_id": request_id,
                      "correlation_id": correlation_id}

        def advance(to_status: str, **kwargs: Any) -> None:
            self._checkpoint(job, cancel_check)
            job.transition(to_status, **kwargs)

        def heartbeat(**fields: Any) -> None:
            self._checkpoint(job, cancel_check)
            job.heartbeat(**fields)

        try:
            self.events.emit({**base_event, "type": "ingestion.start", "stage": "validating"})
            advance("validating", progress=0.05)
            validate_file(path)
            self._checkpoint(job, cancel_check)
            checksum = checksum_file(path)
            document_id = document_id_for_content(
                workspace_id=workspace_id,
                collection_id=collection_id,
                checksum=checksum,
                tenant_id=tenant_id,
            )
            job.document_id = document_id

            existing = _scoped_call(
                self.knowledge.get_document,
                document_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            if existing is not None and existing.status == "published":
                # Idempotent re-ingest: same identities, no duplicate drift.
                job.metadata["deduplicated"] = True
                job.document_id = document_id
                advance("parsing", progress=0.5)
                advance("chunking", progress=0.7)
                advance("embedding", progress=0.8)
                advance("indexing", progress=0.9)
                advance("verifying", progress=0.95)
                publish_context = publication_guard() if callable(publication_guard) else nullcontext()
                with publish_context:
                    with self._lock:
                        self._checkpoint(job, cancel_check)
                        advance("published", progress=1.0)
                self.events.emit({**base_event, "type": "ingestion.completed",
                                  "document_id": document_id, "deduplicated": True})
                return job

            advance("parsing", progress=0.15)
            heartbeat()
            parsed = parser_for(path, pdf_heartbeat=heartbeat).parse(
                path, workspace_id=workspace_id
            )

            advance("chunking", progress=0.35)
            plans = self.chunker.chunk(
                text=parsed.text,
                pages=[(p.page_number, p.text) for p in parsed.pages],
                document_id=document_id,
            )
            if not plans:
                raise ParseError("validation_error", "Document produced no chunks.")

            advance("embedding", progress=0.55)
            vectors = _validate_embeddings(
                self.embeddings.embed([plan.text for plan in plans]),
                expected_count=len(plans),
                dimensions=self.embeddings.dimensions,
            )

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
            self.knowledge.upsert_collection(Collection(
                workspace_id=workspace_id, collection_id=collection_id,
                tenant_id=tenant_id, title=collection_id,
                metadata=(
                    {"created_by": safe_document_metadata["created_by"]}
                    if "created_by" in safe_document_metadata else {}
                ),
            ))
            document_written = True
            # Mark before the call: an adapter is allowed to persist and then
            # raise, and compensation must cover that partial write too.
            self.knowledge.upsert_document(document)
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
            _scoped_call(
                self.knowledge.replace_document_chunks,
                document_id,
                chunks,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            from rick_knowledge import build_point_payload

            points = []
            for chunk, vector in zip(chunks, vectors):
                payload = build_point_payload(chunk=chunk, document=document)
                points.append({"point_id": self._point_id(chunk.chunk_id),
                               "vector": vector, "payload": payload})
            indexed = self.vectors.upsert_points(points)

            advance("verifying", progress=0.9)
            if _scoped_call(
                self.vectors.count_for_document,
                document_id,
                collection_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            ) < len(chunks):
                raise RuntimeError("verify failed: indexed points below chunk count")
            publish_context = publication_guard() if callable(publication_guard) else nullcontext()
            with publish_context:
                with self._lock:
                    self._checkpoint(job, cancel_check)
                    _scoped_call(
                        self.knowledge.set_document_status,
                        document_id,
                        "published",
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                    )
                    job.document_id = document_id
                    advance("published", progress=1.0)
            self.events.emit({**base_event, "type": "ingestion.completed",
                              "document_id": document_id, "chunks": len(chunks), "points": indexed})
            return job
        except _CancellationRequested:
            self._cleanup_failed_document(
                document_id, collection_id, document_written=document_written,
                tenant_id=tenant_id, workspace_id=workspace_id,
            )
            if job.status != "cancelled":
                job.cancel_requested = True
                job.transition("cancelled", message="Cancelled by operator.")
            self.events.emit({**base_event, "type": "ingestion.cancelled"})
            return job
        except ParseError as exc:
            self._cleanup_failed_document(
                document_id, collection_id, document_written=document_written,
                tenant_id=tenant_id, workspace_id=workspace_id,
            )
            job.transition("failed", error_code=exc.code, message=exc.args[0] if exc.args else "Ingestion failed.")
            self.events.emit({**base_event, "type": "ingestion.failed", "error_code": exc.code,
                              "retryable": is_retryable(exc.code)})
            return job
        except Exception:
            self._cleanup_failed_document(
                document_id, collection_id, document_written=document_written,
                tenant_id=tenant_id, workspace_id=workspace_id,
            )
            if job.status == "cancelled":
                self.events.emit({**base_event, "type": "ingestion.cancelled"})
                return job
            error_code = self._failure_code(job)
            job.transition("failed", error_code=error_code, message="Ingestion failed.")
            self.events.emit({**base_event, "type": "ingestion.failed", "error_code": error_code,
                              "retryable": is_retryable(error_code)})
            return job

    def reindex(self, document_id: str, path: Path, **kwargs: Any) -> IngestionJob:
        """Changed content → new version; stale vectors for replaced versions pruned."""
        with self._operation_lock:
            return self._reindex(document_id, path, **kwargs)

    def _reindex(self, document_id: str, path: Path, **kwargs: Any) -> IngestionJob:
        previous = _scoped_call(
            self.knowledge.get_document,
            document_id,
            tenant_id=kwargs.get("tenant_id"),
            workspace_id=kwargs.get("workspace_id"),
        )
        job = self.ingest(path, **kwargs)
        # A failed replacement must not remove the currently published
        # version. Only commit the old-version retirement after the new
        # attempt has crossed the publication gate.
        if (
            previous is not None
            and job.status == "published"
            and job.document_id
            and job.document_id != document_id
        ):
            old_points: list[dict] = []
            retirement_started = False
            try:
                collection_id = normalize_collection_id(kwargs.get("collection_id", "rag_phase0"))
                old_points = self._snapshot_points(self.vectors, document_id, collection_id)
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
            except Exception:
                self._rollback_replacement(
                    job,
                    new_document_id=job.document_id,
                    old_document_id=document_id,
                    collection_id=normalize_collection_id(kwargs.get("collection_id", "rag_phase0")),
                    old_points=old_points,
                    tenant_id=kwargs["tenant_id"],
                    workspace_id=kwargs["workspace_id"],
                    retirement_started=retirement_started,
                )
        return job

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        from rick_knowledge import point_id_for_chunk

        return point_id_for_chunk(chunk_id)
