#!/usr/bin/env python3
"""Deterministic local observation for the Phase 1.5 grounded chat slice.

This benchmark intentionally measures the hermetic retrieval/Professor path;
it never contacts a provider, Qdrant, Redis or Locker service.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
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
from services.professor_backend import ProfessorChatBackend


DEMO_QUERY = (
    "Mastite bovina exige higiene rigorosa na ordenha, isolamento do animal "
    "afetado e avaliação veterinária antes da escolha do tratamento."
)
SAMPLES = 30


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(fraction * len(ordered)))
    return round(ordered[index], 3)


async def _run() -> dict[str, object]:
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

    limits = ProfessorLimits()
    result = {
        "phase": "1.5",
        "fixture": "demo-corpus-single-document",
        "samples": SAMPLES,
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "retrieval_ms": {"p50": _percentile(retrieval_samples, 0.50), "p95": _percentile(retrieval_samples, 0.95)},
        "professor_ms": {"p50": _percentile(professor_samples, 0.50), "p95": _percentile(professor_samples, 0.95)},
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
