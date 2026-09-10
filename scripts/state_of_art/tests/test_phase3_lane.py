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
        "runtime": {
            "disposable": True,
            "service": "phase3-test",
            "baseline": {
                "hardware": "test-host",
                "container_limits": {"cpu": 2, "memory_bytes": 1_000_000_000},
                "dataset": "test-dataset-v1",
                "provider": "test-provider",
                "model": "test-model",
                "versions": {"app": "test"},
            },
        },
        "budgets": {"timeout_seconds": 5, "requests": 1},
        "measurements": measurements,
    }


def _performance_observation() -> dict[str, object]:
    results = []
    for workload in phase3_lane.PERFORMANCE_WORKLOADS:
        for concurrency in phase3_lane.PERFORMANCE_CONCURRENCY_LEVELS:
            results.append(
                {
                    "workload": workload,
                    "concurrency": concurrency,
                    "p50_ms": 10.0,
                    "p95_ms": 42.0,
                    "p99_ms": 50.0,
                    "throughput": 100.0,
                    "error_rate": 0.0,
                    "cpu_percent": 20.0,
                    "ram_bytes": 100_000_000,
                    "queue_depth": 0,
                }
            )
    return _observation("performance", results=results)


def _chaos_observation(*, failed_fault: str | None = None) -> dict[str, object]:
    faults = [
        {
            "fault": fault,
            **{assertion: fault != failed_fault for assertion in phase3_lane.CHAOS_ASSERTIONS},
        }
        for fault in phase3_lane.CHAOS_FAULTS
    ]
    return _observation("chaos", faults=faults)


def _soak_observation() -> dict[str, object]:
    profiles = []
    for profile in phase3_lane.SOAK_PROFILES:
        profiles.append(
            {
                "profile": profile,
                "memory_bytes": 100_000_000,
                "threads": 4,
                "processes": 2,
                "connections": 3,
                "queue_growth": 0,
                "latency_drift_ms": 1.0,
                "retry_storms": False,
                "worker_starvation": False,
                "file_descriptor_leaks": False,
            }
        )
    return _observation("soak", profiles=profiles)


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
        command=_command(_performance_observation()),
        timeout_seconds=5,
    )

    assert artifact["status"] == "PASS"
    assert artifact["exit_status"] == 0
    assert len(artifact["observation"]["measurements"]["results"]) == 20


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


def test_blocked_external_observation_does_not_claim_a_runtime_matrix() -> None:
    payload = _observation("performance")
    payload["status"] = "BLOCKED_EXTERNAL"
    status, observation, reason = phase3_lane._parse_observation(
        json.dumps(payload).encode(), "performance"
    )

    assert status == "BLOCKED_EXTERNAL"
    assert observation["status"] == "BLOCKED_EXTERNAL"
    assert reason == "approved structured runtime observation received"


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
        command=_command(_chaos_observation(failed_fault="kill-redis")),
        timeout_seconds=5,
    )
    soak = phase3_lane.run_lane(
        tmp_path,
        "soak",
        output=tmp_path / "soak.json",
        command=_command(_soak_observation()),
        timeout_seconds=5,
    )

    assert chaos["status"] == "FAIL"
    assert soak["status"] == "PASS"


def test_operational_observation_requires_full_chaos_and_soak_coverage() -> None:
    incomplete_performance = _performance_observation()
    incomplete_performance["measurements"]["results"].pop()  # type: ignore[index]
    performance_status, _, performance_reason = phase3_lane._parse_observation(
        json.dumps(incomplete_performance).encode(), "performance"
    )
    chaos_status, _, chaos_reason = phase3_lane._parse_observation(
        json.dumps(_chaos_observation()).encode(), "chaos"
    )
    soak_status, _, soak_reason = phase3_lane._parse_observation(
        json.dumps(_soak_observation()).encode(), "soak"
    )

    assert performance_status == "FAIL"
    assert performance_reason == "performance result matrix is incomplete"
    assert chaos_status == "PASS"
    assert soak_status == "PASS"
    assert chaos_reason == "approved structured runtime observation received"
    assert soak_reason == "approved structured runtime observation received"
