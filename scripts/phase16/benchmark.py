#!/usr/bin/env python3
"""Hermetic Phase 1.6 upload/ingest/retrieval observation.

The benchmark uses the real local application lifecycle and a temporary
private staging root. It records timings and limits only; document content,
paths, credentials, and external dependency latency never enter the artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
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
from services.ingestion_service import IngestionApplicationError, IngestionApplicationService
from services.retrieval_service import RetrievalApplicationService


SAMPLES = 30
MAX_UPLOAD_BYTES = 1 * 1024 * 1024
SOAK_ITERATIONS = SAMPLES


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("at least one sample is required")
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be between zero and one")
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(fraction * len(ordered)))
    return round(ordered[index], 3)


def _summary(values: list[float]) -> dict[str, float | int]:
    """Return additive percentile fields while preserving p50/p95 semantics."""

    return {
        "n": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def _current_rss_bytes() -> int | None:
    """Read current process RSS without adding a monitoring dependency."""

    try:
        fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return int(fields[1]) * page_size
    except (FileNotFoundError, IndexError, OSError, ValueError):
        return None


def _peak_rss_bytes() -> int | None:
    """Read process high-water RSS with a procfs value before resource fallback."""

    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if not line.startswith("VmHWM:"):
                continue
            fields = line.split()
            value = int(fields[1])
            unit = fields[2].lower() if len(fields) > 2 else "kb"
            return value * (1024 if unit in {"kb", "kib"} else 1)
    except (FileNotFoundError, IndexError, OSError, ValueError):
        pass

    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux reports KiB; macOS reports bytes.
        return value if sys.platform == "darwin" else value * 1024
    except (ImportError, OSError, ValueError):
        return None


def _memory_snapshot() -> dict[str, int | None]:
    return {
        "rss_bytes": _current_rss_bytes(),
        "peak_rss_bytes": _peak_rss_bytes(),
    }


def _memory_observation(
    before: dict[str, int | None], after: dict[str, int | None]
) -> dict[str, object]:
    current_values = [
        value for value in (before.get("rss_bytes"), after.get("rss_bytes"))
        if isinstance(value, int)
    ]
    peak_values = [
        value for value in (before.get("peak_rss_bytes"), after.get("peak_rss_bytes"))
        if isinstance(value, int)
    ]
    if not current_values and not peak_values:
        return {
            "status": "NOT_AVAILABLE",
            "unit": "bytes",
            "method": "procfs_and_resource",
            "reason": "The local runtime did not expose RSS observation APIs.",
        }
    before_rss = before.get("rss_bytes")
    after_rss = after.get("rss_bytes")
    return {
        "status": "OBSERVED",
        "unit": "bytes",
        "method": "procfs_rss_and_vmhwm_or_resource_maxrss",
        "rss_before_bytes": before_rss,
        "rss_after_bytes": after_rss,
        "rss_delta_bytes": (
            after_rss - before_rss
            if isinstance(before_rss, int) and isinstance(after_rss, int)
            else None
        ),
        "peak_rss_bytes": max(peak_values) if peak_values else None,
        "scope": "entire benchmark process; not an isolated request allocation",
    }


def _run_failure_scenarios(
    canonical: IngestionService,
    *,
    refresh_callback: object,
) -> list[dict[str, object]]:
    """Exercise bounded admission failures without starting external services."""

    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="rick-phase16-failure-") as root:
        lifecycle = IngestionApplicationService(
            canonical,
            refresh_callback=refresh_callback,
            staging_root=Path(root),
            max_bytes=16,
            max_staged_bytes=32,
            max_jobs=4,
        )
        scenarios = (
            ("oversized_upload", b"x" * 17, "request_too_large", "failure.txt"),
            ("empty_upload", b"", "validation_error", "empty.txt"),
            ("unsupported_extension", b"content", "unsupported_media_type", "failure.bin"),
        )
        try:
            for scenario_id, payload, expected_code, filename in scenarios:
                status = "FAIL"
                observed = "unexpected_success"
                try:
                    lifecycle.submit_upload(
                        payload,
                        filename=filename,
                        collection_id="rag_phase0",
                        workspace_id="default",
                        tenant_id="default",
                    )
                except IngestionApplicationError as error:
                    observed = error.code
                    status = "PASS" if error.code == expected_code else "FAIL"
                except Exception:
                    observed = "unexpected_exception"
                results.append({
                    "id": scenario_id,
                    "scope": "LOCAL_DETERMINISTIC",
                    "deterministic": True,
                    "expected": expected_code,
                    "observed": observed,
                    "status": status,
                })
        finally:
            lifecycle.close()
    return results


def main() -> int:
    memory_before = _memory_snapshot()
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
        published_count = 0
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
            published_count += 1

        context = {
            "user_id": "benchmark-user",
            "tenant_id": "default",
            "workspace_id": "default",
            "allowed_collection_ids": ["rag_phase0"],
            "permissions": ["chat.query"],
        }
        retrieval_samples: list[float] = []
        retrieval_success_count = 0
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
            retrieval_success_count += 1

        failure_scenarios = _run_failure_scenarios(
            canonical,
            refresh_callback=lambda: retrieval.attach_points(vectors.all_points()),
        )
        soak_scenario = {
            "id": "bounded_local_soak",
            "scope": "LOCAL_DETERMINISTIC",
            "deterministic": True,
            "status": (
                "PASS"
                if published_count == SOAK_ITERATIONS and retrieval_success_count == SOAK_ITERATIONS
                else "FAIL"
            ),
            "iterations": SOAK_ITERATIONS,
            "iterations_completed": min(published_count, retrieval_success_count),
            "upload_published": published_count,
            "retrieval_with_evidence": retrieval_success_count,
            "failures": (SOAK_ITERATIONS - published_count) + (SOAK_ITERATIONS - retrieval_success_count),
            "definition": "bounded sequential upload and retrieval samples; no concurrency or wall-time target",
            "invariants": ["all uploads published", "all retrievals returned evidence", "no external dependency was contacted"],
        }
        lifecycle.close()

    memory_after = _memory_snapshot()
    local_scenarios_pass = (
        soak_scenario.get("status") == "PASS"
        and all(item.get("status") == "PASS" for item in failure_scenarios)
    )

    artifact = {
        "schema_version": 2,
        "phase": "1.6",
        "workload": "local upload -> canonical ingest -> refreshed retrieval",
        "samples": SAMPLES,
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "upload_ms": _summary(upload_samples),
        "enqueue_ms": _summary(enqueue_samples),
        "retrieval_ms": _summary(retrieval_samples),
        "ttft_ms": {
            "status": "NOT_APPLICABLE",
            "reason": "Phase 1.6 exercises ingestion and retrieval; it has no generated token stream.",
        },
        "completion_ms": {
            "status": "NOT_APPLICABLE",
            "reason": "Phase 1.6 has no answer-generation completion event.",
        },
        "memory": _memory_observation(memory_before, memory_after),
        "cost": {
            "status": "NOT_RUN",
            "amount": None,
            "currency": None,
            "reason": "No billing telemetry is available and no external provider was executed.",
        },
        "failure_scenarios": failure_scenarios,
        "soak_scenario": soak_scenario,
        "local_scenarios_status": "PASS" if local_scenarios_pass else "FAIL",
        "external_scenarios": {
            "distributed_load": {
                "status": "NOT_RUN",
                "scope": "EXTERNAL",
                "reason": "External load, failover and multi-replica capacity testing is outside this hermetic benchmark.",
            },
            "dependency_down": {
                "status": "NOT_RUN",
                "scope": "EXTERNAL",
                "reason": "No Qdrant, Redis, object store or worker service was stopped or contacted.",
            },
        },
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
    return 0 if artifact.get("local_scenarios_status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
