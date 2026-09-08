"""Canonical platform contracts (dependency-light, no legacy imports)."""

from rick_contracts.chat import (
    ChatRequest,
    ChatResponse,
    ChatStreamEvent,
    ConversationDetailResponse,
    ConversationMessage,
    ConversationListResponse,
    ConversationSummary,
    HistoryListResponse,
    SourceItem,
    SourceListResponse,
)
from rick_contracts.cases import (
    CASE_CONTRACT_VERSION,
    CASE_SCOPE_STATUS,
    AgentModelCatalogResponse,
    AuthorizedAgentModel,
    CaseCreateRequest,
    CaseDetailResponse,
    CaseEvidence,
    CaseEvidenceInput,
    CaseFeedback,
    CaseFeedbackRequest,
    CaseHypothesis,
    CaseHypothesisInput,
    CaseListResponse,
    CaseRecord,
    CaseReview,
    CaseReviewRequest,
    CaseUpdateRequest,
)
from rick_contracts.errors import ERROR_CODES
from rick_contracts.locking import LOCKING_CONTRACT_VERSION, LeaseErrorDto, LeaseRequest, LeaseResult
from rick_contracts.pagination import Page
from rick_contracts.professor import (
    PROFESSOR_CONTRACT_VERSION,
    EvidenceStatus,
    ProfessorRequest,
    ProfessorResponse,
)
from rick_contracts.providers import (
    PROVIDER_CONTRACT_VERSION,
    ChatCompletionResult,
    ChatCompletionChunk,
    EmbeddingResult,
    ProviderUsage,
    ProviderErrorCode,
    ProviderErrorDto,
    ProviderMessage,
)
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
    "ChatRequest", "ChatResponse", "ChatStreamEvent", "ConversationSummary",
    "ConversationMessage", "ConversationDetailResponse", "ConversationListResponse",
    "HistoryListResponse", "SourceItem", "SourceListResponse", "ERROR_CODES", "Page",
    "CASE_CONTRACT_VERSION", "CASE_SCOPE_STATUS", "CaseCreateRequest",
    "CaseUpdateRequest", "CaseHypothesisInput", "CaseHypothesis", "CaseEvidenceInput",
    "CaseEvidence", "AuthorizedAgentModel", "AgentModelCatalogResponse",
    "CaseReviewRequest", "CaseFeedbackRequest", "CaseRecord",
    "CaseReview", "CaseFeedback", "CaseListResponse", "CaseDetailResponse",
    "PROVIDER_CONTRACT_VERSION", "ProviderMessage", "ProviderErrorCode", "ProviderErrorDto",
    "EmbeddingResult", "ProviderUsage", "ChatCompletionResult", "ChatCompletionChunk", "LOCKING_CONTRACT_VERSION",
    "LeaseRequest", "LeaseResult", "LeaseErrorDto", "EvidenceStatus",
    "PROFESSOR_CONTRACT_VERSION", "ProfessorRequest", "ProfessorResponse",
    "APIError", "AUTHORIZATION_SNAPSHOT_VERSION", "AUTHORIZATION_CONTRACT_VERSION",
    "CollectionGrant", "EvidenceItem", "IDENTITY_CONTRACT_VERSION",
    "Permission", "PermissionOverrides", "RETRIEVAL_CONTEXT_VERSION",
    "RetrievalContext", "Role", "SESSION_CONTRACT_VERSION",
    "SessionSnapshot", "UserIdentity",
    "RAG_SCHEMA_VERSION", "CANONICAL_COLLECTION_ID", "CANONICAL_EMBEDDING_MODEL",
    "CANONICAL_EMBEDDING_DIM", "DENSE_VECTOR_NAME", "SPARSE_VECTOR_NAME",
    "DocumentDto", "ChunkDto", "EvidenceDto", "RetrievalResultDto", "IngestionJobDto",
]
