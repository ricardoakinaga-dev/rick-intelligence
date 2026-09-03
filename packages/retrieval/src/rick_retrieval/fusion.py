"""Reciprocal Rank Fusion — RRF k=60, score 1/(k+rank+1), dense+sparse blend.

Numerically equivalent to the validated legacy `_rrf_fusion` (same constant,
same rank math, same per-source score tracking, same tie behavior).
"""

from __future__ import annotations

RRF_K = 60


def rrf_fusion(dense_results: list[dict], sparse_results: list[dict], k: int = RRF_K) -> list[dict]:
    scores: dict[str, dict] = {}
    for rank, result in enumerate(dense_results):
        chunk_id = result["chunk_id"]
        score = 1.0 / (k + rank + 1)
        if chunk_id not in scores:
            scores[chunk_id] = _blank(result, chunk_id)
        scores[chunk_id]["score"] += score
        scores[chunk_id]["dense_score"] = max(scores[chunk_id]["dense_score"], float(result.get("score", 0.0) or 0.0))
    for rank, result in enumerate(sparse_results):
        chunk_id = result["chunk_id"]
        score = 1.0 / (k + rank + 1)
        if chunk_id in scores:
            scores[chunk_id]["score"] += score
        else:
            scores[chunk_id] = {**_blank(result, chunk_id), "score": score}
        scores[chunk_id]["sparse_score"] = max(
            scores[chunk_id]["sparse_score"],
            float(result.get("sparse_score", result.get("score", 0.0)) or 0.0),
        )
    return sorted(scores.values(), key=lambda item: item["score"], reverse=True)


def _blank(result: dict, chunk_id: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": result.get("document_id"),
        "workspace_id": result.get("workspace_id"),
        "text": result.get("text", ""),
        "page_start": result.get("page_start", result.get("page_hint")),
        "section": result.get("section"),
        "checksum": result.get("checksum"),
        "collection_id": result.get("collection_id") or "rag_phase0",
        "score": 0.0,
        "dense_score": 0.0,
        "sparse_score": 0.0,
    }
