from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch

from scripts.state_of_art import ci_lane_evidence


HEAD = "a" * 40
TREE = "b" * 40
FINGERPRINT = "c" * 64


def _checkout(*, fingerprint: str = FINGERPRINT, status: str = "CLEAN") -> dict[str, object]:
    return {
        "available": True,
        "head": HEAD,
        "tree": TREE,
        "fingerprint": fingerprint,
        "status": status,
        "errors": [],
    }


def _environment(*, secret: str = "top-secret-token") -> dict[str, str]:
    return {
        "CI_SECRET_TOKEN": secret,
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_JOB": "unit",
        "GITHUB_REPOSITORY": "example/rick-intelligence",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "12345",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_SHA": HEAD,
        "GITHUB_WORKFLOW": "RICK canonical quality lanes",
        "GITHUB_WORKFLOW_REF": "ricardoakinaga-dev/rick-intelligence/.github/workflows/quality.yml@refs/heads/main",
    }


def _command(code: str) -> tuple[str, ...]:
    return (sys.executable, "-c", code)


def test_pass_writes_bound_redacted_raw_artifact(tmp_path: Path) -> None:
    output = tmp_path / ".runtime/ci/unit.json"
    with patch.object(
        ci_lane_evidence,
        "capture_checkout",
        side_effect=[_checkout(), _checkout()],
    ):
        envelope = ci_lane_evidence.run_lane(
            tmp_path,
            "unit",
            ("unit",),
            (_command('print("CI_SECRET_TOKEN=top-secret-token")'),),
            output=output,
            environment=_environment(),
            timeout_seconds=10,
        )

    assert envelope["status"] == "PASS"
    assert envelope["exit_status"] == 0
    assert envelope["exit_code"] == 0
    assert envelope["started_at"]
    assert envelope["finished_at"]
    assert envelope["finished_at"] >= envelope["started_at"]
    assert envelope["commit_sha"] == HEAD
    assert envelope["tree_sha"] == TREE
    assert envelope["run"]["run_id"] == "12345"
    raw_path = tmp_path / envelope["raw_artifacts"][0]["path"]
    assert raw_path.is_file()
    assert "top-secret-token" not in raw_path.read_text(encoding="utf-8")
    assert "[REDACTED]" in raw_path.read_text(encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == ci_lane_evidence.SCHEMA_VERSION


def test_failed_command_keeps_a_non_passing_envelope(tmp_path: Path) -> None:
    output = tmp_path / ".runtime/ci/security.json"
    with patch.object(
        ci_lane_evidence,
        "capture_checkout",
        side_effect=[_checkout(), _checkout()],
    ):
        envelope = ci_lane_evidence.run_lane(
            tmp_path,
            "security",
            ("security",),
            (_command("raise SystemExit(3)"),),
            output=output,
            environment=_environment(),
            timeout_seconds=10,
        )

    assert envelope["status"] == "FAIL"
    assert envelope["exit_status"] == 1
    assert envelope["exit_code"] == 1
    assert envelope["started_at"]
    assert envelope["finished_at"]
    assert envelope["commands"][0]["status"] == "FAIL"
    assert envelope["commands"][0]["exit_status"] == 3
    assert envelope["raw_artifacts"]


def test_missing_github_provenance_is_not_run(tmp_path: Path) -> None:
    output = tmp_path / ".runtime/ci/contract.json"
    with patch.object(
        ci_lane_evidence,
        "capture_checkout",
        side_effect=[_checkout(), _checkout()],
    ):
        envelope = ci_lane_evidence.run_lane(
            tmp_path,
            "contract",
            ("contracts",),
            (_command("print('ok')"),),
            output=output,
            environment={"PATH": "/usr/bin"},
            timeout_seconds=10,
        )

    assert envelope["status"] == "NOT_RUN"
    assert envelope["exit_status"] is None
    assert envelope["exit_code"] is None
    assert any("provenance" in item for item in envelope["limitations"])


def test_checkout_mutation_cannot_claim_pass(tmp_path: Path) -> None:
    output = tmp_path / ".runtime/ci/fast.json"
    with patch.object(
        ci_lane_evidence,
        "capture_checkout",
        side_effect=[_checkout(), _checkout(fingerprint="d" * 64)],
    ):
        envelope = ci_lane_evidence.run_lane(
            tmp_path,
            "fast",
            ("architecture",),
            (_command("print('ok')"),),
            output=output,
            environment=_environment(),
            timeout_seconds=10,
        )

    assert envelope["status"] == "FAIL"
    assert envelope["exit_status"] == 1
    assert envelope["freshness"] == "INVALID_CHECKOUT"
    assert any("sentinel" in item for item in envelope["limitations"])


def test_timed_out_command_is_bounded_and_cannot_claim_pass(tmp_path: Path) -> None:
    output = tmp_path / ".runtime/ci/timeout.json"
    with patch.object(
        ci_lane_evidence,
        "capture_checkout",
        side_effect=[_checkout(), _checkout()],
    ):
        envelope = ci_lane_evidence.run_lane(
            tmp_path,
            "timeout",
            ("architecture",),
            (_command("import time; time.sleep(5)"),),
            output=output,
            environment=_environment(),
            timeout_seconds=1,
        )

    assert envelope["status"] == "FAIL"
    assert envelope["exit_status"] == 1
    assert envelope["commands"][0]["status"] == "FAIL"
    assert any("exceeded 1s" in item for item in envelope["limitations"])
