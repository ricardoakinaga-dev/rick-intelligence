"""Hermetic contract tests for the file-security runtime gate."""

from __future__ import annotations

import json
from pathlib import Path
import textwrap
import time

import pytest

from scripts.phase11 import file_security_runtime_gate as gate
from scripts.state_of_art import run_phase3_file_security as adapter


def _write_runtime(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "external_file_security_runtime.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


_VALID_RUNTIME = """
AUTHORIZED = True
EXTERNAL = True


class Runtime:
    authorized = True
    external = True
    production_safe = False

    def preflight(self, timeout_seconds=None):
        return {
            "status": "READY",
            "process_isolated": True,
            "hard_timeout": True,
            "resource_limits_applied": True,
            "output_bounded": True,
            "payloads_ephemeral": True,
        }

    def run_case(self, case, timeout_seconds=None, limits=None):
        return {
            "case_id": case["case_id"],
            "blocked": True,
            "allowed": False,
            "status": "REJECTED",
            "payload_persisted": False,
            "secret_leak": False,
            "process_isolated": True,
            "resource_limits_applied": True,
            "output_bounded": True,
            "time_bounded": True,
            "case_executed": True,
            "probe_materialized": True,
            "timed_out": case["case_id"] == "parser-hang",
            "terminated": case["case_id"] == "parser-hang",
            "output_bytes": 0,
            "duration_ms": 2.0,
        }


def create_runtime(run_id=None, timeout_seconds=None):
    return Runtime()
"""


def _run_main(tmp_path: Path, runtime_path: Path | None, *extra: str) -> tuple[int, dict[str, object]]:
    output = tmp_path / "report.json"
    args = ["--root", str(tmp_path), "--output", str(output), "--timeout-seconds", "1"]
    if runtime_path is not None:
        args.extend(("--runtime-path", str(runtime_path)))
    args.extend(extra)
    code = gate.main(args)
    return code, json.loads(output.read_text(encoding="utf-8"))


def test_missing_external_authority_is_blocked_and_runs_no_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RICK_FILE_SECURITY_RUNTIME_PATH", raising=False)

    code, report = _run_main(tmp_path, None)

    assert code == 2
    assert report["status"] == gate.BLOCKED_EXTERNAL
    assert report["runtime_claim"] is False
    assert report["cases"] == []
    assert report["required_case_count"] == 10


def test_unauthorized_composition_cannot_be_promoted(tmp_path: Path) -> None:
    runtime_path = _write_runtime(
        tmp_path,
        """
        AUTHORIZED = True
        EXTERNAL = False
        def create_runtime():
            return object()
        """,
    )

    code, report = _run_main(tmp_path, runtime_path)

    assert code == 2
    assert report["status"] == gate.BLOCKED_EXTERNAL
    assert report["cases"] == []
    assert report["runtime_claim"] is False
    assert report["preflight"] == {}


def test_preflight_requires_all_isolation_and_bound_attestations(tmp_path: Path) -> None:
    runtime_path = _write_runtime(
        tmp_path,
        """
        AUTHORIZED = True
        EXTERNAL = True
        class Runtime:
            authorized = True
            external = True
            def preflight(self):
                return {"status": "READY", "process_isolated": True}
            def run_case(self, case):
                return {}
        def create_runtime():
            return Runtime()
        """,
    )

    code, report = _run_main(tmp_path, runtime_path)

    assert code == 1
    assert report["status"] == gate.FAIL
    assert report["cases"] == []
    assert report["preflight"]["process_isolated"] is True


def test_authorized_external_composition_passes_all_mandatory_cases(tmp_path: Path) -> None:
    runtime_path = _write_runtime(tmp_path, _VALID_RUNTIME)

    code, report = _run_main(tmp_path, runtime_path)

    assert code == 0
    assert report["status"] == gate.PASS
    assert report["runtime_claim"] is True
    assert report["production_safe"] is False
    assert [case["case_id"] for case in report["cases"]] == list(gate.CASE_IDS)
    assert all(case["result"] == gate.PASS for case in report["cases"])
    assert report["limits"]["worker_process_isolation"] is True
    assert report["limits"]["payload_bytes_persisted_by_gate"] is False


def test_secret_or_payload_persistence_claim_fails_without_retaining_marker(tmp_path: Path) -> None:
    secret = "DO-NOT-PERSIST-file-security-secret"
    runtime_path = _write_runtime(
        tmp_path,
        f"""
        AUTHORIZED = True
        EXTERNAL = True
        class Runtime:
            authorized = True
            external = True
            def preflight(self):
                return {{
                    "status": "READY", "process_isolated": True,
                    "hard_timeout": True, "resource_limits_applied": True,
                    "output_bounded": True, "payloads_ephemeral": True,
                }}
            def run_case(self, case):
                return {{
                    "case_id": case["case_id"],
                    "blocked": True, "allowed": False, "status": "REJECTED",
                    "payload_persisted": True, "secret_leak": True,
                    "detail": "{secret}", "process_isolated": True,
                    "resource_limits_applied": True, "output_bounded": True,
                    "time_bounded": True, "output_bytes": 1, "duration_ms": 1,
                }}
        def create_runtime():
            return Runtime()
        """,
    )

    code, report = _run_main(tmp_path, runtime_path)
    persisted = json.dumps(report, ensure_ascii=False)

    assert code == 1
    assert report["status"] == gate.FAIL
    assert all(case["result"] == gate.FAIL for case in report["cases"])
    assert secret not in persisted
    assert all("detail" not in case["observed"] if "observed" in case else True for case in report["cases"])


def test_hanging_external_case_is_killed_and_not_accepted(tmp_path: Path) -> None:
    runtime_path = _write_runtime(
        tmp_path,
        """
        AUTHORIZED = True
        EXTERNAL = True
        import time
        class Runtime:
            authorized = True
            external = True
            def preflight(self):
                return {
                    "status": "READY", "process_isolated": True,
                    "hard_timeout": True, "resource_limits_applied": True,
                    "output_bounded": True, "payloads_ephemeral": True,
                }
            def run_case(self, case):
                if case["case_id"] == "parser-hang":
                    time.sleep(2)
                return {
                    "case_id": case["case_id"],
                    "blocked": True, "allowed": False, "status": "REJECTED",
                    "payload_persisted": False, "secret_leak": False,
                    "process_isolated": True, "resource_limits_applied": True,
                    "output_bounded": True, "time_bounded": True,
                    "output_bytes": 0, "duration_ms": 1,
                }
        def create_runtime():
            return Runtime()
        """,
    )
    started = time.monotonic()

    code, report = _run_main(tmp_path, runtime_path, "--timeout-seconds", "1")

    assert time.monotonic() - started < 8
    assert code == 1
    assert report["status"] == gate.FAIL
    hang_case = next(case for case in report["cases"] if case["case_id"] == "parser-hang")
    assert hang_case["result"] == gate.FAIL


def test_unbounded_worker_stdout_is_terminated_and_fails_closed(tmp_path: Path) -> None:
    runtime_path = _write_runtime(
        tmp_path,
        f"""
        AUTHORIZED = True
        EXTERNAL = True
        import os
        class Runtime:
            authorized = True
            external = True
            def preflight(self):
                os.write(1, b'x' * ({gate.MAX_WORKER_OUTPUT_BYTES} + 1))
                return {{
                    "status": "READY", "process_isolated": True,
                    "hard_timeout": True, "resource_limits_applied": True,
                    "output_bounded": True, "payloads_ephemeral": True,
                }}
            def run_case(self, case):
                return {{}}
        def create_runtime():
            return Runtime()
        """,
    )

    code, report = _run_main(tmp_path, runtime_path)

    assert code == 1
    assert report["status"] == gate.FAIL
    assert report["cases"] == []


def test_adapter_emits_commit_bound_envelope_without_editing_gate_output_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_path = _write_runtime(tmp_path, _VALID_RUNTIME)
    monkeypatch.setattr(adapter, "ROOT", tmp_path)
    monkeypatch.setattr(adapter, "capture_checkout", lambda _root: {
        "available": True,
        "head": "a" * 40,
        "tree": "b" * 40,
        "fingerprint": "c" * 64,
        "status": "CLEAN",
        "errors": [],
    })

    envelope = adapter.run(
        tmp_path,
        output="evidence.json",
        argv=("--runtime-path", str(runtime_path), "--timeout-seconds", "1"),
    )

    assert envelope["status"] == gate.PASS
    assert envelope["capability_id"] == adapter.CAPABILITY_ID
    assert envelope["production_safe"] is False
    assert (tmp_path / "evidence.json").is_file()
    raw = json.dumps(envelope)
    assert "DO-NOT-PERSIST" not in raw
