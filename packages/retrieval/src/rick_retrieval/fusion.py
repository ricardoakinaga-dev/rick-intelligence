"""Reciprocal Rank Fusion — RRF k=60, score 1/(k+rank+1), dense+sparse blend.

Numerically equivalent to the validated legacy `_rrf_fusion` (same constant,
same rank math, same per-source score tracking, same tie behavior).
"""

from __future__ import annotations

RRF_K = 60

_SCORE_FIELDS = frozenset({"score", "dense_score", "sparse_score"})


def _has_value(value: object) -> bool:
    """Treat null/empty provenance as absent while retaining valid zeroes."""
    return value is not None and value != "" and value != {} and value != []


def _merge_provenance(target: dict, result: dict) -> None:
    """Fill provenance gaps when dense and sparse rows share a chunk ID."""
    for field, value in result.items():
        if field in _SCORE_FIELDS:
            continue
        if not _has_value(target.get(field)) and _has_value(value):
            target[field] = value


def _finalize_provenance(item: dict) -> None:
    """Keep canonical and compatibility citation fields mutually useful."""
    if not _has_value(item.get("page_start")):
        item["page_start"] = item.get("page_hint")
    if not _has_value(item.get("page_end")):
        item["page_end"] = item.get("page_start")
    if not _has_value(item.get("source")):
        item["source"] = item.get("source_title") or item.get("document_filename") or ""
    if not _has_value(item.get("document_filename")):
        item["document_filename"] = item.get("source") or ""
    if not _has_value(item.get("title")):
        item["title"] = item.get("source_title") or item.get("source") or ""


def rrf_fusion(dense_results: list[dict], sparse_results: list[dict], k: int = RRF_K) -> list[dict]:
    scores: dict[str, dict] = {}
    for rank, result in enumerate(dense_results):
        chunk_id = result["chunk_id"]
        score = 1.0 / (k + rank + 1)
        if chunk_id not in scores:
            scores[chunk_id] = _blank(result, chunk_id)
        else:
            _merge_provenance(scores[chunk_id], result)
        scores[chunk_id]["score"] += score
        scores[chunk_id]["dense_score"] = max(scores[chunk_id]["dense_score"], float(result.get("score", 0.0) or 0.0))
    for rank, result in enumerate(sparse_results):
        chunk_id = result["chunk_id"]
        score = 1.0 / (k + rank + 1)
        if chunk_id in scores:
            _merge_provenance(scores[chunk_id], result)
            scores[chunk_id]["score"] += score
        else:
            scores[chunk_id] = {**_blank(result, chunk_id), "score": score}
        scores[chunk_id]["sparse_score"] = max(
            scores[chunk_id]["sparse_score"],
            float(result.get("sparse_score", result.get("score", 0.0)) or 0.0),
        )
    for item in scores.values():
        _finalize_provenance(item)
    return sorted(scores.values(), key=lambda item: item["score"], reverse=True)


def _blank(result: dict, chunk_id: str) -> dict:
    return {
        **result,
        "chunk_id": chunk_id,
        "document_id": result.get("document_id"),
        "workspace_id": result.get("workspace_id"),
        "text": result.get("text", ""),
        "page_start": result.get("page_start", result.get("page_hint")),
        "page_end": result.get("page_end"),
        "source": result.get("source"),
        "title": result.get("title"),
        "document_filename": result.get("document_filename"),
        "section": result.get("section"),
        "checksum": result.get("checksum"),
        "collection_id": result.get("collection_id") or "rag_phase0",
        "score": 0.0,
        "dense_score": 0.0,
        "sparse_score": 0.0,
    }
