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
from rick_retrieval.vectordb import (
    CANONICAL_EMBEDDING_DIM,
    CANONICAL_EMBEDDING_MODEL,
    DeterministicHashEmbedding,
    EmbeddingProvider,
    InMemoryVectorStore,
    QdrantVectorStore,
    VectorStore,
)

__all__ = [
    "LOW_SIGNAL_DOMAIN_TOKENS", "MEANINGLESS_QUERY_TOKENS", "SPARSE_MODULUS",
    "CANONICAL_EMBEDDING_DIM", "CANONICAL_EMBEDDING_MODEL", "RRF_K",
    "BM25FReranker", "DeterministicHashEmbedding", "DisabledReranker",
    "DiskFallbackBackend", "EmbeddingProvider", "InMemoryBackend",
    "InMemoryVectorStore", "ModelReranker", "QdrantBackend", "Reranker",
    "RetrievalBackend", "RetrievalEngine", "RetrievalOptions", "RetrievalResult",
    "VectorStore", "compute_confidence", "content_query_terms", "dedupe_candidates",
    "normalize_query", "rrf_fusion", "sparse_hash", "sparse_overlap_score",
    "sparse_vector", "tokenize_terms",
]
