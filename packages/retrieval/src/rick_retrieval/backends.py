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
               allowed_collection_ids: list[str], chunks: list[dict], limit: int,
               tenant_id: str) -> tuple[list[dict], list[dict]]: ...


def _in_scope(chunk: dict, workspace_id: str, allowed: set[str], tenant_id: str) -> bool:
    if chunk.get("tenant_id") != tenant_id:
        return False
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

    def search(self, *, query, query_vector, workspace_id, allowed_collection_ids, chunks, limit,
               tenant_id):
        allowed = set(allowed_collection_ids or [])
        scoped = [c for c in chunks if _in_scope(c, workspace_id, allowed, tenant_id)]
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
        dense = [c for c in dense if _in_scope(c, workspace_id, allowed, tenant_id)]
        sparse = [c for c in sparse if _in_scope(c, workspace_id, allowed, tenant_id)]
        return dense, sparse


class DiskFallbackBackend:
    """Disk fallback over persisted chunk files — same ACL, same scoring."""

    name = "disk-fallback"

    def __init__(self, root: Path) -> None:
        self.root = root

    def search(self, *, query, query_vector, workspace_id, allowed_collection_ids, chunks, limit,
               tenant_id):
        # `chunks` here are loaded from disk files (caller-owned); ACL enforced identically.
        return InMemoryBackend().search(
            query=query, query_vector=query_vector, workspace_id=workspace_id,
            allowed_collection_ids=allowed_collection_ids, chunks=chunks, limit=limit,
            tenant_id=tenant_id)


class QdrantBackend:
    """Live Qdrant backend (lazy client). Query-time workspace+collection filters."""

    name = "qdrant"

    def __init__(self, store) -> None:
        self.store = store

    def search(self, *, query, query_vector, workspace_id, allowed_collection_ids, chunks, limit,
               tenant_id):
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
        except ImportError as exc:
            raise RuntimeError("qdrant-client is not installed.") from exc
        allowed = set(allowed_collection_ids or [])
        if not allowed:
            return [], []
        # Use one scoped query per collection instead of selecting the first
        # grant. This is compatible with older qdrant-client versions and
        # preserves the same exact ACL when a user has several collections.
        scopes = [None] if "*" in allowed else sorted(allowed)
        dense: list[dict] = []
        for collection_id in scopes:
            must = [
                FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id)),
            ]
            if collection_id is not None:
                must.append(FieldCondition(key="collection_id", match=MatchValue(value=collection_id)))
            flt = Filter(must=must)
            dense_hits = self.store._client.search(
                collection_name=self.store.collection, query_vector=("dense", query_vector),
                query_filter=flt, limit=limit)
            for hit in dense_hits:
                payload = getattr(hit, "payload", None)
                if not isinstance(payload, dict) or not isinstance(payload.get("chunk_id"), str):
                    continue
                try:
                    score = float(hit.score)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(score):
                    continue
                dense.append({"chunk_id": payload["chunk_id"], "document_id": payload.get("document_id"),
                              "tenant_id": payload.get("tenant_id"),
                              "workspace_id": payload.get("workspace_id"), "text": payload.get("text", ""),
                              "collection_id": payload.get("collection_id"), "score": score})
        # A backend can return duplicate points across scoped calls; stable
        # point identity wins, then score determines the final top-k.
        deduped: dict[str, dict] = {}
        for item in dense:
            previous = deduped.get(item["chunk_id"])
            if previous is None or item["score"] > previous["score"]:
                deduped[item["chunk_id"]] = item
        dense = sorted(deduped.values(), key=lambda item: item["score"], reverse=True)[:limit]
        # Post-filter: defense in depth on trusted fields.
        allowed = set(allowed_collection_ids or [])
        dense = [c for c in dense if _in_scope(c, workspace_id, allowed, tenant_id)]
        return dense, []
