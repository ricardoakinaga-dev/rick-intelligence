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
    runtime_path = tmp_path / ".runtime/phase-3/postgres-runtime-evidence.json"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_text(
        json.dumps({"status": "BLOCKED_EXTERNAL", "exit_status": 2, "reason": "owned lab is unavailable"}),
        encoding="utf-8",
    )

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

    assert result.result == "BLOCKED_EXTERNAL"
    assert result.exit_status == 2
    assert result.evidence_paths[0].path.endswith("postgres-runtime-evidence.json")
