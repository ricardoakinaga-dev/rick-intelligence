"""Focused tests for the explicit operational lane harness."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from scripts.state_of_art import phase3_lane


def _command(payload: dict[str, object], *, exit_code: int = 0) -> list[str]:
    source = (
        "import json,sys; "
        f"print(json.dumps({payload!r})); "
        f"sys.exit({exit_code})"
    )
    return [sys.executable, "-c", source]


def _observation(lane: str, **measurements: object) -> dict[str, object]:
    return {
        "schema_version": "rick-phase3-operational-observation.v1",
        "lane": lane,
        "status": "PASS",
        "runtime": {"disposable": True, "service": "phase3-test"},
        "budgets": {"timeout_seconds": 5, "requests": 1},
        "measurements": measurements,
    }


def test_missing_external_harness_is_blocked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RICK_PHASE3_PERFORMANCE_COMMAND", raising=False)
    artifact = phase3_lane.run_lane(
        tmp_path,
        "performance",
        output=tmp_path / "performance.json",
    )

    assert artifact["status"] == "BLOCKED_EXTERNAL"
    assert artifact["exit_status"] == 2


def test_structured_performance_observation_can_pass(tmp_path: Path) -> None:
    artifact = phase3_lane.run_lane(
        tmp_path,
        "performance",
        output=tmp_path / "performance.json",
        command=_command(_observation("performance", p95_ms=42.0, error_rate=0.0)),
        timeout_seconds=5,
    )

    assert artifact["status"] == "PASS"
    assert artifact["exit_status"] == 0
    assert artifact["observation"]["measurements"]["p95_ms"] == 42.0


def test_zero_exit_without_structured_pass_fails_closed(tmp_path: Path) -> None:
    artifact = phase3_lane.run_lane(
        tmp_path,
        "chaos",
        output=tmp_path / "chaos.json",
        command=_command({"status": "PASS"}),
        timeout_seconds=5,
    )

    assert artifact["status"] == "FAIL"
    assert artifact["exit_status"] == 1


def test_duplicate_status_keys_fail_closed(tmp_path: Path) -> None:
    raw = (
        b'{"schema_version":"rick-phase3-operational-observation.v1",'
        b'"lane":"performance","status":"FAIL","status":"PASS",'
        b'"runtime":{"disposable":true},"budgets":{"timeout_seconds":5},'
        b'"measurements":{"p95_ms":42}}'
    )

    status, observation, reason = phase3_lane._parse_observation(raw, "performance")

    assert status == "FAIL"
    assert observation == {}
    assert "valid JSON object" in reason


def test_chaos_requires_recovery_and_soak_requires_duration(tmp_path: Path) -> None:
    chaos = phase3_lane.run_lane(
        tmp_path,
        "chaos",
        output=tmp_path / "chaos.json",
        command=_command(_observation("chaos", recovered=False)),
        timeout_seconds=5,
    )
    soak = phase3_lane.run_lane(
        tmp_path,
        "soak",
        output=tmp_path / "soak.json",
        command=_command(_observation("soak", requests=3)),
        timeout_seconds=5,
    )

    assert chaos["status"] == "FAIL"
    assert soak["status"] == "FAIL"
