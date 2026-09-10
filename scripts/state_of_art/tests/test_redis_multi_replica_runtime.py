from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[3]
SPEC = importlib.util.spec_from_file_location(
    "redis_multi_replica_runtime_gate",
    ROOT / "scripts/phase11/redis_multi_replica_runtime_gate.py",
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def test_missing_redis_url_is_blocked_without_runtime_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    output = tmp_path / "gate.json"

    assert gate.main(["--redis-url", "", "--output", "gate.json"]) == 2

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCKED_EXTERNAL"
    assert payload["runtime_claim"] is False
    assert payload["production_safe"] is False
    assert "required" in payload["results"][0]["detail"]


def test_non_loopback_redis_requires_explicit_authority() -> None:
    with pytest.raises(gate._BlockedExternal):  # noqa: SLF001
        gate.run_gate("redis://:secret@example.invalid/0")


def test_invalid_redis_url_is_rejected_without_echoing_configuration() -> None:
    with pytest.raises(gate._InvalidConfiguration):  # noqa: SLF001
        gate.run_gate("https://redis.example.invalid/0")


def test_two_replica_observations_prove_one_bucket_and_tenant_isolation() -> None:
    observations = [
        {
            "kind": "complete",
            "pid": 101,
            "replica": "api-a",
            "tenant_namespace": "tenant-fingerprint",
            "other_namespace": "other-fingerprint",
            "first": [True, False],
            "replay": False,
            "overflow": False,
            "other_tenant": True,
            "production_safe": False,
        },
        {
            "kind": "complete",
            "pid": 202,
            "replica": "api-b",
            "tenant_namespace": "tenant-fingerprint",
            "other_namespace": "other-fingerprint",
            "first": [False, True],
            "replay": True,
            "overflow": False,
            "other_tenant": True,
            "production_safe": False,
        },
    ]

    results, metrics, production_safe = gate._local_results(observations)  # noqa: SLF001

    assert all(item.result in {"PASS", "PARTIAL"} for item in results)
    assert metrics["distinct_processes"] is True
    assert metrics["shared_bucket_allowed"] == 2
    assert metrics["multi_replica_overflow_denied"] is True
    assert metrics["replay_consistent"] is True
    assert metrics["other_tenant_allowed"] == 2
    assert production_safe is False
    assert any(item.name == "RATE_LIMIT_MULTI_REPLICA_BYPASS_REJECTED" for item in results)


def test_bucket_bypass_is_failed_when_three_shared_requests_are_allowed() -> None:
    observations = [
        {
            "pid": 101,
            "replica": "api-a",
            "tenant_namespace": "same",
            "other_namespace": "other",
            "first": [True, True],
            "replay": True,
            "overflow": False,
            "other_tenant": True,
            "production_safe": False,
        },
        {
            "pid": 202,
            "replica": "api-b",
            "tenant_namespace": "same",
            "other_namespace": "other",
            "first": [True, False],
            "replay": True,
            "overflow": False,
            "other_tenant": True,
            "production_safe": False,
        },
    ]

    results, _metrics, _production_safe = gate._local_results(observations)  # noqa: SLF001

    bypass = next(item for item in results if item.name == "RATE_LIMIT_MULTI_REPLICA_BYPASS_REJECTED")
    assert bypass.result == "FAIL"


def test_gate_does_not_use_the_in_memory_rate_limiter() -> None:
    source = (ROOT / "scripts/phase11/redis_multi_replica_runtime_gate.py").read_text(encoding="utf-8")

    assert "InMemoryRateLimiter" not in source
    assert "get_context(\"spawn\")" in source
    assert "RedisRateLimiter" not in source  # composition goes through the package factory
