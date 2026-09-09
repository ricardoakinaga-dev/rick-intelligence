"""Canonical Qdrant point payload builder + drift validator (rag-contract-v1).

Every indexed point carries the full required field set; `validate_payload`
returns missing fields instead of silently accepting drift.
"""

from __future__ import annotations

from collections.abc import Mapping

from rick_knowledge.identity import normalize_tenant_id
from rick_knowledge.models import materialize_lineage

LINEAGE_PAYLOAD_FIELDS = (
    "document_id",
    "document_version",
    "ingestion_version",
    "parser_version",
    "chunker_version",
    "embedding_model",
    "embedding_version",
    "index_version",
    "checksum",
    "object_ref",
    "created_at",
    "published_at",
)

REQUIRED_PAYLOAD_FIELDS = (
    "schema_version",
    "tenant_id",
    "workspace_id",
    "collection_id",
    "document_id",
    "document_version",
    "ingestion_version",
    "chunk_id",
    "parent_chunk_id",
    "chunk_index",
    "text",
    "source",
    "title",
    "page_start",
    "page_end",
    "section",
    "checksum",
    "object_ref",
    "created_at",
    "published_at",
    "parser_version",
    "chunker_version",
    "embedding_model",
    "embedding_version",
    "index_version",
    "metadata",
)


def build_point_payload(*, chunk, document, schema_version: str = "rag-contract-v1") -> dict:
    document_tenant = normalize_tenant_id(getattr(document, "tenant_id", None))
    chunk_tenant = normalize_tenant_id(getattr(chunk, "tenant_id", None))
    if document_tenant != chunk_tenant:
        raise ValueError("document and chunk tenant_id must match")
    materialize_lineage(document, published=getattr(document, "status", None) == "published")
    return {
        "schema_version": schema_version,
        "tenant_id": document_tenant,
        "workspace_id": document.workspace_id,
        "collection_id": document.collection_id,
        "document_id": document.document_id,
        "document_version": document.document_version,
        "ingestion_version": document.ingestion_version,
        "chunk_id": chunk.chunk_id,
        "parent_chunk_id": chunk.parent_chunk_id,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "source": document.display_filename or document.filename,
        "title": document.title or document.display_filename or document.filename,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "section": chunk.section,
        "checksum": chunk.checksum or document.content_checksum,
        "object_ref": document.object_ref,
        "created_at": document.created_at,
        "published_at": document.published_at,
        "parser_version": chunk.parser_version or document.parser_version,
        "chunker_version": chunk.chunker_version or document.chunker_version,
        "embedding_model": document.embedding_model,
        "embedding_version": chunk.embedding_version or document.embedding_version,
        "index_version": chunk.index_version,
        "metadata": dict(chunk.metadata or {}),
        # Compatibility shims (never replace canonical fields):
        "document_filename": document.display_filename or document.filename,
        "qdrant_collection": document.collection_id,
        "object_key": document.object_ref,
    }


def validate_payload(payload: dict) -> list[str]:
    if not isinstance(payload, Mapping):
        return list(REQUIRED_PAYLOAD_FIELDS)
    missing = [field for field in REQUIRED_PAYLOAD_FIELDS if field not in payload]
    if missing:
        return missing

    invalid: list[str] = []
    for field in (
        "tenant_id",
        "workspace_id",
        "collection_id",
        "document_id",
        "document_version",
        "ingestion_version",
        "chunk_id",
        "object_ref",
        "created_at",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            invalid.append(field)
    published_at = payload.get("published_at")
    if published_at is not None and (not isinstance(published_at, str) or not published_at.strip()):
        invalid.append("published_at")
    return invalid
