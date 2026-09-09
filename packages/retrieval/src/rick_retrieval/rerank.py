"""Rerankers: disabled / current deterministic BM25F / future model slot.

BM25FReranker mirrors the validated local reranker: IDF over candidates,
k1=1.5 b=0.75 avgdl=200, field weights body 1.0 / filename 0.3 / tags 0.2,
positional decay on body, geometric-mean blend with retrieval quality, and an
original-score tie-break. Deterministic, no external calls.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

from rick_retrieval.sparse import content_query_terms, tokenize_terms


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[dict]) -> list[dict]: ...


class DisabledReranker:
    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        return list(candidates)


class BM25FReranker:
    def __init__(self, k1: float = 1.5, b: float = 0.75, avg_doc_len: int = 200) -> None:
        self.k1 = k1
        self.b = b
        self.avg_doc_len = avg_doc_len
        self._idf_cache: dict = {}

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return candidates
        query_terms = content_query_terms(query) or set(tokenize_terms(query))
        if not query_terms:
            return candidates
        idf = self._compute_idf(sorted(query_terms), [c.get("text", "") for c in candidates])
        scored = []
        for cand in candidates:
            text = cand.get("text", "")
            filename = cand.get("document_filename", "") or ""
            tags = " ".join(cand.get("tags", []) or [])
            doc_len = len(text.split())
            body = self._field_score(sorted(query_terms), text, idf, doc_len, 1.0, True)
            fname = self._field_score(sorted(query_terms), filename, idf, max(len(filename.split()), 1), 0.3, False)
            tag_score = self._field_score(sorted(query_terms), tags, idf, max(len(tags.split()), 1), 0.2, False)
            bm25f = body + fname + tag_score
            new_cand = dict(cand)
            new_cand["original_score"] = cand.get("score", 0.0)
            new_cand["bm25f_score"] = bm25f
            quality = cand.get("retrieval_quality_score", cand.get("confidence_score", 0.0)) or 0.0
            if quality > 0 and bm25f > 0:
                new_cand["score"] = (quality * bm25f) ** 0.5
            else:
                new_cand["score"] = max(quality, bm25f)
            scored.append(new_cand)
        scored.sort(key=lambda x: (x.get("score", 0.0), x.get("original_score", 0.0)), reverse=True)
        return scored

    def _field_score(self, terms, field_text, idf, doc_len, weight, pos_decay) -> float:
        field_terms = tokenize_terms(field_text)
        if not field_terms:
            return 0.0
        score = 0.0
        for rank, term in enumerate(field_terms):
            if term not in terms:
                continue
            tf = field_terms.count(term)
            tf_norm = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / max(self.avg_doc_len, 1)))
            pos = 1.0 / (rank + 1) if pos_decay else 1.0
            score += idf.get(term, 0.0) * tf_norm * pos * weight
        return score

    def _compute_idf(self, query_terms: list[str], texts: list[str]) -> dict[str, float]:
        digest = hashlib.md5("\x1f".join(texts).encode("utf-8")).hexdigest()
        cache_key = (tuple(sorted(set(query_terms))), len(texts), digest)
        if cache_key in self._idf_cache:
            return self._idf_cache[cache_key]
        n = len(texts)
        if n == 0:
            idf = {t: 1.0 for t in query_terms}
            self._idf_cache[cache_key] = idf
            return idf
        idf: dict[str, float] = {}
        universe = set(query_terms)
        for text in texts:
            universe.update(tokenize_terms(text))
        for term in universe:
            df = sum(1 for text in texts if term in tokenize_terms(text))
            idf[term] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
        self._idf_cache[cache_key] = idf
        return idf


class ModelReranker:
    """Future model-reranker slot: delegates to an embedding similarity backend.

    Falls back to unchanged order when the backend is unavailable (offline-safe,
    mirroring the legacy neural reranker contract).
    """

    def __init__(self, embed=None) -> None:
        self._embed = embed

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        if not candidates or not query or self._embed is None:
            return list(candidates)
        try:
            query_vec = self._embed([query])[0]
            cand_vecs = self._embed([c.get("text", "")[:8000] for c in candidates])
        except Exception:
            return list(candidates)
        scored = []
        for cand, vec in zip(candidates, cand_vecs):
            sim = _cosine(query_vec, vec)
            new_cand = dict(cand)
            quality = cand.get("retrieval_quality_score", cand.get("confidence_score", 0.0)) or 0.0
            new_cand["score"] = (quality * sim) ** 0.5 if quality > 0 and sim > 0 else max(quality, sim)
            scored.append(new_cand)
        scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return scored


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0
