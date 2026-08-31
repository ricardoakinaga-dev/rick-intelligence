#!/usr/bin/env python3
"""Measure the reproducible local Phase 0.5 workload shape."""

from __future__ import annotations

import json
import math
import resource
import time
from pathlib import Path

from phase05_e2e import (
    COLLECTION_ID,
    DOCUMENTS_ROOT,
    FILENAME,
    SOURCE_ROOT,
    SOURCE_TEXT,
    WORKSPACE_ID,
    _answer_from_retrieved_result,
    _configure_runtime,
    _count_points,
    _embedding,
    _search,
)


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return round(ordered[index], 3)


def storage_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def main() -> int:
    _, ingestion_service, vector_service = _configure_runtime()
    vector_service.ensure_collection(collection_name=COLLECTION_ID)
    source_path = SOURCE_ROOT / FILENAME
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(SOURCE_TEXT, encoding="utf-8")
    ingestion_service.get_embeddings_batch = _embedding
    vector_service._embed_query = lambda query: _embedding([query])[0]

    ingestion_service.ingest_document(
        source_path,
        workspace_id=WORKSPACE_ID,
        original_filename=FILENAME,
        qdrant_collection=COLLECTION_ID,
    )
    warm_search = _search(vector_service)
    _answer_from_retrieved_result(vector_service, warm_search)

    ingestion_samples = []
    for _ in range(5):
        started = time.perf_counter()
        ingestion_service.ingest_document(
            source_path,
            workspace_id=WORKSPACE_ID,
            original_filename=FILENAME,
            qdrant_collection=COLLECTION_ID,
        )
        ingestion_samples.append((time.perf_counter() - started) * 1000)

    retrieval_samples = []
    latest_search = None
    for _ in range(10):
        started = time.perf_counter()
        latest_search = _search(vector_service)
        retrieval_samples.append((time.perf_counter() - started) * 1000)

    answer_samples = []
    latest_answer = None
    for _ in range(5):
        started = time.perf_counter()
        latest_answer = _answer_from_retrieved_result(vector_service, latest_search)
        answer_samples.append((time.perf_counter() - started) * 1000)

    point_count = _count_points(vector_service, latest_search.results[0].document_id)
    result = {
        "status": "PASS",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "workspace_id": WORKSPACE_ID,
            "collection_id": COLLECTION_ID,
            "embedding_mode": "deterministic_test_double",
            "answer_mode": "deterministic_test_generator",
            "provider_quality": "NOT_RUN",
        },
        "workloads": {
            "ingestion_ms": {
                "n": len(ingestion_samples),
                "p50": percentile(ingestion_samples, 0.50),
                "p95": percentile(ingestion_samples, 0.95),
                "min": round(min(ingestion_samples), 3),
                "max": round(max(ingestion_samples), 3),
            },
            "retrieval_ms": {
                "n": len(retrieval_samples),
                "p50": percentile(retrieval_samples, 0.50),
                "p95": percentile(retrieval_samples, 0.95),
                "min": round(min(retrieval_samples), 3),
                "max": round(max(retrieval_samples), 3),
            },
            "answer_plumbing_ms": {
                "n": len(answer_samples),
                "p50": percentile(answer_samples, 0.50),
                "p95": percentile(answer_samples, 0.95),
                "min": round(min(answer_samples), 3),
                "max": round(max(answer_samples), 3),
            },
        },
        "observations": {
            "retrieval_results": len(latest_search.results),
            "answer_grounded": latest_answer.grounded,
            "point_count_for_document": point_count,
            "qdrant_storage_bytes_observed": storage_bytes(Path(".runtime/qdrant-storage")),
            "process_max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "limitations": [
            "Local loopback measurements only; not production SLOs or capacity limits.",
            "Embedding and answer timings use deterministic test doubles because no provider credential is configured.",
            "Qdrant storage size includes the isolated shared test collection, not only this document.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
