"""Reciprocal Rank Fusion — RRF k=60, score 1/(k+rank+1), dense+sparse blend.

Numerically equivalent to the validated legacy `_rrf_fusion` (same constant,
same rank math, same per-source score tracking, same tie behavior).
"""

from __future__ import annotations

RRF_K = 60

_SCORE_FIELDS = frozenset({"score", "dense_score", "sparse_score"})


def _has_value(value: object) -> bool:
    """Treat null/empty provenance as absent while retaining valid zeroes."""
    if value is None:
        return False
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (dict, list)):
        return len(value) > 0
    return True


def _merge_provenance(target: dict, result: dict) -> None:
    """Fill provenance gaps when dense and sparse rows share a chunk ID."""
    for field, value in result.items():
        if field in _SCORE_FIELDS:
            continue
        if not _has_value(target.get(field)) and _has_value(value):
            target[field] = value


def _finalize_provenance(item: dict) -> None:
    """Keep canonical and compatibility citation fields mutually useful."""
    get = item.get
    value = get("page_start")
    if not _has_value(value):
        item["page_start"] = value = get("page_hint")
    if not _has_value(get("page_end")):
        item["page_end"] = value
    value = get("source")
    if not _has_value(value):
        value = get("source_title") or get("document_filename") or ""
        item["source"] = value
    if not _has_value(get("document_filename")):
        item["document_filename"] = value or ""
    if not _has_value(get("title")):
        item["title"] = get("source_title") or value or ""


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
    item = dict(result)
    item["chunk_id"] = chunk_id
    item.setdefault("document_id", None)
    item.setdefault("workspace_id", None)
    item.setdefault("text", "")
    if "page_start" not in item:
        item["page_start"] = item.get("page_hint")
    item.setdefault("page_end", None)
    item.setdefault("source", None)
    item.setdefault("title", None)
    item.setdefault("document_filename", None)
    item.setdefault("section", None)
    item.setdefault("checksum", None)
    if not item.get("collection_id"):
        item["collection_id"] = "rag_phase0"
    item["score"] = 0.0
    item["dense_score"] = 0.0
    item["sparse_score"] = 0.0
    return item
