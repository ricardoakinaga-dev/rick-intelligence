#!/usr/bin/env python3
"""Hermetic Phase 1.6 upload/ingest/retrieval observation.

The benchmark uses the real local application lifecycle and a temporary
private staging root. It records timings and limits only; document content,
paths, credentials, and external dependency latency never enter the artifact.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
for package in ("contracts", "knowledge", "ingestion", "retrieval"):
    source = str(ROOT / "packages" / package / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
api_source = str(ROOT / "apps" / "api" / "src")
if api_source not in sys.path:
    sys.path.insert(0, api_source)

from rick_ingestion import IngestionService
from rick_knowledge import InMemoryKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryBackend, InMemoryVectorStore
from services.ingestion_service import IngestionApplicationService
from services.retrieval_service import RetrievalApplicationService


SAMPLES = 30
MAX_UPLOAD_BYTES = 1 * 1024 * 1024


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(fraction * len(ordered)))
    return round(ordered[index], 3)


def main() -> int:
    knowledge = InMemoryKnowledgeStore()
    vectors = InMemoryVectorStore()
    embeddings = DeterministicHashEmbedding()
    retrieval = RetrievalApplicationService(knowledge=knowledge, vectors=vectors, embeddings=embeddings)

    with tempfile.TemporaryDirectory(prefix="rick-phase16-benchmark-") as root:
        canonical = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=embeddings)
        lifecycle = IngestionApplicationService(
            canonical,
            refresh_callback=lambda: retrieval.attach_points(vectors.all_points()),
            staging_root=Path(root),
            max_bytes=MAX_UPLOAD_BYTES,
            max_staged_bytes=2 * MAX_UPLOAD_BYTES,
            max_jobs=64,
        )

        upload_samples: list[float] = []
        enqueue_samples: list[float] = []
        for index in range(SAMPLES):
            content = (
                f"Benchmark document {index}: protocolo de manejo e higiene para avaliacao local. "
                * 10
            ).encode("utf-8")
            start = time.perf_counter()
            queued = lifecycle.submit_upload(
                content,
                filename=f"benchmark-{index}.txt",
                collection_id="rag_phase0",
                workspace_id="default",
                tenant_id="default",
            )
            enqueue_samples.append((time.perf_counter() - start) * 1000)
            job = queued
            for _ in range(1_000):
                job = lifecycle.get_status(
                    queued["job_id"],
                    tenant_id="default",
                    workspace_id="default",
                    allowed_collection_ids=["rag_phase0"],
                ) or queued
                if job.get("status") in {"published", "failed", "cancelled"}:
                    break
                time.sleep(0.001)
            upload_samples.append((time.perf_counter() - start) * 1000)
            if job.get("status") != "published":
                raise RuntimeError("local benchmark ingestion did not publish")

        context = {
            "user_id": "benchmark-user",
            "tenant_id": "default",
            "workspace_id": "default",
            "allowed_collection_ids": ["rag_phase0"],
            "permissions": ["chat.query"],
        }
        retrieval_samples: list[float] = []
        for _ in range(SAMPLES):
            start = time.perf_counter()
            result = retrieval.retrieve(
                query="protocolo de manejo e higiene",
                context=context,
                top_k=3,
            )
            retrieval_samples.append((time.perf_counter() - start) * 1000)
            if result.selected_count <= 0:
                raise RuntimeError("local benchmark retrieval returned no evidence")

        artifact = {
            "schema_version": 1,
            "phase": "1.6",
            "workload": "local upload -> canonical ingest -> refreshed retrieval",
            "samples": SAMPLES,
            "runtime": {"python": platform.python_version(), "platform": platform.platform()},
            "upload_ms": {"p50": _percentile(upload_samples, 0.50), "p95": _percentile(upload_samples, 0.95)},
            "enqueue_ms": {"p50": _percentile(enqueue_samples, 0.50), "p95": _percentile(enqueue_samples, 0.95)},
            "retrieval_ms": {"p50": _percentile(retrieval_samples, 0.50), "p95": _percentile(retrieval_samples, 0.95)},
            "bounds": {
                "max_upload_bytes": MAX_UPLOAD_BYTES,
                "max_staged_bytes": 2 * MAX_UPLOAD_BYTES,
                "max_jobs": 64,
                "retrieval_top_k": 3,
            },
            "workload_query_sha256": hashlib.sha256(b"protocolo de manejo e higiene").hexdigest(),
            "external_dependencies": {"provider": "NOT_RUN", "qdrant": "NOT_RUN", "redis_locker": "NOT_RUN"},
            "note": "Hermetic temporary storage and deterministic embeddings only; no production latency claim.",
        }

    output = ROOT / "docs" / "progress" / "phase-1.6-perf.json"
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
