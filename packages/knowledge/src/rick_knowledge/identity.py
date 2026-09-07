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
_TENANT_NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_IDENTITY_NAMESPACE = uuid5(NAMESPACE_URL, "https://rick-intelligence.local/rag-contract-v1")


def normalize_collection_id(collection_id: str | None) -> str:
    candidate = str(collection_id or CANONICAL_COLLECTION_ID).strip()
    if not _COLLECTION_NAME.fullmatch(candidate):
        raise ValueError("collection_id must use 1-64 letters, numbers, '_' or '-'")
    return COLLECTION_ALIASES.get(candidate, candidate)


def normalize_tenant_id(tenant_id: str | None) -> str:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id is required")
    candidate = tenant_id.strip()
    if not _TENANT_NAME.fullmatch(candidate):
        raise ValueError("tenant_id must use 1-128 letters, numbers, '_' or '-'")
    return candidate


def content_checksum(content: bytes | str) -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    return hashlib.sha256(raw).hexdigest()


def document_id_for_content(*, workspace_id: str, collection_id: str, checksum: str,
                            tenant_id: str) -> str:
    tenant = normalize_tenant_id(tenant_id)
    resolved = normalize_collection_id(collection_id)
    # The default tenant keeps the frozen Phase 0/1 contract byte-identical to
    # the preserved CVG implementation.  Explicit non-default tenants get a
    # namespace component so two tenants cannot collide when they share a
    # workspace identifier during the migration period.
    name = f"document:{workspace_id}:{resolved}:{checksum}"
    if tenant != "default":
        name = f"document:tenant:{tenant}:{workspace_id}:{resolved}:{checksum}"
    return str(uuid5(_IDENTITY_NAMESPACE, name))


def point_id_for_chunk(chunk_id: str) -> str:
    return str(uuid5(_IDENTITY_NAMESPACE, f"point:{chunk_id}"))


def document_version(checksum: str) -> str:
    return f"sha256:{checksum[:16]}"


def chunk_id_for_document(document_id: str, chunk_index: int) -> str:
    return f"chunk_{document_id}_{chunk_index:04d}"
