"""Embedding + vector-store interfaces with hermetic and lazy-real backends.

- EmbeddingProvider protocol (model, dimensions, embed). Dimension mismatch
  fails explicitly before any index write (model-change safety).
- DeterministicHashEmbedding: hermetic test/dev backend — deterministic
  token-hash vectors at the canonical 1536 dimensions. Documented as
  NON-semantic (tests only); production uses a real provider via this iface.
- VectorStore protocol + InMemoryVectorStore (idempotent upsert by point_id,
  per-document counts/deletes) + QdrantVectorStore (lazy qdrant-client import;
  only constructed when explicitly selected).
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

CANONICAL_EMBEDDING_MODEL = "text-embedding-3-small"
CANONICAL_EMBEDDING_DIM = 1536
MAX_POINTS_PER_READ = 100_000


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    def upsert_points(self, points: list[dict]) -> int: ...
    def delete_document(self, document_id: str, collection_id: str) -> int: ...
    def count_for_document(self, document_id: str, collection_id: str) -> int: ...


class DeterministicHashEmbedding:
    """Deterministic hermetic embedding (tests/dev only — NOT semantic)."""

    model = "hash-stub-1536"
    dimensions = CANONICAL_EMBEDDING_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        import re

        tokens = re.findall(r"\w{2,}", (text or "").lower()) or ["empty"]
        vec = [0.0] * self.dimensions
        for token in tokens:
            digest = hashlib.md5(token.encode()).digest()
            for i in range(0, len(digest), 2):
                idx = (digest[i] * 256 + digest[i + 1]) % self.dimensions
                vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class InMemoryVectorStore:
    """Idempotent point store keyed by point_id (re-ingest converges, no drift)."""

    def __init__(self) -> None:
        self._points: dict[str, dict] = {}

    def upsert_points(self, points: list[dict]) -> int:
        for point in points:
            self._points[point["point_id"]] = point
        return len(points)

    def delete_document(self, document_id: str, collection_id: str) -> int:
        doomed = [pid for pid, p in self._points.items()
                  if p["payload"].get("document_id") == document_id
                  and p["payload"].get("collection_id") == collection_id]
        for pid in doomed:
            del self._points[pid]
        return len(doomed)

    def count_for_document(self, document_id: str, collection_id: str) -> int:
        return sum(1 for p in self._points.values()
                   if p["payload"].get("document_id") == document_id
                   and p["payload"].get("collection_id") == collection_id)

    def all_points(self, *, limit: int = MAX_POINTS_PER_READ) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= MAX_POINTS_PER_READ:
            raise ValueError("point read limit is out of range")
        if len(self._points) > limit:
            raise ValueError("complete point snapshot exceeds read limit")
        return list(self._points.values())


class QdrantVectorStore:
    """Qdrant adapter: named vectors, canonical payload, query-time ACL filters.

    qdrant-client is imported lazily in the constructor so domain code and unit
    tests never require the dependency or a live server.
    """

    COLLECTION = "rag_phase0"

    def __init__(self, *, url: str = "http://localhost:6333", collection: str = COLLECTION) -> None:
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError("qdrant-client is not installed; Qdrant backend unavailable.") from exc
        self._client = QdrantClient(url=url)
        self.collection = collection

    def upsert_points(self, points: list[dict]) -> int:
        from qdrant_client.models import PointStruct

        self._client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=p["point_id"], vector={"dense": p["vector"]}, payload=p["payload"]) for p in points],
        )
        return len(points)

    def delete_document(self, document_id: str, collection_id: str) -> int:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        self._client.delete(
            collection_name=self.collection,
            points_selector=Filter(must=[
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                FieldCondition(key="collection_id", match=MatchValue(value=collection_id)),
            ]),
        )
        return 0

    def count_for_document(self, document_id: str, collection_id: str) -> int:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        return self._client.count(
            collection_name=self.collection,
            count_filter=Filter(must=[
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                FieldCondition(key="collection_id", match=MatchValue(value=collection_id)),
            ]),
            exact=True,
        ).count
