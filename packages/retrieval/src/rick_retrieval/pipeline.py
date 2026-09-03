"""Canonical retrieval pipeline.

normalize → dense → sparse → fusion → authorization revalidation →
deduplication → reranking → context selection (budget) → evidence.

Input: query + canonical RetrievalContext (built by packages/authorization) +
options. No FastAPI. Evidence provenance is immutable once selected.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from rick_retrieval.backends import RetrievalBackend
from rick_retrieval.fusion import rrf_fusion
from rick_retrieval.rerank import DisabledReranker
from rick_retrieval.sparse import content_query_terms, sparse_overlap_score, tokenize_terms

DEFAULT_TOP_K = 5
DEFAULT_CANDIDATE_MULTIPLIER = 10
DEFAULT_CANDIDATE_FLOOR = 20
DEFAULT_MAX_CONTEXT_CHARS = 12000
DIVERSITY_ADJACENT_PENALTY = True


def normalize_query(query: str, *, max_chars: int = 2000) -> str:
    cleaned = re.sub(r"\s+", " ", (query or "")).strip()
    if not cleaned:
        raise ValueError("empty query")
    return cleaned[:max_chars]


def _lexical_diversity_ratio(text: str) -> float:
    tokens = tokenize_terms(text)
    if len(tokens) < 20:
        return 1.0
    return len(set(tokens)) / len(tokens)


def _has_minimal_support(query: str, text: str) -> bool:
    content_terms = content_query_terms(query)
    text_terms = set(tokenize_terms(text))
    if content_terms:
        return bool(content_terms.intersection(text_terms))
    non_numeric = {t for t in set(tokenize_terms(query)) if not t.isdigit()}
    if not non_numeric:
        return True
    return bool(non_numeric.intersection({t for t in text_terms if not t.isdigit()}))


def compute_confidence(item: dict, query: str | None = None) -> float:
    """Human-readable confidence blend (mirror of validated semantics)."""
    dense = max(0.0, min(1.0, float(item.get("dense_score", 0.0) or 0.0)))
    sparse = max(0.0, min(1.0, math.tanh(float(item.get("sparse_score", 0.0) or 0.0) / 4.0)))
    rrf = max(0.0, min(1.0, math.tanh(float(item.get("score", 0.0) or 0.0) * 30.0)))
    diversity = _lexical_diversity_ratio(item.get("text", ""))
    support = _has_minimal_support(query, item.get("text", "")) if query else True
    if dense <= 0 and sparse <= 0:
        return max(0.0, min(1.0, rrf))
    if dense > 0 and sparse > 0:
        combined = max(dense, sparse) + min(dense, sparse) * 0.15 + rrf * 0.10
        if sparse > 0 and not support and dense < 0.55:
            combined = min(combined, 0.19)
        return max(0.0, min(1.0, combined))
    score = max(dense, sparse)
    if dense > 0 and sparse <= 0 and diversity < 0.2:
        score *= max(0.1, diversity / 0.2)
        score += rrf * 0.10
    elif sparse > 0 and not support and dense < 0.55:
        score = min(score, 0.19)
    else:
        score += rrf * 0.10
    return max(0.0, min(1.0, score))


def dedupe_candidates(candidates: list[dict]) -> list[dict]:
    """Drop near-duplicate adjacent chunks (same doc, overlapping text) — keep first."""
    seen_texts: set[str] = set()
    out: list[dict] = []
    for cand in candidates:
        fingerprint = (cand.get("document_id"), (cand.get("text", "") or "")[:120])
        if fingerprint in seen_texts:
            continue
        seen_texts.add(fingerprint)
        out.append(cand)
    return out


@dataclass
class RetrievalOptions:
    top_k: int = DEFAULT_TOP_K
    rerank: bool = False
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS
    candidate_multiplier: int = DEFAULT_CANDIDATE_MULTIPLIER


@dataclass
class RetrievalResult:
    query: str
    evidence: list[dict] = field(default_factory=list)
    candidate_count: int = 0
    selected_count: int = 0
    backend: str = ""
    fallback_used: bool = False


class RetrievalEngine:
    def __init__(self, *, backend: RetrievalBackend, fallback: RetrievalBackend | None = None,
                 reranker=None, embed=None) -> None:
        self.backend = backend
        self.fallback = fallback
        self.reranker = reranker or DisabledReranker()
        self._embed = embed

    def retrieve(self, *, query: str, context: dict, options: RetrievalOptions | None = None) -> RetrievalResult:
        options = options or RetrievalOptions()
        normalized = normalize_query(query)
        workspace_id = context["workspace_id"]
        allowed = list(context.get("allowed_collection_ids") or [])
        chunks = self._chunks()
        query_vector = self._embed_query(normalized)
        limit = max(options.top_k * options.candidate_multiplier, DEFAULT_CANDIDATE_FLOOR)

        dense, sparse = self.backend.search(
            query=normalized, query_vector=query_vector, workspace_id=workspace_id,
            allowed_collection_ids=allowed, chunks=chunks, limit=limit)
        fallback_used = False
        if not dense and not sparse and self.fallback is not None:
            dense, sparse = self.fallback.search(
                query=normalized, query_vector=query_vector, workspace_id=workspace_id,
                allowed_collection_ids=allowed, chunks=chunks, limit=limit)
            fallback_used = bool(dense or sparse)

        fused = rrf_fusion(dense, sparse)
        # Authorization revalidation (defense in depth) + dedup.
        allowed_set = set(allowed)
        fused = [c for c in fused
                 if c.get("workspace_id") == workspace_id
                 and ("*" in allowed_set or (c.get("collection_id") or "rag_phase0") in allowed_set)]
        fused = dedupe_candidates(fused)
        for item in fused:
            item["confidence_score"] = compute_confidence(item, normalized)
        fused.sort(key=lambda i: (float(i.get("confidence_score", 0.0) or 0.0),
                                  float(i.get("score", 0.0) or 0.0)), reverse=True)
        if options.rerank:
            fused = self.reranker.rerank(normalized, fused)

        # Context selection under a char budget (never unbounded concatenation).
        evidence: list[dict] = []
        budget = options.max_context_chars
        for rank, item in enumerate(fused[:options.top_k]):
            if budget <= 0:
                break
            text = item.get("text", "")
            budget -= len(text)
            evidence.append({
                "evidence_id": f"ev-{item.get('chunk_id')}",
                "document_id": item.get("document_id"),
                "chunk_id": item.get("chunk_id"),
                "workspace_id": item.get("workspace_id"),
                "collection_id": item.get("collection_id") or "rag_phase0",
                "text": text,
                "source": item.get("document_filename") or item.get("source") or "",
                "title": item.get("title") or "",
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end", item.get("page_start")),
                "section": item.get("section"),
                "checksum": item.get("checksum") or "",
                "score": float(item.get("score", 0.0) or 0.0),
                "rank": rank,
                "dense_score": float(item.get("dense_score", 0.0) or 0.0),
                "sparse_score": float(item.get("sparse_score", 0.0) or 0.0),
            })
        return RetrievalResult(query=normalized, evidence=evidence, candidate_count=len(fused),
                               selected_count=len(evidence), backend=self.backend.name,
                               fallback_used=fallback_used)

    # -- seams (subclass/override in adapters; default in-memory index) --------
    def _chunks(self) -> list[dict]:
        return list(getattr(self, "_index", []) or [])

    def attach_index(self, chunks: list[dict]) -> None:
        self._index = list(chunks)

    def _embed_query(self, query: str) -> list[float]:
        if self._embed is None:
            return []
        return self._embed([query])[0]
