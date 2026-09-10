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


def test_runtime_fault_seam_exposes_distinct_handler_and_result_boundaries(local_runtime_contract) -> None:
    contract = local_runtime_contract
    job = contract.job(operation="runtime_multi_worker", now=time.time())
    queue = contract.FakeQueue([job])
    observed: list[tuple[str, str]] = []

    def inject(point, observed_job, lease):
        observed.append((point, str(observed_job.job_id)))
        assert lease.job_id == observed_job.job_id

    runtime = contract.RealWorkerRuntime(
        queue,
        worker_id="worker-fault-contract",
        scope=contract.SCOPE,
        handlers={"runtime_multi_worker": lambda _job, _lease, *, cancelled: contract.JobResult(
            output_refs={"publication_ref": "runtime-publication:fault-contract"},
            completed_at=time.time(),
        )},
        poll_interval_seconds=0.001,
        heartbeat_interval_seconds=10.0,
        handler_timeout_seconds=1.0,
        shutdown_timeout_seconds=1.0,
        fault_injector=inject,
    )
    try:
        runtime.start()
        result = runtime.run_once(wait=True)
    finally:
        runtime.shutdown(timeout=1.0)

    assert result.succeeded == 1
    assert [point for point, _job_id in observed] == ["during_handler", "before_result"]
    assert queue.acknowledged


def test_postgres_fault_seam_marks_transaction_after_lock_and_commit(local_runtime_contract) -> None:
    from postgres_jobs import PostgresJobError, PostgresJobQueue

    contract = local_runtime_contract

    class Cursor:
        def close(self):
            pass

    class Connection:
        commits = 0
        rollbacks = 0

        def cursor(self):
            return Cursor()

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            pass

    connection = Connection()
    observed: list[str] = []

    def injector(point):
        observed.append(point)
        if point == "in_transaction":
            raise RuntimeError("injected transaction crash")

    queue = PostgresJobQueue(lambda: connection, fault_injector=injector)
    queued = contract.job(operation="runtime_multi_worker", now=time.time())
    running = queued.start_attempt(worker_id="worker-fault-contract", now=time.time())
    lease = contract.JobLease(
        job_id=running.job_id,
        scope=running.scope,
        worker_id="worker-fault-contract",
        token="fault-token",
        acquired_at=time.time(),
        expires_at=time.time() + 30,
        heartbeat_at=time.time(),
    )
    queue._lock_lease = lambda *_args, **_kwargs: (None, running)

    with pytest.raises(PostgresJobError):
        queue.acknowledge(
            lease,
            contract.JobResult(output_refs={"publication_ref": "fault"}, completed_at=time.time()),
            now=time.time(),
            expected_version=running.version,
        )

    assert observed == ["in_transaction"]
    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_postgres_fault_seam_wraps_result_event_publication(local_runtime_contract, monkeypatch) -> None:
    from postgres_jobs import PostgresJobQueue

    contract = local_runtime_contract
    observed: list[str] = []
    queue = PostgresJobQueue(lambda: None, fault_injector=observed.append)
    queued = contract.job(operation="runtime_multi_worker", now=time.time())
    running = queued.start_attempt(worker_id="worker-fault-contract", now=time.time())
    completed_at = time.time()
    succeeded = running.finish_attempt(
        contract.JobState.SUCCEEDED,
        now=completed_at,
        result=contract.JobResult(output_refs={"publication_ref": "fault"}, completed_at=completed_at),
    )
    event_order: list[str] = []
    monkeypatch.setattr(PostgresJobQueue, "_execute", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(PostgresJobQueue, "_one", staticmethod(lambda *_args, **_kwargs: {}))
    monkeypatch.setattr(PostgresJobQueue, "_write_attempts", classmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(
        PostgresJobQueue,
        "_write_event",
        classmethod(lambda *_args, **_kwargs: event_order.append("event")),
    )
    monkeypatch.setattr(
        PostgresJobQueue,
        "_decode",
        classmethod(lambda _cls, _cursor, _row: succeeded),
    )

    queue._persist(
        object(),
        succeeded,
        expected_version=running.version,
        from_state=running.state,
        event_type="acknowledged",
    )

    assert observed == ["before_publish", "after_publish"]
    assert event_order == ["event"]


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
    monkeypatch.setattr(gate, "SUPPORTED_CRASH_POINTS", ("after_claim", "after_heartbeat"))
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
