"""Canonical shared security contracts (serialized surface).

Contract versions: identity-contract-v1 / authorization-contract-v1 /
session-contract-v1 / retrieval-context-v1. No secrets ever serialize here.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from rick_contracts.base import StrictContractModel

IDENTITY_CONTRACT_VERSION = "identity-contract-v1"
AUTHORIZATION_CONTRACT_VERSION = "authorization-contract-v1"
SESSION_CONTRACT_VERSION = "session-contract-v1"
RETRIEVAL_CONTEXT_VERSION = "retrieval-context-v1"

AuthorizationState = Literal["AUTHORITATIVE", "LEGACY_UNMIGRATED", "MIGRATED"]
AUTHORIZATION_SNAPSHOT_VERSION = 1


class Role(StrictContractModel):
    canonical: str
    legacy_label: str | None = None


class Permission(StrictContractModel):
    identifier: str


class PermissionOverrides(StrictContractModel):
    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class UserIdentity(StrictContractModel):
    user_id: str
    email: str | None = None
    role: str
    canonical_role: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    status: str = "active"
    overrides: PermissionOverrides = Field(default_factory=PermissionOverrides)
    authorized_collection_ids: list[str] = Field(default_factory=list)
    password_version: int = 1
    role_version: int = 1


class SessionSnapshot(StrictContractModel):
    """Authoritative session view. `permissions=[]` means NO permissions (modern)."""

    contract_version: str = SESSION_CONTRACT_VERSION
    authorization_snapshot_version: int = AUTHORIZATION_SNAPSHOT_VERSION
    authorization_state: AuthorizationState = "AUTHORITATIVE"
    authenticated: bool = False
    session_state: str = "anonymous"
    user_id: str | None = None
    email: str | None = None
    role: str | None = None
    canonical_role: str | None = None
    permissions: list[str] = Field(default_factory=list)
    # Anonymous snapshots carry None; authenticated boundaries must bind an
    # explicit tenant before authorization or data access.
    tenant_id: str | None = None
    workspace_id: str | None = None
    session_id: str | None = None
    allowed_collection_ids: list[str] = Field(default_factory=list)


class CollectionGrant(StrictContractModel):
    tenant_id: str
    workspace_id: str
    allowed_collection_ids: list[str] = Field(default_factory=list)


class RetrievalContext(StrictContractModel):
    contract_version: str = RETRIEVAL_CONTEXT_VERSION
    user_id: str | None = None
    workspace_id: str
    tenant_id: str
    allowed_collection_ids: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class EvidenceItem(StrictContractModel):
    document_id: str
    chunk_id: str | None = None
    title: str | None = None
    collection_id: str | None = None
    checksum: str | None = None


class APIError(StrictContractModel):
    code: str
    message: str
    request_id: str
    details: Any | None = None
