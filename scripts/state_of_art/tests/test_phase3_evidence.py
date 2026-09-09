from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts.state_of_art import generate_phase3_evidence
from scripts.state_of_art.phase3_evidence import (
    MATRIX_SCHEMA,
    MatrixValidationError,
    artifact_set_digest,
    evaluate_matrix,
    parse_matrix,
)


HEAD = "a" * 40
TREE = "c" * 40
CHECKOUT = "b" * 64


def _ref(root: Path, path: str, description: str) -> dict[str, str]:
    return {
        "path": path,
        "sha256": sha256((root / path).read_bytes()).hexdigest(),
        "description": description,
    }


def _raw_ref(root: Path, filename: str, *, status: str = "PASS") -> dict[str, str]:
    path = root / filename
    path.write_text(
        json.dumps({"schema_version": "fixture-runtime-gate.v1", "status": status, "results": []}) + "\n",
        encoding="utf-8",
    )
    return _ref(root, filename, "raw runtime gate fixture")


def _runtime_sentinel() -> dict[str, object]:
    snapshot = {
        "available": True,
        "head": HEAD,
        "tree": TREE,
        "fingerprint": CHECKOUT,
        "status": "CLEAN",
    }
    return {"before": snapshot, "after": dict(snapshot), "unchanged": True}


def _runtime_record(
    raw_ref: dict[str, str],
    *,
    status: str = "PASS",
    production_safe: bool = False,
    observed_at: str | None = None,
    freshness: str = "CURRENT",
    reviewer: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "state-of-art-runtime-evidence.v1",
        "record_id": "runtime-fixture-helper-1",
        "capability_id": "P0-TEST",
        "status": status,
        "commit_sha": HEAD,
        "tree_sha": TREE,
        "checkout_fingerprint": CHECKOUT,
        "checkout_available": True,
        "clean_worktree": True,
        "checkout_sentinel": _runtime_sentinel(),
        "environment": "fixture-runtime",
        "procedure": "fixture runtime procedure",
        "exit_status": 0 if status in {"PASS", "VERIFIED_RUNTIME", "PROMOTABLE"} else 2,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "artifact_sha256": raw_ref["sha256"],
        "raw_artifacts": [raw_ref],
        "freshness": freshness,
        "production_safe": production_safe,
        "reviewer": reviewer or {"id": "runner", "kind": "automated", "name": "fixture runner", "independent": False},
        "limitations": "fixture is local only",
        "next_action": "run an independent review",
    }


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, object]]:
    (tmp_path / "audit.md").write_text("audit\n", encoding="utf-8")
    (tmp_path / "test.py").write_text("assert True\n", encoding="utf-8")
    artifacts = [_ref(tmp_path, "audit.md", "audit artifact")]
    capability = {
        "capability_id": "P0-TEST",
        "title": "fixture capability",
        "priority": "P0",
        "status": "LOCAL_VERIFIED",
        "code_tests": ["test.py"],
        "runtime_evidence": [],
        "commit_sha": HEAD,
        "artifact_sha256": artifact_set_digest(artifacts),
        "artifact_refs": artifacts,
        "environment": "test",
        "reviewer": {"id": "fixture", "kind": "automated", "name": "fixture reviewer", "independent": False},
        "procedure": "fixture local validation",
        "exit_status": 0,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "limitations": "fixture is local only",
        "next_action": "run a real runtime fixture",
    }
    payload: dict[str, object] = {
        "schema_version": MATRIX_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": "test",
        "source_prompt": "audit.md",
        "source_prompt_sha256": sha256((tmp_path / "audit.md").read_bytes()).hexdigest(),
        "candidate": {
            "commit_sha": HEAD,
            "tree_sha": TREE,
            "checkout_fingerprint": CHECKOUT,
            "clean_worktree": True,
        },
        "capabilities": [capability],
    }
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    checkout = {
        "available": True,
        "head": HEAD,
        "tree": TREE,
        "fingerprint": CHECKOUT,
        "status": "CLEAN",
        "errors": [],
    }
    return path, payload, checkout


def test_local_matrix_is_valid_but_not_promotable(tmp_path: Path) -> None:
    path, _, checkout = _fixture(tmp_path)

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "PARTIAL"
    assert result["rejection_codes"] == []


