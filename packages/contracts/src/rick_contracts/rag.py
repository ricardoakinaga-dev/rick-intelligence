"""Canonical RAG DTOs (rag-contract-v1 surface). No second citation schema:
citations reuse security.EvidenceItem; retrieval evidence extends it immutably."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from rick_contracts.base import StrictContractModel

RAG_SCHEMA_VERSION = "rag-contract-v1"
CANONICAL_COLLECTION_ID = "rag_phase0"
CANONICAL_EMBEDDING_MODEL = "text-embedding-3-small"
CANONICAL_EMBEDDING_DIM = 1536
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

DocumentStatus = Literal["draft", "processing", "published", "unpublished", "deleted", "partial", "failed"]
JobStatus = Literal["queued", "validating", "parsing", "chunking", "embedding", "indexing",
                    "verifying", "published", "failed", "cancelled"]


class DocumentDto(StrictContractModel):
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


class ChunkDto(StrictContractModel):
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


class EvidenceDto(StrictContractModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    chunk_id: str = Field(min_length=1, max_length=128)
    # Internal retrieval provenance. Public API projections deliberately omit
    # this field, but final consumers must retain it until scope validation.
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    collection_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=1_000_000)
    source: str = Field(default="", max_length=512)
    title: str = Field(default="", max_length=512)
    page_start: int | None = Field(default=None, ge=0)
    page_end: int | None = Field(default=None, ge=0)
    section: str | None = None
    checksum: str = Field(default="", max_length=256)
    document_version: str | None = Field(default=None, min_length=1, max_length=128)
    score: float = 0.0
    rank: int = Field(default=0, ge=0, le=1_000_000)
    dense_score: float = 0.0
    sparse_score: float = 0.0
    # Bounded ranking quality signal. This is intentionally separate from a
    # calibrated probability; confidence_score remains for legacy wire
    # compatibility until its consumers migrate.
    retrieval_quality_score: float = 0.0
    confidence_score: float = 0.0

    @field_validator(
        "score", "dense_score", "sparse_score", "retrieval_quality_score", "confidence_score",
        mode="before",
    )
    @classmethod
    def finite_score(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("score must be finite")
        return float(value)

    @field_validator("page_start", "page_end", "rank", mode="before")
    @classmethod
    def integer_bounds(cls, value: object) -> object:
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError("page and rank values must be integers")
        return value


class RetrievalResultDto(StrictContractModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    evidence: list[EvidenceDto] = Field(default_factory=list)
    candidate_count: int = Field(default=0, ge=0, le=1_000_000)
    selected_count: int = Field(default=0, ge=0, le=1_000_000)
    backend: str = Field(default="", max_length=128)
    fallback_used: bool = False
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=32)


class IngestionJobDto(StrictContractModel):
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
