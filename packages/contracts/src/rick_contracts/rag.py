"""Canonical RAG DTOs (rag-contract-v1 surface). No second citation schema:
citations reuse security.EvidenceItem; retrieval evidence extends it immutably."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RAG_SCHEMA_VERSION = "rag-contract-v1"
CANONICAL_COLLECTION_ID = "rag_phase0"
CANONICAL_EMBEDDING_MODEL = "text-embedding-3-small"
CANONICAL_EMBEDDING_DIM = 1536
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

DocumentStatus = Literal["draft", "processing", "published", "unpublished", "deleted", "partial", "failed"]
JobStatus = Literal["queued", "validating", "parsing", "chunking", "embedding", "indexing",
                    "verifying", "published", "failed", "cancelled"]


class DocumentDto(BaseModel):
    document_id: str
    workspace_id: str
    collection_id: str = CANONICAL_COLLECTION_ID
    document_version: str = ""
    content_checksum: str = ""
    filename: str = ""
    display_filename: str = ""
    title: str = ""
    source_type: str = ""
    mime_type: str = ""
    language: str | None = None
    status: DocumentStatus = "draft"
    parser_version: str = ""
    chunker_version: str = ""
    embedding_model: str = CANONICAL_EMBEDDING_MODEL
    embedding_version: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkDto(BaseModel):
    chunk_id: str
    document_id: str
    parent_chunk_id: str | None = None
    chunk_index: int = 0
    text: str = ""
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    heading: str | None = None
    token_count: int = 0
    checksum: str = ""
    parser_version: str = ""
    chunker_version: str = ""
    embedding_version: str = ""
    index_version: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceDto(BaseModel):
    evidence_id: str
    document_id: str
    chunk_id: str
    workspace_id: str
    collection_id: str
    text: str
    source: str = ""
    title: str = ""
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    checksum: str = ""
    score: float = 0.0
    rank: int = 0
    dense_score: float = 0.0
    sparse_score: float = 0.0


class RetrievalResultDto(BaseModel):
    query: str
    evidence: list[EvidenceDto] = Field(default_factory=list)
    candidate_count: int = 0
    selected_count: int = 0
    backend: str = ""
    fallback_used: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionJobDto(BaseModel):
    job_id: str
    document_id: str | None = None
    status: JobStatus = "queued"
    stage: str = "queued"
    progress: float = 0.0
    attempt: int = 1
    error_code: str | None = None
    safe_error_message: str | None = None
    workspace_id: str = "default"
    collection_id: str = CANONICAL_COLLECTION_ID
    metadata: dict[str, Any] = Field(default_factory=dict)
