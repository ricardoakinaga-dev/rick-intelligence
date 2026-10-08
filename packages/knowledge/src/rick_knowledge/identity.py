"""Canonical identity with an unambiguous v2 tuple and explicit v1 lookups.

Safe default-tenant scopes retain the frozen v1 bytes. Persisted IDs are never
rewritten. Point derivation, content versions and collection aliases are stable.
"""

from __future__ import annotations

import hashlib
import json
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


def legacy_document_id_for_content(*, workspace_id: str, collection_id: str, checksum: str,
                                  tenant_id: str) -> str:
    """Read-only v1 lookup. Never use this ambiguous encoding for new rows."""
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


def document_id_for_content(*, workspace_id: str, collection_id: str, checksum: str,
                            tenant_id: str) -> str:
    """Versioned, unambiguous tuple encoding for new document identities.

Persisted v1 IDs remain authoritative: ingestion explicitly resolves the old
ID in the requested scope before creating a v2 row. No stored ID is rewritten.
"""
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ValueError("workspace_id is required")
    if not isinstance(checksum, str) or not checksum:
        raise ValueError("checksum is required")
    tenant = normalize_tenant_id(tenant_id)
    # The frozen default-tenant names without separators are unambiguous and
    # retain byte parity for deployed Phase 0/1 callers. Separator-bearing
    # workspaces and every non-default tenant use the disjoint v2 tuple domain.
    if tenant == "default" and ":" not in workspace_id:
        return legacy_document_id_for_content(workspace_id=workspace_id,
            collection_id=collection_id, checksum=checksum, tenant_id=tenant)
    name = "document:v2:" + json.dumps(
        [tenant, workspace_id, normalize_collection_id(collection_id), checksum],
        ensure_ascii=True, separators=(",", ":"),
    )
    return str(uuid5(_IDENTITY_NAMESPACE, name))


def point_id_for_chunk(chunk_id: str) -> str:
    return str(uuid5(_IDENTITY_NAMESPACE, f"point:{chunk_id}"))


def document_version(checksum: str) -> str:
    return f"sha256:{checksum[:16]}"


def chunk_id_for_document(document_id: str, chunk_index: int) -> str:
    return f"chunk_{document_id}_{chunk_index:04d}"