def test_wrong_commit_matrix_is_rejected(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    payload["candidate"]["commit_sha"] = "d" * 40  # type: ignore[index]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "WRONG_COMMIT_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_stale_matrix_generated_at_is_rejected(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    payload["generated_at"] = "2000-01-01T00:00:00+00:00"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "STALE_RUNTIME_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_local_check_diagnostics_are_redacted_before_persistence() -> None:
    rendered = generate_phase3_evidence._redacted_tail(
        "DATABASE_URL=postgresql://user:super-secret@example.invalid/db token=another-secret"
    )

    assert "super-secret" not in rendered
    assert "another-secret" not in rendered
    assert "[REDACTED]" in rendered


def test_unavailable_checkout_is_rejected_even_when_identity_fields_match(tmp_path: Path) -> None:
    path, _, checkout = _fixture(tmp_path)
    checkout["available"] = False
    checkout["errors"] = ["git status unavailable"]

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "MISSING_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_wrong_artifact_hash_matrix_is_rejected(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    (tmp_path / "audit.md").write_text("tampered\n", encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "WRONG_HASH_REJECTED" in result["rejection_codes"]


def test_blocked_runtime_matrix_is_explicitly_blocking(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    payload["capabilities"][0]["status"] = "BLOCKED_EXTERNAL"  # type: ignore[index]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "BLOCKED_EXTERNAL"
    assert "BLOCKED_RUNTIME_REJECTED" in result["rejection_codes"]


def test_missing_matrix_artifact_is_rejected(tmp_path: Path) -> None:
    path, _, checkout = _fixture(tmp_path)
    (tmp_path / "audit.md").unlink()

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "MISSING_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_promotable_requires_runtime_evidence_and_independent_review(tmp_path: Path) -> None:
    path, payload, _ = _fixture(tmp_path)
    payload["capabilities"][0]["status"] = "PROMOTABLE"  # type: ignore[index]
    with pytest.raises(MatrixValidationError, match="runtime_evidence"):
        parse_matrix(payload)


def test_complete_evaluation_rejects_missing_required_capability_rows(tmp_path: Path) -> None:
    path, _, checkout = _fixture(tmp_path)

    result = evaluate_matrix(path, checkout, root=tmp_path)

    assert result["classification"] == "FAILED"
    assert "P0-02" in result["reason"]
    assert result["rejection_codes"] == ["MISSING_EVIDENCE_REJECTED"]


def test_verified_runtime_requires_independent_reviewer(tmp_path: Path) -> None:
    path, payload, _ = _fixture(tmp_path)
    payload["capabilities"][0]["status"] = "VERIFIED_RUNTIME"  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [{  # type: ignore[index]
        "path": "audit.md",
        "sha256": sha256((tmp_path / "audit.md").read_bytes()).hexdigest(),
        "description": "runtime envelope",
    }]

    with pytest.raises(MatrixValidationError, match="independent reviewer"):
        parse_matrix(payload)


def test_verified_runtime_cannot_reuse_static_artifact_as_runtime_evidence(tmp_path: Path) -> None:
    path, payload, _ = _fixture(tmp_path)
    payload["capabilities"][0]["status"] = "VERIFIED_RUNTIME"  # type: ignore[index]
    payload["capabilities"][0]["reviewer"]["independent"] = True  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [{  # type: ignore[index]
        "path": "audit.md",
        "sha256": sha256((tmp_path / "audit.md").read_bytes()).hexdigest(),
        "description": "reused static artifact",
    }]

    with pytest.raises(MatrixValidationError, match="must not reuse artifact_refs"):
        parse_matrix(payload)


def test_verified_runtime_is_not_promotable_without_explicit_production_promotion(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-success.json")
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({
        "schema_version": "state-of-art-runtime-evidence.v1",
        "record_id": "runtime-fixture-1",
        "capability_id": "P0-TEST",
        "status": "PASS",
        "commit_sha": HEAD,
        "tree_sha": TREE,
        "checkout_fingerprint": CHECKOUT,
        "checkout_available": True,
        "clean_worktree": True,
        "checkout_sentinel": _runtime_sentinel(),
        "environment": "fixture-runtime",
        "procedure": "fixture runtime procedure",
        "exit_status": 0,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "artifact_sha256": raw_ref["sha256"],
        "raw_artifacts": [raw_ref],
        "freshness": "CURRENT",
        "production_safe": False,
        "reviewer": {"id": "runner", "kind": "automated", "name": "fixture runner", "independent": False},
        "limitations": "fixture is local only",
        "next_action": "run an independent review",
    }), encoding="utf-8")
    payload["capabilities"][0]["status"] = "VERIFIED_RUNTIME"  # type: ignore[index]
    payload["capabilities"][0]["reviewer"]["independent"] = True  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(tmp_path, "runtime.json", "runtime envelope")]  # type: ignore[index]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "PARTIAL"
    assert result["rejection_codes"] == []


def test_promotable_capability_requires_runtime_production_safety(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-not-production-safe.json")
    runtime = tmp_path / "runtime-not-production-safe.json"
    runtime.write_text(json.dumps(_runtime_record(raw_ref)), encoding="utf-8")
    payload["capabilities"][0]["status"] = "PROMOTABLE"  # type: ignore[index]
    payload["capabilities"][0]["reviewer"]["independent"] = True  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(  # type: ignore[index]
        tmp_path,
        "runtime-not-production-safe.json",
        "runtime envelope",
    )]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "MISSING_EVIDENCE_REJECTED" in result["rejection_codes"]
    assert "production_safe" in result["reason"]


def test_explicit_production_safe_promotable_capability_classifies_promotable(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-production-safe.json")
    runtime = tmp_path / "runtime-production-safe.json"
    runtime.write_text(
        json.dumps(_runtime_record(raw_ref, production_safe=True)),
        encoding="utf-8",
    )
    payload["capabilities"][0]["status"] = "PROMOTABLE"  # type: ignore[index]
    payload["capabilities"][0]["reviewer"]["independent"] = True  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(  # type: ignore[index]
        tmp_path,
        "runtime-production-safe.json",
        "production-safe runtime envelope",
    )]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "PROMOTABLE"
    assert result["rejection_codes"] == []


def test_runtime_envelope_requires_checkout_sentinel(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-no-sentinel.json", status="BLOCKED_EXTERNAL")
    runtime = tmp_path / "runtime-no-sentinel.json"
    runtime_record = _runtime_record(raw_ref, status="BLOCKED_EXTERNAL")
    del runtime_record["checkout_sentinel"]
    runtime.write_text(json.dumps(runtime_record), encoding="utf-8")
    payload["capabilities"][0]["status"] = "BLOCKED_EXTERNAL"  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(  # type: ignore[index]
        tmp_path,
        "runtime-no-sentinel.json",
        "runtime envelope without checkout sentinel",
    )]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "checkout_sentinel" in result["reason"]


def test_current_label_with_old_runtime_observed_at_is_rejected(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-old-observed-at.json", status="BLOCKED_EXTERNAL")
    runtime = tmp_path / "runtime-old-observed-at.json"
    runtime.write_text(
        json.dumps(_runtime_record(
            raw_ref,
            status="BLOCKED_EXTERNAL",
            observed_at="2000-01-01T00:00:00+00:00",
        )),
        encoding="utf-8",
    )
    payload["capabilities"][0]["status"] = "BLOCKED_EXTERNAL"  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(  # type: ignore[index]
        tmp_path,
        "runtime-old-observed-at.json",
        "old runtime envelope",
    )]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "STALE_RUNTIME_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_old_capability_observed_at_is_rejected_even_with_current_runtime_envelope(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    payload["capabilities"][0]["observed_at"] = "2000-01-01T00:00:00+00:00"  # type: ignore[index]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "STALE_RUNTIME_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_runtime_envelope_requires_nonempty_reviewer_fields(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-empty-reviewer.json", status="BLOCKED_EXTERNAL")
    runtime = tmp_path / "runtime-empty-reviewer.json"
    runtime.write_text(
        json.dumps(_runtime_record(
            raw_ref,
            status="BLOCKED_EXTERNAL",
            reviewer={"id": " ", "kind": "automated", "name": "fixture runner", "independent": False},
        )),
        encoding="utf-8",
    )
    payload["capabilities"][0]["status"] = "BLOCKED_EXTERNAL"  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(  # type: ignore[index]
        tmp_path,
        "runtime-empty-reviewer.json",
        "runtime envelope with empty reviewer",
    )]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "reviewer" in result["reason"]


def test_blocked_runtime_envelope_is_bound_without_becoming_a_pass(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-blocked.json", status="BLOCKED_EXTERNAL")
    runtime = tmp_path / "runtime-blocked.json"
    runtime.write_text(json.dumps({
        "schema_version": "state-of-art-runtime-evidence.v1",
        "record_id": "runtime-fixture-blocked-1",
        "capability_id": "P0-TEST",
        "status": "BLOCKED_EXTERNAL",
        "commit_sha": HEAD,
        "tree_sha": TREE,
        "checkout_fingerprint": CHECKOUT,
        "checkout_available": True,
        "clean_worktree": True,
        "checkout_sentinel": _runtime_sentinel(),
        "environment": "fixture-runtime",
        "procedure": "fixture runtime procedure was not executable",
        "exit_status": 2,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "artifact_sha256": raw_ref["sha256"],
        "raw_artifacts": [raw_ref],
        "freshness": "CURRENT",
        "production_safe": False,
        "reviewer": {"id": "runner", "kind": "automated", "name": "fixture runner", "independent": False},
        "limitations": "fixture dependency is unavailable",
        "next_action": "provide the dependency",
    }), encoding="utf-8")
    payload["capabilities"][0]["status"] = "BLOCKED_EXTERNAL"  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(tmp_path, "runtime-blocked.json", "blocked runtime envelope")]  # type: ignore[index]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "BLOCKED_EXTERNAL"
    assert "BLOCKED_RUNTIME_REJECTED" in result["rejection_codes"]
    assert "MISSING_EVIDENCE_REJECTED" not in result["rejection_codes"]


def test_non_json_raw_artifact_is_rejected_even_when_hash_matches(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw = tmp_path / "raw-non-json.json"
    raw.write_text("not-json\n", encoding="utf-8")
    raw_ref = _ref(tmp_path, "raw-non-json.json", "malformed raw gate output")
    runtime = tmp_path / "runtime-non-json-raw.json"
    runtime.write_text(json.dumps(_runtime_record(raw_ref, status="BLOCKED_EXTERNAL")), encoding="utf-8")
    payload["capabilities"][0]["status"] = "BLOCKED_EXTERNAL"  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(  # type: ignore[index]
        tmp_path,
        "runtime-non-json-raw.json",
        "runtime envelope with malformed raw artifact",
    )]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "MISSING_EVIDENCE_REJECTED" in result["rejection_codes"]
    assert "raw_artifacts" in result["reason"]


def test_raw_gate_status_must_match_runtime_envelope(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-status-mismatch.json", status="FAIL")
    runtime = tmp_path / "runtime-status-mismatch.json"
    runtime.write_text(
        json.dumps(_runtime_record(raw_ref, production_safe=True)),
        encoding="utf-8",
    )
    payload["capabilities"][0]["status"] = "PROMOTABLE"  # type: ignore[index]
    payload["capabilities"][0]["reviewer"]["independent"] = True  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(  # type: ignore[index]
        tmp_path,
        "runtime-status-mismatch.json",
        "runtime envelope with mismatched raw gate status",
    )]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "status_mismatch" in result["reason"]
    assert "MISSING_EVIDENCE_REJECTED" in result["rejection_codes"]


@pytest.mark.parametrize("raw_status", ["PROMOTABLE", "VERIFIED_RUNTIME"])
def test_raw_gate_cannot_self_promote(raw_status: str, tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, f"raw-{raw_status.lower()}.json", status=raw_status)
    runtime = tmp_path / f"runtime-{raw_status.lower()}.json"
    runtime.write_text(
        json.dumps(_runtime_record(raw_ref, production_safe=True)),
        encoding="utf-8",
    )
    payload["capabilities"][0]["status"] = "PROMOTABLE"  # type: ignore[index]
    payload["capabilities"][0]["reviewer"]["independent"] = True  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(  # type: ignore[index]
        tmp_path,
        runtime.name,
        "runtime envelope with promotion-level raw status",
    )]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "unsupported_gate_status" in result["reason"]
    assert "MISSING_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_missing_raw_artifact_is_rejected(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-missing.json")
    runtime = tmp_path / "runtime-missing-raw.json"
    runtime.write_text(json.dumps(_runtime_record(raw_ref, status="BLOCKED_EXTERNAL")), encoding="utf-8")
    (tmp_path / "raw-missing.json").unlink()
    payload["capabilities"][0]["status"] = "BLOCKED_EXTERNAL"  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(  # type: ignore[index]
        tmp_path,
        "runtime-missing-raw.json",
        "runtime envelope with missing raw artifact",
    )]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "MISSING_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_runtime_envelope_wrong_tree_is_rejected(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-wrong-tree.json")
    runtime = tmp_path / "runtime-wrong-tree.json"
    runtime.write_text(json.dumps({
        "schema_version": "state-of-art-runtime-evidence.v1",
        "record_id": "runtime-fixture-wrong-tree-1",
        "capability_id": "P0-TEST",
        "status": "PASS",
        "commit_sha": HEAD,
        "tree_sha": "d" * 40,
        "checkout_fingerprint": CHECKOUT,
        "checkout_available": True,
        "clean_worktree": True,
        "checkout_sentinel": {
            "before": {"available": True, "head": HEAD, "tree": "d" * 40, "fingerprint": CHECKOUT, "status": "CLEAN"},
            "after": {"available": True, "head": HEAD, "tree": "d" * 40, "fingerprint": CHECKOUT, "status": "CLEAN"},
            "unchanged": True,
        },
        "environment": "fixture-runtime",
        "procedure": "fixture runtime procedure",
        "exit_status": 0,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "artifact_sha256": raw_ref["sha256"],
        "raw_artifacts": [raw_ref],
        "freshness": "CURRENT",
        "production_safe": False,
        "reviewer": {"id": "runner", "kind": "automated", "name": "fixture runner", "independent": False},
        "limitations": "fixture is local only",
        "next_action": "run an independent review",
    }), encoding="utf-8")
    payload["capabilities"][0]["status"] = "PARTIAL"  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(tmp_path, "runtime-wrong-tree.json", "wrong tree envelope")]  # type: ignore[index]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "WRONG_COMMIT_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_stale_runtime_envelope_is_rejected(tmp_path: Path) -> None:
    path, payload, checkout = _fixture(tmp_path)
    raw_ref = _raw_ref(tmp_path, "raw-stale.json", status="BLOCKED_EXTERNAL")
    runtime = tmp_path / "runtime-stale.json"
    runtime.write_text(json.dumps({
        "schema_version": "state-of-art-runtime-evidence.v1",
        "record_id": "runtime-fixture-stale-1",
        "capability_id": "P0-TEST",
        "status": "BLOCKED_EXTERNAL",
        "commit_sha": HEAD,
        "tree_sha": TREE,
        "checkout_fingerprint": CHECKOUT,
        "checkout_available": True,
        "clean_worktree": True,
        "checkout_sentinel": _runtime_sentinel(),
        "environment": "fixture-runtime",
        "procedure": "fixture runtime procedure",
        "exit_status": 2,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "artifact_sha256": raw_ref["sha256"],
        "raw_artifacts": [raw_ref],
        "freshness": "STALE",
        "production_safe": False,
        "reviewer": {"id": "runner", "kind": "automated", "name": "fixture runner", "independent": False},
        "limitations": "fixture is stale",
        "next_action": "run a current fixture",
    }), encoding="utf-8")
    payload["capabilities"][0]["status"] = "BLOCKED_EXTERNAL"  # type: ignore[index]
    payload["capabilities"][0]["runtime_evidence"] = [_ref(tmp_path, "runtime-stale.json", "stale runtime envelope")]  # type: ignore[index]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "STALE_RUNTIME_EVIDENCE_REJECTED" in result["rejection_codes"]


def test_verify_missing_matrix_returns_nonzero(tmp_path: Path) -> None:
    assert generate_phase3_evidence.main([
        "--root",
        str(tmp_path),
        "--output",
        "missing.json",
        "--verify",
    ]) == 1


def test_missing_observed_tree_is_rejected(tmp_path: Path) -> None:
    path, _, checkout = _fixture(tmp_path)
    checkout["tree"] = None

    result = evaluate_matrix(path, checkout, root=tmp_path, require_complete=False)

    assert result["classification"] == "FAILED"
    assert "WRONG_COMMIT_EVIDENCE_REJECTED" in result["rejection_codes"]
