"""Canonical platform contracts (dependency-light, no legacy imports)."""

from rick_contracts.chat import ChatRequest, ChatResponse, ChatStreamEvent
from rick_contracts.errors import ERROR_CODES
from rick_contracts.pagination import Page
from rick_contracts.security import (
    APIError,
    AUTHORIZATION_SNAPSHOT_VERSION,
    AUTHORIZATION_CONTRACT_VERSION,
    CollectionGrant,
    EvidenceItem,
    IDENTITY_CONTRACT_VERSION,
    Permission,
    PermissionOverrides,
    RETRIEVAL_CONTEXT_VERSION,
    RetrievalContext,
    Role,
    SESSION_CONTRACT_VERSION,
    SessionSnapshot,
    UserIdentity,
)

__all__ = [
    "ChatRequest", "ChatResponse", "ChatStreamEvent", "ERROR_CODES", "Page",
    "APIError", "AUTHORIZATION_SNAPSHOT_VERSION", "AUTHORIZATION_CONTRACT_VERSION",
    "CollectionGrant", "EvidenceItem", "IDENTITY_CONTRACT_VERSION",
    "Permission", "PermissionOverrides", "RETRIEVAL_CONTEXT_VERSION",
    "RetrievalContext", "Role", "SESSION_CONTRACT_VERSION",
    "SessionSnapshot", "UserIdentity",
]
