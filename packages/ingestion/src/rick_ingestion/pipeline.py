"""Canonical ingestion pipeline: acquire→validate→parse→chunk→embed→index→verify→publish.

Idempotency: stable document/chunk/point IDs — re-ingesting unchanged content
upserts the same identities with no duplicate drift. Changed content produces a
new document version; stale vectors for replaced versions are pruned. Partial
failures never publish: processing → partial/failed → published only after verify.

No HTTP/FastAPI/Redis/OpenAI/qdrant-client imports. RequestContext/correlation
flow through events; document text never enters logs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

from rick_ingestion.chunking import CHUNKER_VERSION, RecursiveChunkingStrategy
from rick_ingestion.jobs import IngestionJob, is_retryable
from rick_ingestion.parsers import PARSER_VERSION, ParseError, parser_for, sanitize_display_filename, validate_file
from rick_knowledge import (
    Collection,
    Document,
    InMemoryKnowledgeStore,
    chunk_id_for_document,
    content_checksum,
    document_id_for_content,
    document_version,
    normalize_collection_id,
)


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    def upsert_points(self, points: list[dict]) -> int: ...
    def delete_document(self, document_id: str, collection_id: str) -> int: ...
    def count_for_document(self, document_id: str, collection_id: str) -> int: ...


class IngestionEvents(Protocol):
    def emit(self, event: dict) -> None: ...


class NullEvents:
    def emit(self, event: dict) -> None:
        pass


def _embedding_is_valid(embedding: object, dimensions: int) -> bool:
    return (
        isinstance(embedding, (list, tuple))
        and len(embedding) == dimensions
        and all(isinstance(v, (int, float)) for v in embedding)
    )


class IngestionService:
    """Deliberate interface: ingest / reindex / cancel / get_status."""

    def __init__(self, *, knowledge, vectors: VectorStore, embeddings: EmbeddingProvider,
                 events: IngestionEvents | None = None,
                 chunker=None, embedding_version: str = "emb-v1") -> None:
        self.knowledge = knowledge
        self.vectors = vectors
        self.embeddings = embeddings
        self.events = events or NullEvents()
        self.chunker = chunker or RecursiveChunkingStrategy()
        self.embedding_version = embedding_version
        self._jobs: dict[str, IngestionJob] = {}

    # -- jobs ----------------------------------------------------------
    def get_status(self, job_id: str) -> IngestionJob | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status in ("published", "failed", "cancelled"):
            return False
        job.transition("cancelled", message="Cancelled by operator.")
        self.events.emit({"type": "ingestion.cancelled", "job_id": job_id})
        return True

    # -- ingest --------------------------------------------------------
    def ingest(self, path: Path, *, workspace_id: str, collection_id: str,
               display_filename: str | None = None, request_id: str | None = None,
               correlation_id: str | None = None) -> IngestionJob:
        collection_id = normalize_collection_id(collection_id)
        job = IngestionJob(workspace_id=workspace_id, collection_id=collection_id)
        self._jobs[job.job_id] = job
        base_event = {"job_id": job.job_id, "workspace_id": workspace_id,
                      "collection_id": collection_id, "request_id": request_id,
                      "correlation_id": correlation_id}
        try:
            self.events.emit({**base_event, "type": "ingestion.start", "stage": "validating"})
            job.transition("validating", progress=0.05)
            validate_file(path)
            raw_bytes = path.read_bytes()
            checksum = content_checksum(raw_bytes)
            document_id = document_id_for_content(
                workspace_id=workspace_id, collection_id=collection_id, checksum=checksum)

            existing = self.knowledge.get_document(document_id)
            if existing is not None and existing.status == "published":
                # Idempotent re-ingest: same identities, no duplicate drift.
                job.document_id = document_id
                job.transition("parsing", progress=0.5)
                job.transition("chunking", progress=0.7)
                job.transition("embedding", progress=0.8)
                job.transition("indexing", progress=0.9)
                job.transition("verifying", progress=0.95)
                job.transition("published", progress=1.0)
                self.events.emit({**base_event, "type": "ingestion.completed",
                                  "document_id": document_id, "deduplicated": True})
                return job

            job.transition("parsing", progress=0.15)
            job.heartbeat()
            parsed = parser_for(path).parse(path, workspace_id=workspace_id)

            job.transition("chunking", progress=0.35)
            plans = self.chunker.chunk(
                text=parsed.text,
                pages=[(p.page_number, p.text) for p in parsed.pages],
                document_id=document_id,
            )
            if not plans:
                raise ParseError("validation_error", "Document produced no chunks.")

            job.transition("embedding", progress=0.55)
            vectors = self.embeddings.embed([plan.text for plan in plans])
            for vector in vectors:
                if not _embedding_is_valid(vector, self.embeddings.dimensions):
                    raise ValueError(
                        f"Embedding dimension mismatch: expected {self.embeddings.dimensions}. "
                        "Refusing to write incompatible vectors; reindex required on model change."
                    )

            job.transition("indexing", progress=0.75)
            version = document_version(checksum)
            document = Document(
                document_id=document_id, workspace_id=workspace_id, collection_id=collection_id,
                document_version=version, content_checksum=checksum,
                filename=sanitize_display_filename(display_filename or path.name),
                display_filename=sanitize_display_filename(display_filename or path.name),
                title=sanitize_display_filename(display_filename or path.name),
                source_type=path.suffix.lower().lstrip(".") or "unknown",
                status="processing", parser_version=PARSER_VERSION,
                chunker_version=self.chunker.__class__.__name__,
                embedding_model=self.embeddings.model, embedding_version=self.embedding_version,
            )
            self.knowledge.upsert_collection(Collection(
                workspace_id=workspace_id, collection_id=collection_id, title=collection_id))
            self.knowledge.upsert_document(document)
            from rick_knowledge import Chunk as KnowledgeChunk

            chunks = [
                KnowledgeChunk(
                    chunk_id=chunk_id_for_document(document_id, plan.chunk_index),
                    document_id=document_id, chunk_index=plan.chunk_index, text=plan.text,
                    page_start=plan.page_start, page_end=plan.page_start,
                    checksum=plan.checksum, parser_version=PARSER_VERSION,
                    chunker_version=self.chunker.__class__.__name__,
                    embedding_version=self.embedding_version,
                )
                for plan in plans
            ]
            self.knowledge.replace_document_chunks(document_id, chunks)
            from rick_knowledge import build_point_payload

            points = []
            for chunk, vector in zip(chunks, vectors):
                payload = build_point_payload(chunk=chunk, document=document)
                points.append({"point_id": self._point_id(chunk.chunk_id),
                               "vector": list(vector), "payload": payload})
            indexed = self.vectors.upsert_points(points)

            job.transition("verifying", progress=0.9)
            if self.vectors.count_for_document(document_id, collection_id) < len(chunks):
                raise RuntimeError("verify failed: indexed points below chunk count")
            self.knowledge.set_document_status(document_id, "published")
            job.document_id = document_id
            job.transition("published", progress=1.0)
            self.events.emit({**base_event, "type": "ingestion.completed",
                              "document_id": document_id, "chunks": len(chunks), "points": indexed})
            return job
        except ParseError as exc:
            job.transition("failed", error_code=exc.code, message=exc.args[0] if exc.args else "Ingestion failed.")
            self.events.emit({**base_event, "type": "ingestion.failed", "error_code": exc.code,
                              "retryable": is_retryable(exc.code)})
            return job
        except Exception:
            job.transition("failed", error_code="ingestion_failed", message="Ingestion failed.")
            self.events.emit({**base_event, "type": "ingestion.failed", "error_code": "ingestion_failed",
                              "retryable": False})
            return job

    def reindex(self, document_id: str, path: Path, **kwargs: Any) -> IngestionJob:
        """Changed content → new version; stale vectors for replaced versions pruned."""
        previous = self.knowledge.get_document(document_id)
        job = self.ingest(path, **kwargs)
        if previous is not None and job.document_id and job.document_id != document_id:
            self.vectors.delete_document(document_id, kwargs.get("collection_id", "rag_phase0"))
            try:
                self.knowledge.set_document_status(document_id, "unpublished")
            except (KeyError, ValueError):
                pass
        return job

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        from rick_knowledge import point_id_for_chunk

        return point_id_for_chunk(chunk_id)
