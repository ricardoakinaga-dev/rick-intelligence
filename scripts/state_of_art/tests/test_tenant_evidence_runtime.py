"""Hermetic contract tests for the tenant/evidence negative runtime gate."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from scripts.phase11 import tenant_evidence_runtime_gate as gate


def _runtime_module(path: Path, *, allow: bool = False, attest: bool = True) -> Path:
    path.write_text(
        """
class Runtime:
    authorized = True
    external = True
    production_safe = False

    async def preflight(self):
        return {"status": "ready"}

    async def run_negative_case(self, *, case, timeout_seconds):
        if ALLOW:
            return {"status": "allowed", "allowed": True}
        response = {"status": "blocked", "allowed": False, "evidence_count": 0, "citation_count": 0}
        if ATTEST:
            response.update({"metadata_leak_free": True, "timing_leak_free": True})
        return response

def create_runtime():
    return Runtime()
""".replace("ALLOW", repr(allow)).replace("ATTEST", repr(attest)),
        encoding="utf-8",
    )
    return path


def test_missing_runtime_authority_is_blocked(tmp_path: Path) -> None:
    payload = asyncio.run(gate.run_gate(output=str(tmp_path / "tenant.json"), root=tmp_path))

    assert payload["status"] == gate.BLOCKED_EXTERNAL
    assert payload["runtime_claim"] is False
    assert payload["case_count"] == 0


def test_external_runtime_must_reject_every_negative_case(tmp_path: Path) -> None:
    module = _runtime_module(tmp_path / "runtime.py")
    output = tmp_path / "tenant.json"
    payload = asyncio.run(
        gate.run_gate(str(module), output=str(output), root=tmp_path)
    )

    assert payload["status"] == gate.PASS
    assert payload["case_count"] == 16
    assert all(case["result"] == gate.PASS for case in payload["cases"])
    assert payload["production_safe"] is False


def test_metadata_and_timing_attestations_are_mandatory(tmp_path: Path) -> None:
    module = _runtime_module(tmp_path / "runtime.py", attest=False)
    payload = asyncio.run(
        gate.run_gate(str(module), output=str(tmp_path / "tenant.json"), root=tmp_path)
    )

    assert payload["status"] == gate.FAIL
    failed = {case["case_id"] for case in payload["cases"] if case["result"] == gate.FAIL}
    assert failed == gate._METADATA_CASE_IDS | gate._TIMING_CASE_IDS


def test_metadata_case_payloads_have_unique_probe_markers() -> None:
    payloads = [gate._case_payload(case_id, "run-123") for case_id in gate._CASE_IDS]
    metadata = [item for item in payloads if item["case_id"] in gate._METADATA_CASE_IDS | gate._TIMING_CASE_IDS]

    assert len(metadata) == 8
    markers = {item["mutation"]["probe_marker"] for item in metadata}
    assert len(markers) == len(metadata)


def test_accepted_negative_case_fails_closed(tmp_path: Path) -> None:
    module = _runtime_module(tmp_path / "runtime.py", allow=True)
    payload = asyncio.run(
        gate.run_gate(str(module), output=str(tmp_path / "tenant.json"), root=tmp_path)
    )

    assert payload["status"] == gate.FAIL
    assert any(case["result"] == gate.FAIL for case in payload["cases"])


def test_main_writes_a_safe_blocked_artifact_without_runtime_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    output = "tenant.json"

    assert gate.main(["--output", output]) == 2
    payload = json.loads((tmp_path / output).read_text(encoding="utf-8"))
    assert payload["status"] == gate.BLOCKED_EXTERNAL
    assert "credential" not in json.dumps(payload).lower()
