"""Canonical knowledge domain models. No Qdrant/OpenAI/FastAPI/Redis/filesystem here."""

from __future__ import annotations

from dataclasses import dataclass, field

DOCUMENT_STATUSES = ("draft", "processing", "published", "unpublished", "deleted", "partial", "failed")


@dataclass
class Document:
    document_id: str
    workspace_id: str
    collection_id: str
    tenant_id: str
    document_version: str = ""
    content_checksum: str = ""
    filename: str = ""
    display_filename: str = ""
    title: str = ""
    source_type: str = ""
    mime_type: str = ""
    language: str | None = None
    status: str = "draft"
    parser_version: str = ""
    chunker_version: str = ""
    embedding_model: str = ""
    embedding_version: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    tenant_id: str
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
    metadata: dict = field(default_factory=dict)


@dataclass
class Collection:
    workspace_id: str
    collection_id: str
    tenant_id: str
    title: str = ""
    description: str = ""
    status: str = "active"
    version: int = 1
    metadata: dict = field(default_factory=dict)
