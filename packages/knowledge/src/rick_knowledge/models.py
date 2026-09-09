"""Canonical knowledge domain models. No Qdrant/OpenAI/FastAPI/Redis/filesystem here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

DOCUMENT_STATUSES = ("draft", "processing", "published", "unpublished", "deleted", "partial", "failed")


def utc_timestamp() -> str:
    """Return the stable wire representation used for lineage timestamps."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        candidate = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return candidate.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError("lineage timestamps must be non-empty strings or datetimes")


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
    # These fields are appended after the historical fields so positional
    # callers remain source-compatible while new writes carry explicit
    # version/object/publication lineage.
    ingestion_version: str = ""
    object_ref: str = ""
    created_at: str | None = field(default_factory=utc_timestamp)
    published_at: str | None = None


def materialize_lineage(document: Document, *, published: bool = False) -> None:
    """Fill only compatibility-safe lineage defaults before durable writes.

    Existing callers did not provide ingestion or object lineage explicitly.
    Reusing the content version and legacy object key keeps those callers
    readable while allowing new callers to provide distinct values.
    """

    document.created_at = _timestamp_text(document.created_at) or utc_timestamp()
    document.published_at = _timestamp_text(document.published_at)
    if not isinstance(document.ingestion_version, str) or not document.ingestion_version.strip():
        document.ingestion_version = document.document_version
    else:
        document.ingestion_version = document.ingestion_version.strip()
    if not isinstance(document.object_ref, str) or not document.object_ref.strip():
        metadata = document.metadata if isinstance(document.metadata, dict) else {}
        candidate = metadata.get("object_key")
        if not isinstance(candidate, str) or not candidate.strip():
            candidate = document.filename or document.display_filename or document.document_id
        document.object_ref = str(candidate).strip()
    else:
        document.object_ref = document.object_ref.strip()
    if published and not document.published_at:
        document.published_at = utc_timestamp()


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
