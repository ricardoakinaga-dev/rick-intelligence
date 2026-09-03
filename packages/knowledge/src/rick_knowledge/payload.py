"""Canonical Qdrant point payload builder + drift validator (rag-contract-v1).

Every indexed point carries the full required field set; `validate_payload`
returns missing fields instead of silently accepting drift.
"""

from __future__ import annotations

REQUIRED_PAYLOAD_FIELDS = (
    "schema_version",
    "workspace_id",
    "collection_id",
    "document_id",
    "document_version",
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
    "parser_version",
    "chunker_version",
    "embedding_model",
    "embedding_version",
    "metadata",
)


def build_point_payload(*, chunk, document, schema_version: str = "rag-contract-v1") -> dict:
    return {
        "schema_version": schema_version,
        "workspace_id": document.workspace_id,
        "collection_id": document.collection_id,
        "document_id": document.document_id,
        "document_version": document.document_version,
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
        "parser_version": chunk.parser_version or document.parser_version,
        "chunker_version": chunk.chunker_version or document.chunker_version,
        "embedding_model": document.embedding_model,
        "embedding_version": chunk.embedding_version or document.embedding_version,
        "metadata": dict(chunk.metadata or {}),
        # Compatibility shims (never replace canonical fields):
        "document_filename": document.display_filename or document.filename,
        "qdrant_collection": document.collection_id,
    }


def validate_payload(payload: dict) -> list[str]:
    return [field for field in REQUIRED_PAYLOAD_FIELDS if field not in payload]
