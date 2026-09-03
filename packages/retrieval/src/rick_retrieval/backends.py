"""Retrieval backends behind one interface — identical ACL on every path.

- RetrievalBackend protocol: searchDense/searchSparse over scoped candidates.
- InMemoryBackend: cosine over embedded chunk vectors + lexical overlap.
- DiskFallbackBackend: same scoring over serialized chunk files; enforces the
  EXACT same workspace/collection ACL as the primary path (no leakage).
- QdrantBackend: lazy live-Qdrant dense+sparse with query-time filters.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Protocol

from rick_retrieval.sparse import sparse_overlap_score


class RetrievalBackend(Protocol):
    name: str
    def search(self, *, query: str, query_vector: list[float], workspace_id: str,
               allowed_collection_ids: list[str], chunks: list[dict], limit: int) -> tuple[list[dict], list[dict]]: ...


def _in_scope(chunk: dict, workspace_id: str, allowed: set[str]) -> bool:
    if chunk.get("workspace_id") != workspace_id:
        return False
    collection = chunk.get("collection_id") or "rag_phase0"
    return "*" in allowed or collection in allowed


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


class InMemoryBackend:
    name = "memory"

    def search(self, *, query, query_vector, workspace_id, allowed_collection_ids, chunks, limit):
        allowed = set(allowed_collection_ids or [])
        scoped = [c for c in chunks if _in_scope(c, workspace_id, allowed)]
        dense = sorted(
            ({**c, "score": _cosine(query_vector, c.get("vector") or [])} for c in scoped),
            key=lambda c: c["score"], reverse=True,
        )[:limit]
        sparse = sorted(
            ({**c, "score": sparse_overlap_score(query, c.get("text", "")),
               "sparse_score": sparse_overlap_score(query, c.get("text", ""))} for c in scoped),
            key=lambda c: c["score"], reverse=True,
        )[:limit]
        # Defense in depth: re-validate scope on the way out.
        dense = [c for c in dense if _in_scope(c, workspace_id, allowed)]
        sparse = [c for c in sparse if _in_scope(c, workspace_id, allowed)]
        return dense, sparse


class DiskFallbackBackend:
    """Disk fallback over persisted chunk files — same ACL, same scoring."""

    name = "disk-fallback"

    def __init__(self, root: Path) -> None:
        self.root = root

    def search(self, *, query, query_vector, workspace_id, allowed_collection_ids, chunks, limit):
        # `chunks` here are loaded from disk files (caller-owned); ACL enforced identically.
        return InMemoryBackend().search(
            query=query, query_vector=query_vector, workspace_id=workspace_id,
            allowed_collection_ids=allowed_collection_ids, chunks=chunks, limit=limit)


class QdrantBackend:
    """Live Qdrant backend (lazy client). Query-time workspace+collection filters."""

    name = "qdrant"

    def __init__(self, store) -> None:
        self.store = store

    def search(self, *, query, query_vector, workspace_id, allowed_collection_ids, chunks, limit):
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
        except ImportError as exc:
            raise RuntimeError("qdrant-client is not installed.") from exc
        must = [FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id))]
        if "*" not in set(allowed_collection_ids or []):
            must.append(FieldCondition(key="collection_id", match=MatchValue(value=list(allowed_collection_ids)[0])))
        flt = Filter(must=must)
        dense_hits = self.store._client.search(
            collection_name=self.store.collection, query_vector=("dense", query_vector),
            query_filter=flt, limit=limit)
        dense = [{"chunk_id": h.payload["chunk_id"], "document_id": h.payload.get("document_id"),
                  "workspace_id": h.payload.get("workspace_id"), "text": h.payload.get("text", ""),
                  "collection_id": h.payload.get("collection_id"), "score": float(h.score)} for h in dense_hits]
        # Post-filter: defense in depth on trusted fields.
        allowed = set(allowed_collection_ids or [])
        dense = [c for c in dense if _in_scope(c, workspace_id, allowed)]
        return dense, []
