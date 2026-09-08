#!/usr/bin/env python3
"""Deterministic local observation for the Phase 1.5 grounded chat slice.

This benchmark intentionally measures the hermetic retrieval/Professor path;
it never contacts a provider, Qdrant, Redis or Locker service.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
for package in ("contracts", "authorization", "identity", "knowledge", "ingestion", "retrieval", "providers", "locking", "professor"):
    source = str(ROOT / "packages" / package / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
api_source = str(ROOT / "apps" / "api" / "src")
if api_source not in sys.path:
    sys.path.insert(0, api_source)

from rick_locking import InMemoryLeaseClient
from rick_professor import ProfessorLimits
from rick_providers import DeterministicProvider
from services.knowledge_service import seed_demo_corpus, seed_demo_points
from services.retrieval_service import RetrievalApplicationService
from services.professor_backend import ProfessorBackendError, ProfessorChatBackend


DEMO_QUERY = (
    "Mastite bovina exige higiene rigorosa na ordenha, isolamento do animal "
    "afetado e avaliação veterinária antes da escolha do tratamento."
)
SAMPLES = 30
SOAK_ITERATIONS = 10


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


async def _measure_stream(
    backend: ProfessorChatBackend,
    *,
    message: str,
    context: dict[str, object],
    conversation_id: str,
) -> tuple[float, float]:
    started = time.perf_counter()
    first_delta_ms: float | None = None
    final_status: str | None = None
    async for event in backend.generate_stream(
        message=message,
        context=context,
        conversation_id=conversation_id,
    ):
        elapsed_ms = (time.perf_counter() - started) * 1000
        if event.get("type") == "delta" and first_delta_ms is None:
            first_delta_ms = elapsed_ms
        elif event.get("type") == "final":
            result = event.get("result")
            if isinstance(result, dict):
                metadata = result.get("metadata")
                if isinstance(metadata, dict):
                    final_status = metadata.get("evidence_status")
    completion_ms = (time.perf_counter() - started) * 1000
    if first_delta_ms is None or final_status != "APPROVED_EVIDENCE":
        raise RuntimeError("local streaming benchmark did not produce a validated first token and completion")
    return first_delta_ms, completion_ms


class _FailingChatProvider:
    """Deterministic failure double used only by the local failure probe."""

    async def chat_completion(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("deterministic benchmark provider failure")


class _UnavailableLease:
    """Deterministic lease failure double used only by the local failure probe."""

    async def acquire(self, **kwargs: object) -> object:
        raise RuntimeError("deterministic benchmark lease failure")

    async def release(self, **kwargs: object) -> bool:
        return False


async def _run_failure_scenarios(
    retrieval: RetrievalApplicationService,
    *,
    context: dict[str, object],
) -> list[dict[str, object]]:
    scenarios: list[tuple[str, str, object]] = [
        (
            "provider_failure",
            "provider_failed",
            ProfessorChatBackend(
                retrieval=retrieval,
                provider=_FailingChatProvider(),
                lease=InMemoryLeaseClient(),
            ),
        ),
        (
            "lease_unavailable",
            "lease_unavailable",
            ProfessorChatBackend(
                retrieval=retrieval,
                provider=DeterministicProvider(embedding_dimensions=1536, environment="local"),
                lease=_UnavailableLease(),
            ),
        ),
    ]
    results: list[dict[str, object]] = []
    for scenario_id, expected_stage, backend in scenarios:
        status = "FAIL"
        observed = "unexpected_success"
        try:
            await backend.generate(
                message=DEMO_QUERY,
                context=context,
                conversation_id=f"failure-{scenario_id}",
            )
        except ProfessorBackendError as error:
            observed = error.stage
            status = "PASS" if error.stage == expected_stage else "FAIL"
        except Exception:
            observed = "unexpected_exception"
        results.append({
            "id": scenario_id,
            "scope": "LOCAL_DETERMINISTIC",
            "deterministic": True,
            "expected": expected_stage,
            "observed": observed,
            "status": status,
        })
    return results


async def _run_local_soak(
    backend: ProfessorChatBackend,
    *,
    context: dict[str, object],
) -> dict[str, object]:
    started = time.perf_counter()
    completed = 0
    failures = 0
    for index in range(SOAK_ITERATIONS):
        try:
            result = await backend.generate(
                message=DEMO_QUERY,
                context=context,
                conversation_id=f"soak-{index}",
            )
            completed += 1
            if result.get("metadata", {}).get("evidence_status") != "APPROVED_EVIDENCE":
                failures += 1
        except Exception:
            failures += 1
    return {
        "id": "bounded_local_soak",
        "scope": "LOCAL_DETERMINISTIC",
        "deterministic": True,
        "status": "PASS" if completed == SOAK_ITERATIONS and failures == 0 else "FAIL",
        "iterations": SOAK_ITERATIONS,
        "iterations_completed": completed,
        "failures": failures,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "invariants": ["all completions retained APPROVED_EVIDENCE", "no external dependency was contacted"],
    }


async def _run() -> dict[str, object]:
    memory_before = _memory_snapshot()
    from rick_knowledge import InMemoryKnowledgeStore

    knowledge = InMemoryKnowledgeStore()
    seed_demo_corpus(knowledge)
    retrieval = RetrievalApplicationService(knowledge=knowledge)
    retrieval.attach_points(seed_demo_points(knowledge, retrieval.embeddings))
    provider = DeterministicProvider(embedding_dimensions=1536, environment="local")
    lease = InMemoryLeaseClient()
    backend = ProfessorChatBackend(retrieval=retrieval, provider=provider, lease=lease)
    context = {
        "tenant_id": "default",
        "user_id": "benchmark-user",
        "workspace_id": "default",
        "allowed_collection_ids": ["rag_phase0"],
        "permissions": ["chat.query"],
    }

    for index in range(5):
        await backend.generate(message=DEMO_QUERY, context=context, conversation_id=f"warm-{index}")

    retrieval_samples: list[float] = []
    professor_samples: list[float] = []
    for index in range(SAMPLES):
        start = time.perf_counter()
        retrieval.retrieve(query=DEMO_QUERY, context=context)
        retrieval_samples.append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        result = await backend.generate(
            message=DEMO_QUERY,
            context=context,
            conversation_id=f"bench-{index}",
        )
        professor_samples.append((time.perf_counter() - start) * 1000)
        if result.get("metadata", {}).get("evidence_status") != "APPROVED_EVIDENCE":
            raise RuntimeError("benchmark fixture did not produce approved evidence")

    ttft_samples: list[float] = []
    completion_samples: list[float] = []
    for index in range(SAMPLES):
        ttft_ms, completion_ms = await _measure_stream(
            backend,
            message=DEMO_QUERY,
            context=context,
            conversation_id=f"stream-bench-{index}",
        )
        ttft_samples.append(ttft_ms)
        completion_samples.append(completion_ms)

    failure_scenarios = await _run_failure_scenarios(retrieval, context=context)
    soak_scenario = await _run_local_soak(backend, context=context)
    memory_after = _memory_snapshot()
    local_scenarios_pass = (
        soak_scenario.get("status") == "PASS"
        and all(item.get("status") == "PASS" for item in failure_scenarios)
    )

    limits = ProfessorLimits()
    result = {
        "schema_version": 2,
        "phase": "1.5",
        "fixture": "demo-corpus-single-document",
        "samples": SAMPLES,
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "retrieval_ms": _summary(retrieval_samples),
        "professor_ms": _summary(professor_samples),
        "ttft_ms": {"status": "OBSERVED", **_summary(ttft_samples)},
        "completion_ms": {"status": "OBSERVED", **_summary(completion_samples)},
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
                "reason": "External load and multi-replica capacity testing is outside this hermetic benchmark.",
            },
            "provider_soak": {
                "status": "NOT_RUN",
                "scope": "EXTERNAL",
                "reason": "No live provider or paid workload was contacted.",
            },
        },
        "bounds": {
            "provider_max_attempts": provider.config.max_attempts,
            "provider_max_response_bytes": 1_000_000,
            "professor_max_evidence_items": limits.max_evidence_items,
            "professor_max_evidence_chars": limits.max_evidence_chars,
            "professor_max_prompt_chars": limits.max_prompt_chars,
            "professor_max_answer_chars": limits.max_answer_chars,
        },
        "fixture_query_sha256": hashlib.sha256(DEMO_QUERY.encode("utf-8")).hexdigest(),
        "note": "Local hermetic observation only; no live provider, Qdrant, Redis or Locker latency claim.",
    }
    return result


def main() -> int:
    result = asyncio.run(_run())
    output = ROOT / "docs" / "progress" / "phase-1.5-perf.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("local_scenarios_status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
