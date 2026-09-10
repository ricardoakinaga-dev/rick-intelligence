from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import time

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


@pytest.fixture
def local_runtime_contract(monkeypatch: pytest.MonkeyPatch):
    """Reuse the canonical runtime's queue double; this is not live evidence."""
    for relative in ("apps/worker", "packages/jobs/src", "packages/observability/src"):
        monkeypatch.syspath_prepend(str(ROOT / relative))
    name = "multi_worker_local_runtime_contract"
    spec = importlib.util.spec_from_file_location(name, ROOT / "apps/worker/tests/test_runtime.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_gate_cycle_uses_real_runtime_heartbeat_and_result(local_runtime_contract) -> None:
    contract = local_runtime_contract
    job = contract.Job.create(
        job_id="runtime-contract",
        tenant_id=contract.SCOPE.tenant_id,
        workspace_id=contract.SCOPE.workspace_id,
        collection_id=contract.SCOPE.collection_id,
        operation="runtime_multi_worker",
        idempotency_key="runtime-contract",
        payload={"source_ref": "runtime:contract"},
        now=time.time(),
    )
    queue = contract.FakeQueue([job.transition(contract.JobState.QUEUED, now=time.time())])

    observed = gate._run_runtime_cycle(queue, contract.SCOPE, str(job.job_id), "worker-contract", contract.JobResult)

    assert observed["runtime"] == "RealWorkerRuntime"
    assert observed["claimed"] is True
    assert observed["heartbeat"] is True
    assert observed["acked"] is True
    assert queue.heartbeat_calls >= 1
    assert len(queue.acknowledged) == 1
    assert queue.acknowledged[0][1].output_refs == {"publication_ref": "runtime-publication:runtime-contract"}


def test_idle_real_runtime_does_not_claim_heartbeat_or_ack(local_runtime_contract) -> None:
    contract = local_runtime_contract
    queue = contract.FakeQueue([])

    observed = gate._run_runtime_cycle(queue, contract.SCOPE, "runtime-contract", "worker-idle", contract.JobResult)

    assert observed["claimed"] is False
    assert observed["heartbeat"] is False
    assert observed["acked"] is False
    assert queue.acknowledged == []


def test_runtime_heartbeat_failure_cannot_report_publication(local_runtime_contract) -> None:
    contract = local_runtime_contract
    job = contract.Job.create(
        job_id="runtime-failed-heartbeat",
        tenant_id=contract.SCOPE.tenant_id,
        workspace_id=contract.SCOPE.workspace_id,
        collection_id=contract.SCOPE.collection_id,
        operation="runtime_multi_worker",
        idempotency_key="runtime-failed-heartbeat",
        payload={"source_ref": "runtime:contract"},
        now=time.time(),
    )
    queue = contract.FakeQueue([job.transition(contract.JobState.QUEUED, now=time.time())], heartbeat_error=True)

    with pytest.raises(RuntimeError, match="canonical worker execution failed"):
        gate._run_runtime_cycle(queue, contract.SCOPE, str(job.job_id), "worker-failure", contract.JobResult)

    assert queue.heartbeat_calls >= 1
    assert queue.acknowledged == []


@pytest.mark.parametrize("crash_point", ["after_claim", "after_heartbeat"])
def test_crash_injection_runs_inside_real_handler(local_runtime_contract, monkeypatch, crash_point):
    """Observe injection locally; os._exit is replaced, so this is not a crash proof."""
    contract = local_runtime_contract
    job = contract.job(operation="runtime_multi_worker", now=time.time())
    queue = contract.FakeQueue([job])
    messages = []
    exit_codes = []

    class Channel:
        closed = False

        def send(self, value):
            messages.append(value)

        def close(self):
            self.closed = True

    def terminate(code):
        exit_codes.append(code)
        raise SystemExit(code)

    channel = Channel()
    monkeypatch.setattr(gate.os, "_exit", terminate)

    with pytest.raises(RuntimeError, match="did not terminate at the requested point"):
        gate._run_crash_cycle(queue, contract.SCOPE, "worker-crash-test", channel, crash_point)

    assert exit_codes == [0]
    assert channel.closed is True
    assert len(messages) == 1
    assert messages[0]["runtime"] == "RealWorkerRuntime"
    assert messages[0]["crash_point"] == crash_point
    assert messages[0]["job_id"] == str(job.job_id)
    if crash_point == "after_heartbeat":
        assert queue.heartbeat_calls >= 1
        assert messages[0]["heartbeat_at"] > messages[0]["acquired_at"]
        assert messages[0]["expires_at"] == queue._leases[str(job.job_id)].expires_at
    else:
        assert queue.heartbeat_calls == 0
    assert queue.acknowledged == []


def test_partial_crash_coverage_does_not_claim_complete_production_safety(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "run_gate", lambda *_args, **_kwargs: (
        "PASS", [gate.GateResult(f"CRASH_{point.upper()}", "PASS") for point in gate.SUPPORTED_CRASH_POINTS]
    ))

    assert gate.main(["--database-url", "postgresql://localhost/test", "--output", "gate.json"]) == 0

    payload = json.loads((tmp_path / "gate.json").read_text())
    assert payload["runtime_claim"] is True
    assert payload["production_safe"] is False
    assert payload["crash_matrix_complete"] is False
    assert payload["crash_matrix"]["after_heartbeat"] == "PASS"
    assert payload["crash_matrix"]["in_transaction"] == "NOT_IMPLEMENTED"
    assert len(payload["crash_matrix"]) == 8


def test_failed_heartbeat_cannot_report_reaching_after_heartbeat_crash(local_runtime_contract, monkeypatch):
    contract = local_runtime_contract
    queue = contract.FakeQueue(
        [contract.job(operation="runtime_multi_worker", now=time.time())], heartbeat_error=True,
    )
    observations = []

    class Channel:
        def send(self, value):
            observations.append(value)

        def close(self):
            pass

    monkeypatch.setattr(gate.os, "_exit", lambda code: observations.append(code))

    with pytest.raises(RuntimeError, match="did not terminate at the requested point"):
        gate._run_crash_cycle(queue, contract.SCOPE, "worker-crash-failure", Channel(), "after_heartbeat")

    assert queue.heartbeat_calls >= 1
    assert observations == []
    assert queue.acknowledged == []
