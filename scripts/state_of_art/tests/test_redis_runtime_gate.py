from __future__ import annotations

from pathlib import Path


def test_redis_runtime_gate_declares_recovery_and_fault_authority() -> None:
    source = (Path(__file__).parents[2] / "phase11" / "redis_runtime_gate.py").read_text(
        encoding="utf-8"
    )

    for case in ("heartbeat-renewal", "reconnect-recovery", "circuit-breaker-recovery"):
        assert case in source
    assert "RICK_REDIS_FAULT_HARNESS" in source
