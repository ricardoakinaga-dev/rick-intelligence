from __future__ import annotations

import json
from pathlib import Path

from scripts.state_of_art import generate_release_evidence
from scripts.state_of_art.release_manifest import ReviewerRef


HEAD = "a" * 40
TREE = "b" * 40
ARTIFACT_HASH = "c" * 64
TIMESTAMP = "2026-09-10T00:00:00+00:00"


def _reviewer() -> ReviewerRef:
    return ReviewerRef(
        reviewer_id="fixture-reviewer",
        kind="automated",
        name="fixture generator",
        independent=False,
    )


def test_runtime_gate_artifact_registry_points_to_named_envelopes() -> None:
    assert generate_release_evidence.RUNTIME_GATE_ARTIFACTS == {
        "multi-worker": ".runtime/phase-3/multi-worker-runtime-evidence.json",
        "multi-tenant": ".runtime/phase-3/tenant-evidence-runtime-evidence.json",
        "redis": ".runtime/phase-3/redis-multi-replica-runtime-evidence.json",
        "redis-multi-replica": ".runtime/phase-3/redis-multi-replica-runtime-evidence.json",
        "postgresql": ".runtime/phase-3/postgres-runtime-evidence.json",
        "qdrant": ".runtime/phase-3/object-qdrant-runtime-evidence.json",
        "object-storage": ".runtime/phase-3/object-qdrant-runtime-evidence.json",
        "ingestion-e2e": ".runtime/phase-3/golden-ingestion-runtime-evidence.json",
        "evidence": ".runtime/phase-3/tenant-evidence-runtime-evidence.json",
        "citation": ".runtime/phase-3/golden-ingestion-runtime-evidence.json",
        "decision": ".runtime/phase-3/golden-ingestion-runtime-evidence.json",
        "observability": ".runtime/phase-3/observability-runtime-evidence.json",
        "restore": ".runtime/phase-3/restore-runtime-evidence.json",
        "dr": ".runtime/phase-3/restore-runtime-evidence.json",
        "file-security": ".runtime/phase-3/file-security-runtime-evidence.json",
        "chaos": ".runtime/phase-3/chaos-runtime-evidence.json",
        "soak": ".runtime/phase-3/soak-runtime-evidence.json",
        "performance": ".runtime/phase-3/performance-runtime-evidence.json",
        "frontend-e2e": ".runtime/phase-3/frontend-supply-runtime-evidence.json",
        "accessibility": ".runtime/phase-3/frontend-supply-runtime-evidence.json",
        "visual": ".runtime/phase-3/frontend-supply-runtime-evidence.json",
        "supply-chain": ".runtime/phase-3/supply-chain-runtime-evidence.json",
        "provider": ".runtime/phase-3/provider-runtime-evidence.json",
    }


def test_missing_runtime_artifact_is_not_run_not_fabricated_block(tmp_path: Path) -> None:
    audit = tmp_path / "audit.md"
    audit.write_text("audit\n", encoding="utf-8")

    result = generate_release_evidence._runtime_result(
        tmp_path,
        "postgresql",
        "audit.md",
        _reviewer(),
        commit_sha=HEAD,
        tree_sha=TREE,
        artifact_hash=ARTIFACT_HASH,
        timestamp=TIMESTAMP,
    )

    assert result.result == "NOT_RUN"
    assert result.exit_status is None
    assert result.evidence_paths[0].path == "audit.md"


def test_runtime_artifact_status_is_aggregated(tmp_path: Path) -> None:
    gate_id = "observability"
    runtime_path = tmp_path / generate_release_evidence.RUNTIME_GATE_ARTIFACTS[gate_id]
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        json.dumps({"status": "FAIL", "exit_status": 1, "reason": "runtime assertion failed"}),
        encoding="utf-8",
    )

    result = generate_release_evidence._runtime_result(
        tmp_path,
        gate_id,
        "audit.md",
        _reviewer(),
        commit_sha=HEAD,
        tree_sha=TREE,
        artifact_hash=ARTIFACT_HASH,
        timestamp=TIMESTAMP,
    )

    assert result.result == "FAIL"
    assert result.exit_status == 1
    assert result.evidence_paths[0].path == generate_release_evidence.RUNTIME_GATE_ARTIFACTS[gate_id]
