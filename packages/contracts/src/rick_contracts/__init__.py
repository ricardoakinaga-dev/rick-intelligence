"""Canonical platform contracts (dependency-light, no legacy imports)."""

from rick_contracts.chat import ChatRequest, ChatResponse, ChatStreamEvent
from rick_contracts.errors import ERROR_CODES
from rick_contracts.pagination import Page
from rick_contracts.rag import (
    CANONICAL_COLLECTION_ID,
    CANONICAL_EMBEDDING_DIM,
    CANONICAL_EMBEDDING_MODEL,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    ChunkDto,
    DocumentDto,
    EvidenceDto,
    IngestionJobDto,
    RAG_SCHEMA_VERSION,
    RetrievalResultDto,
)
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
    "RAG_SCHEMA_VERSION", "CANONICAL_COLLECTION_ID", "CANONICAL_EMBEDDING_MODEL",
    "CANONICAL_EMBEDDING_DIM", "DENSE_VECTOR_NAME", "SPARSE_VECTOR_NAME",
    "DocumentDto", "ChunkDto", "EvidenceDto", "RetrievalResultDto", "IngestionJobDto",
]
