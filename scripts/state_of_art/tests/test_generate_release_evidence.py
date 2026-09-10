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


def test_local_ci_gate_artifact_registry_is_explicit_and_disjoint() -> None:
    assert generate_release_evidence.CI_GATE_ARTIFACTS == {
        "architecture": ".runtime/ci/architecture.json",
        "contracts": ".runtime/ci/contracts.json",
        "security": ".runtime/ci/security.json",
        "unit": ".runtime/ci/unit.json",
        "supply-chain": ".runtime/ci/supply-chain.json",
    }
    assert not (set(generate_release_evidence.CI_GATE_ARTIFACTS) - {"supply-chain"}) & {
        "multi-worker",
        "multi-tenant",
        "redis",
        "postgresql",
        "qdrant",
        "object-storage",
        "ingestion-e2e",
        "evidence",
        "citation",
        "decision",
        "observability",
        "dr",
        "restore",
        "file-security",
        "chaos",
        "soak",
        "performance",
        "frontend-e2e",
        "accessibility",
        "visual",
        "provider",
    }


def test_supply_chain_runtime_remains_primary_with_ci_as_supplement(tmp_path: Path) -> None:
    audit = tmp_path / "audit.md"
    audit.write_text("audit\n", encoding="utf-8")
    runtime_path = tmp_path / generate_release_evidence.RUNTIME_GATE_ARTIFACTS["supply-chain"]
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(json.dumps({"status": "PASS", "exit_status": 0}), encoding="utf-8")
    ci_path = tmp_path / generate_release_evidence.CI_GATE_ARTIFACTS["supply-chain"]
    ci_path.parent.mkdir(parents=True, exist_ok=True)
    ci_path.write_text(
        json.dumps({"schema_version": "state-of-art-ci-evidence.v1", "status": "PASS", "exit_status": 0}),
        encoding="utf-8",
    )

    result = generate_release_evidence._runtime_result(
        tmp_path,
        "supply-chain",
        "audit.md",
        _reviewer(),
        commit_sha=HEAD,
        tree_sha=TREE,
        artifact_hash=ARTIFACT_HASH,
        timestamp=TIMESTAMP,
        supplemental_ci_relative=generate_release_evidence.CI_GATE_ARTIFACTS["supply-chain"],
    )

    assert result.command == ("runtime-envelope", generate_release_evidence.RUNTIME_GATE_ARTIFACTS["supply-chain"])
    assert [item.path for item in result.evidence_paths] == [
        generate_release_evidence.RUNTIME_GATE_ARTIFACTS["supply-chain"],
        generate_release_evidence.CI_GATE_ARTIFACTS["supply-chain"],
    ]


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


def test_ci_artifact_status_is_aggregated(tmp_path: Path) -> None:
    audit = tmp_path / "audit.md"
    audit.write_text("audit\n", encoding="utf-8")
    gate_id = "unit"
    ci_path = tmp_path / generate_release_evidence.CI_GATE_ARTIFACTS[gate_id]
    ci_path.parent.mkdir(parents=True)
    ci_path.write_text(
        json.dumps(
            {
                "schema_version": "state-of-art-ci-evidence.v1",
                "status": "PASS",
                "exit_status": 0,
                "limitations": ["local CI only"],
            }
        ),
        encoding="utf-8",
    )

    result = generate_release_evidence._ci_result(
        tmp_path,
        gate_id,
        "audit.md",
        _reviewer(),
        commit_sha=HEAD,
        tree_sha=TREE,
        artifact_hash=ARTIFACT_HASH,
        timestamp=TIMESTAMP,
    )

    assert result.result == "PASS"
    assert result.exit_status == 0
    assert result.evidence_paths[0].path == generate_release_evidence.CI_GATE_ARTIFACTS[gate_id]


def test_invalid_ci_artifact_status_is_not_promoted(tmp_path: Path) -> None:
    audit = tmp_path / "audit.md"
    audit.write_text("audit\n", encoding="utf-8")
    gate_id = "security"
    ci_path = tmp_path / generate_release_evidence.CI_GATE_ARTIFACTS[gate_id]
    ci_path.parent.mkdir(parents=True)
    ci_path.write_text(
        json.dumps(
            {
                "schema_version": "state-of-art-ci-evidence.v1",
                "status": "PASS",
                "exit_status": 1,
                "limitations": ["contradictory fixture"],
            }
        ),
        encoding="utf-8",
    )

    result = generate_release_evidence._ci_result(
        tmp_path,
        gate_id,
        "audit.md",
        _reviewer(),
        commit_sha=HEAD,
        tree_sha=TREE,
        artifact_hash=ARTIFACT_HASH,
        timestamp=TIMESTAMP,
    )

    assert result.result == "INVALID"
    assert result.exit_status == 1


def test_canonical_workflow_binds_ci_artifacts_to_the_same_run() -> None:
    workflow = Path(__file__).parents[3] / ".github/workflows/quality.yml"
    text = workflow.read_text(encoding="utf-8")

    for lane, gate in (
        ("fast", "architecture"),
        ("unit", "unit"),
        ("contract", "contracts"),
        ("security", "security"),
        ("supply-chain", "supply-chain"),
    ):
        assert "ci_lane_evidence.py" in text
        assert f"--lane {lane}" in text
        assert f"--gate {gate}" in text
        assert f"ci-{gate}-${{{{ github.run_id }}}}" in text

    assert "Download architecture CI envelope from this workflow run" in text
    assert "Download supply-chain CI envelope from this workflow run" in text
    assert "cvg-master-rag-v2','rick-professor','modulo-redis-locker" in text
    assert "run: make phase3-frontend-supply-runtime" in text
    assert ".runtime/phase-3" in text
