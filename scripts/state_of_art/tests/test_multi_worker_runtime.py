from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[3]
SPEC = importlib.util.spec_from_file_location(
    "multi_worker_runtime_gate",
    ROOT / "scripts/phase11/multi_worker_runtime_gate.py",
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def test_missing_database_is_blocked_without_runtime_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    output = tmp_path / "gate.json"

    assert gate.main(["--output", "gate.json"]) == 2

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCKED_EXTERNAL"
    assert payload["runtime_claim"] is False
    assert payload["production_safe"] is False
    assert "required" in payload["results"][0]["detail"]


def test_non_loopback_database_requires_explicit_authority() -> None:
    try:
        gate.run_gate("postgresql://user:secret@example.invalid/db")
    except ValueError as error:
        assert "non-loopback" in str(error)
        assert "secret" not in str(error)
    else:
        raise AssertionError("non-loopback DSN should be rejected without authority")


def test_worker_gate_contains_no_legacy_ack_alias() -> None:
    source = (ROOT / "scripts/phase11/multi_worker_runtime_gate.py").read_text(encoding="utf-8")

    assert ".ack(" not in source
    assert ".acknowledge(" in source


def test_worker_gate_names_every_mandatory_fencing_case() -> None:
    source = (ROOT / "scripts/phase11/multi_worker_runtime_gate.py").read_text(encoding="utf-8")
    for case in (
        "STALE_WORKER_ACK_REJECTED",
        "STALE_WORKER_PUBLISH_REJECTED",
        "DUPLICATE_PUBLICATION_REJECTED",
        "LEASE_RECLAIM_AFTER_EXPIRY",
        "CRASH_RECOVERY_SUCCEEDS",
    ):
        assert case in source
