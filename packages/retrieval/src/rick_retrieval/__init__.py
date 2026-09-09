"""Canonical retrieval package — hybrid dense+sparse engine as platform capability."""

from rick_retrieval.backends import DiskFallbackBackend, InMemoryBackend, QdrantBackend, RetrievalBackend
from rick_retrieval.fusion import RRF_K, rrf_fusion
from rick_retrieval.pipeline import (
    RetrievalEngine,
    RetrievalOptions,
    RetrievalResult,
    compute_confidence,
    dedupe_candidates,
    normalize_query,
    retrieval_quality_score,
)
from rick_retrieval.qdrant import (
    HttpResponse,
    HttpTransport,
    QdrantBoundsError,
    QdrantClosedError,
    QdrantConfigurationError,
    QdrantCircuitOpenError,
    QdrantAlias,
    QdrantCollectionInfo,
    QdrantDeleteResult,
    QdrantDependencyError,
    QdrantError,
    QdrantHealth,
    QdrantHttpVectorStore,
    QdrantLimits,
    QdrantMalformedResponseError,
    QdrantSearchHit,
    QdrantStatusError,
    QdrantTimeoutError,
    QdrantTransportError,
    QdrantValidationError,
)
from rick_retrieval.rerank import BM25FReranker, DisabledReranker, ModelReranker, Reranker
from rick_retrieval.sparse import (
    LOW_SIGNAL_DOMAIN_TOKENS,
    MEANINGLESS_QUERY_TOKENS,
    SPARSE_MODULUS,
    content_query_terms,
    sparse_hash,
    sparse_overlap_score,
    sparse_vector,
    tokenize_terms,
)
from rick_retrieval.sqlite_vector_store import (
    SQLiteVectorStore,
    SQLiteVectorStoreConfigurationError,
    SQLiteVectorStoreError,
    SQLiteVectorStoreValidationError,
)
from rick_retrieval.vectordb import (
    CANONICAL_EMBEDDING_DIM,
    CANONICAL_EMBEDDING_MODEL,
    DeterministicHashEmbedding,
    EmbeddingProvider,
    InMemoryVectorStore,
    MAX_POINTS_PER_READ,
    QdrantVectorStore,
    VectorStore,
)

__all__ = [
    "LOW_SIGNAL_DOMAIN_TOKENS", "MEANINGLESS_QUERY_TOKENS", "SPARSE_MODULUS",
    "CANONICAL_EMBEDDING_DIM", "CANONICAL_EMBEDDING_MODEL", "RRF_K",
    "MAX_POINTS_PER_READ",
    "BM25FReranker", "DeterministicHashEmbedding", "DisabledReranker",
    "DiskFallbackBackend", "EmbeddingProvider", "InMemoryBackend",
    "InMemoryVectorStore", "ModelReranker", "QdrantBackend", "Reranker",
    "HttpResponse", "HttpTransport", "QdrantBoundsError", "QdrantClosedError",
    "QdrantConfigurationError", "QdrantCircuitOpenError", "QdrantAlias",
    "QdrantCollectionInfo", "QdrantDeleteResult", "QdrantDependencyError",
    "QdrantError", "QdrantHealth",
    "QdrantHttpVectorStore", "QdrantLimits", "QdrantMalformedResponseError",
    "QdrantSearchHit", "QdrantStatusError", "QdrantTimeoutError",
    "QdrantTransportError", "QdrantValidationError", "RetrievalBackend",
    "RetrievalEngine", "RetrievalOptions", "RetrievalResult", "VectorStore",
    "SQLiteVectorStore", "SQLiteVectorStoreConfigurationError",
    "SQLiteVectorStoreError", "SQLiteVectorStoreValidationError",
    "compute_confidence", "content_query_terms", "dedupe_candidates",
    "normalize_query", "rrf_fusion", "sparse_hash", "sparse_overlap_score",
    "retrieval_quality_score", "sparse_vector", "tokenize_terms",
]
