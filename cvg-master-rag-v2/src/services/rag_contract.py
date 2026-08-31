"""Versioned cross-service RAG contract and deterministic identity helpers."""

from __future__ import annotations

import hashlib
import re
from uuid import NAMESPACE_URL, UUID, uuid5


RAG_SCHEMA_VERSION = "rag-contract-v1"
CANONICAL_COLLECTION_ID = "rag_phase0"
CANONICAL_EMBEDDING_MODEL = "text-embedding-3-small"
CANONICAL_EMBEDDING_DIM = 1536
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

# These names were used by the separate components before the contract was
# frozen. They identify one logical collection; they are not permission scopes
# and must never trigger an implicit fan-out search.
COLLECTION_ALIASES: dict[str, str] = {
    CANONICAL_COLLECTION_ID: CANONICAL_COLLECTION_ID,
    "cvg_master_rag": CANONICAL_COLLECTION_ID,
    "rickvet_documents": CANONICAL_COLLECTION_ID,
}

_COLLECTION_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_IDENTITY_NAMESPACE = uuid5(NAMESPACE_URL, "https://rick-intelligence.local/rag-contract-v1")


def normalize_collection_id(collection_id: str | None) -> str:
    """Resolve a legacy physical name to the single canonical collection ID."""
    candidate = str(collection_id or CANONICAL_COLLECTION_ID).strip()
    if not _COLLECTION_NAME.fullmatch(candidate):
        raise ValueError("collection_id must use 1-64 letters, numbers, '_' or '-'")
    return COLLECTION_ALIASES.get(candidate, candidate)


def is_known_collection_alias(collection_id: str | None) -> bool:
    try:
        return str(collection_id or "").strip() in COLLECTION_ALIASES
    except Exception:
        return False


def content_checksum(content: bytes | str) -> str:
    """Return a stable SHA-256 checksum for document identity and audit."""
    raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    return hashlib.sha256(raw).hexdigest()


def document_id_for_content(
    *,
    workspace_id: str,
    collection_id: str,
    checksum: str,
) -> str:
    """Derive a stable document UUID from its ownership and content."""
    resolved_collection = normalize_collection_id(collection_id)
    return str(uuid5(_IDENTITY_NAMESPACE, f"document:{workspace_id}:{resolved_collection}:{checksum}"))


def point_id_for_chunk(chunk_id: str) -> str:
    """Derive a Qdrant UUID stable across Python processes and restarts."""
    return str(uuid5(_IDENTITY_NAMESPACE, f"point:{chunk_id}"))


def document_version(checksum: str) -> str:
    """Compact, human-auditable version token for a content checksum."""
    return f"sha256:{checksum[:16]}"


def canonical_payload_required_fields() -> tuple[str, ...]:
    return (
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


def validate_canonical_payload(payload: dict) -> list[str]:
    """Return missing required fields instead of silently accepting drift."""
    return [field for field in canonical_payload_required_fields() if field not in payload]
