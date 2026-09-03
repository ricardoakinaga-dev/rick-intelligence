"""Canonical knowledge identity — byte-identical derivation to rag-contract-v1.

document:{workspace}:{collection}:{sha256} UUIDv5 under the frozen namespace;
point:{chunk_id} UUIDv5; version sha256:{16}; legacy physical-name aliases.
No Python hash(). Stable across restarts and reindexes of unchanged content.
"""

from __future__ import annotations

import hashlib
import re
from uuid import NAMESPACE_URL, uuid5

RAG_SCHEMA_VERSION = "rag-contract-v1"
CANONICAL_COLLECTION_ID = "rag_phase0"

COLLECTION_ALIASES: dict[str, str] = {
    CANONICAL_COLLECTION_ID: CANONICAL_COLLECTION_ID,
    "cvg_master_rag": CANONICAL_COLLECTION_ID,
    "rickvet_documents": CANONICAL_COLLECTION_ID,
}

_COLLECTION_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_IDENTITY_NAMESPACE = uuid5(NAMESPACE_URL, "https://rick-intelligence.local/rag-contract-v1")


def normalize_collection_id(collection_id: str | None) -> str:
    candidate = str(collection_id or CANONICAL_COLLECTION_ID).strip()
    if not _COLLECTION_NAME.fullmatch(candidate):
        raise ValueError("collection_id must use 1-64 letters, numbers, '_' or '-'")
    return COLLECTION_ALIASES.get(candidate, candidate)


def content_checksum(content: bytes | str) -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    return hashlib.sha256(raw).hexdigest()


def document_id_for_content(*, workspace_id: str, collection_id: str, checksum: str) -> str:
    resolved = normalize_collection_id(collection_id)
    return str(uuid5(_IDENTITY_NAMESPACE, f"document:{workspace_id}:{resolved}:{checksum}"))


def point_id_for_chunk(chunk_id: str) -> str:
    return str(uuid5(_IDENTITY_NAMESPACE, f"point:{chunk_id}"))


def document_version(checksum: str) -> str:
    return f"sha256:{checksum[:16]}"


def chunk_id_for_document(document_id: str, chunk_index: int) -> str:
    return f"chunk_{document_id}_{chunk_index:04d}"
