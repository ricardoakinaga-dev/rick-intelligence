"""Deterministic local tests for the isolated Phase 2.3 worker runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Event, Lock
import time

import pytest

from rick_jobs import Job, JobFailure, JobLease, JobResult, JobScope, JobState, WorkerId

from runtime import (
    OperationRegistry,
    RealWorkerRuntime,
    RuntimeConfigurationError,
    StartupValidationError,
    WorkerCancelled,
)
import runtime as runtime_module


SCOPE = JobScope("tenant-a", "workspace-a", "collection-a")


class LeaseLost(RuntimeError):
    code = "lease"


class ProviderFailure(RuntimeError):
    code = "provider_timeout"


@dataclass
class ManualClock:
    value: float = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += max(0.001, seconds)


class FakeQueue:
    """A local canonical queue seam; it never opens PostgreSQL."""

    lease_seconds = 30.0

    def __init__(self, jobs: list[Job], *, heartbeat_error: bool = False) -> None:
        self._jobs = {str(job.job_id): job for job in jobs}
        self._pending = [str(job.job_id) for job in jobs]
        self.claim_calls: list[tuple[int, float]] = []
        self.heartbeat_calls = 0
        self.acknowledged: list[tuple[str, JobResult]] = []
        self.failures: list[tuple[str, JobFailure]] = []
        self.cancel_lease_calls: list[str] = []
        self.heartbeat_error = heartbeat_error
        self.healthy = True
        self._leases: dict[str, JobLease] = {}
        self._lock = Lock()

    def health_check(self) -> bool:
        return self.healthy

    def get(
        self,
        job_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
    ) -> Job | None:
        job = self._jobs.get(str(job_id))
        if job is None or (job.tenant_id, job.workspace_id, job.collection_id) != (
            tenant_id,
            workspace_id,
            collection_id,
        ):
            return None
        return job

    def claim(
        self,
        *,
        worker_id: WorkerId,
        scope: JobScope,
        expected_versions: Mapping[str, int],
        limit: int,
        now: float,
    ) -> tuple[tuple[Job, JobLease], ...]:
        self.claim_calls.append((limit, now))
        selected: list[tuple[Job, JobLease]] = []
        with self._lock:
            while self._pending and len(selected) < limit:
                job_id = self._pending.pop(0)
                job = self._jobs[job_id]
                assert expected_versions[job.job_id] == job.version
                running = job.start_attempt(worker_id=worker_id, now=max(now, job.updated_at))
                token = f"lease-{job_id}"
                lease = JobLease(
                    job_id=running.job_id,
                    scope=scope,
                    worker_id=worker_id,
                    token=token,
                    acquired_at=now,
                    expires_at=now + self.lease_seconds,
                    heartbeat_at=now,
                )
                self._jobs[job_id] = running
                self._leases[job_id] = lease
                selected.append((running, lease))
        return tuple(selected)

    def heartbeat(self, lease: JobLease, *, now: float, expected_version: int) -> JobLease:
        self.heartbeat_calls += 1
        if self.heartbeat_error:
            raise LeaseLost("simulated lease loss")
        current = self._leases[str(lease.job_id)]
        assert expected_version == self._jobs[str(lease.job_id)].version
        renewed = JobLease(
            job_id=current.job_id,
            scope=current.scope,
            worker_id=current.worker_id,
            token=current.token,
            acquired_at=current.acquired_at,
            expires_at=now + self.lease_seconds,
            heartbeat_at=now,
        )
        self._leases[str(lease.job_id)] = renewed
        return renewed

    def acknowledge(
        self,
        lease: JobLease,
        result: JobResult,
        *,
        now: float,
        expected_version: int,
        deadline: float | None = None,
    ) -> Job:
        job_id = str(lease.job_id)
        job = self._jobs[job_id]
        assert expected_version == job.version
        assert self._leases[job_id].token == lease.token
        completed = job.finish_attempt(
            JobState.SUCCEEDED,
            now=max(now, job.updated_at),
            result=result,
        )
        self._jobs[job_id] = completed
        self.acknowledged.append((job_id, result))
        return completed

    def fail(
        self,
        lease: JobLease,
        failure: JobFailure,
        *,
        now: float,
        expected_version: int,
    ) -> Job:
        job_id = str(lease.job_id)
        job = self._jobs[job_id]
        assert expected_version == job.version
        failed = job.finish_attempt(
            JobState.FAILED,
            now=max(now, job.updated_at),
            failure=failure,
        )
        self._jobs[job_id] = failed
        self.failures.append((job_id, failure))
        return failed

    def cancel_lease(self, lease: JobLease, *, now: float, expected_version: int) -> Job:
        job_id = str(lease.job_id)
        job = self._jobs[job_id]
        assert expected_version == job.version
        cancelled = job.finish_attempt(JobState.CANCELLED, now=max(now, job.updated_at))
        self._jobs[job_id] = cancelled
        self.cancel_lease_calls.append(job_id)
        return cancelled


def job(
    *,
    operation: str = "ingest",
    payload: Mapping[str, str] | None = None,
    now: float = 100.0,
    suffix: str = "1",
) -> Job:
    identity = f"{operation.replace('.', '-')}-{suffix}"
    created = Job.create(
        job_id=f"job-{identity}",
        tenant_id=SCOPE.tenant_id,
        workspace_id=SCOPE.workspace_id,
        collection_id=SCOPE.collection_id,
        operation=operation,
        idempotency_key=f"idem-{identity}",
        payload=payload or {"source_key": "objects/input.txt"},
        now=now,
    )
    return created.transition(JobState.QUEUED, now=now)


def yielding_sleep(clock: ManualClock) -> Callable[[float], None]:
    def sleep(seconds: float) -> None:
        clock.advance(seconds)
        time.sleep(0)

    return sleep


def make_runtime(
    queue: FakeQueue,
    clock: ManualClock,
    handler: Callable[..., JobResult],
    **overrides: object,
) -> RealWorkerRuntime:
    values: dict[str, object] = {
        "queue": queue,
        "worker_id": "worker-a",
        "scope": SCOPE,
        "handlers": {"ingest": handler},
        "clock": clock,
        "sleep_fn": yielding_sleep(clock),
        "poll_interval_seconds": 0.001,
        "handler_timeout_seconds": 1.0,
        "heartbeat_interval_seconds": 10.0,
        "shutdown_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return RealWorkerRuntime(**values)  # type: ignore[arg-type]


def success(_job: Job, _lease: JobLease, *, cancelled) -> JobResult:
    cancelled.checkpoint()
    return JobResult(
        output_refs={"object_key": "objects/output.txt"},
        document_id="doc-1",
        completed_at=_job.updated_at,
    )


def test_worker_execution_uses_flat_w3c_trace_context_without_persisting_baggage(monkeypatch):
    from contextlib import contextmanager

    observed: dict[str, object] = {}

    @contextmanager
    def fake_attach(carrier):
        observed["carrier"] = carrier
        yield

    @contextmanager
    def fake_span(name, **kwargs):
        observed["span"] = (name, kwargs)
        yield None

    monkeypatch.setattr(runtime_module, "attach_trace_context", fake_attach)
    monkeypatch.setattr(runtime_module, "stage_span", fake_span)
    worker_job = job(
        payload={
            "source_key": "objects/input.txt",
            "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
            "tracestate": "vendor=value",
        }
    )
    queue = FakeQueue([worker_job])
    runtime = make_runtime(queue, ManualClock(), success)

    result = runtime.run_once()

    assert result.succeeded == 1
    assert observed["carrier"] == {
        "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
        "tracestate": "vendor=value",
    }
    assert observed["span"][0] == "worker.ingestion"


def test_registry_and_startup_reject_invalid_composition() -> None:
    registry = OperationRegistry()
    with pytest.raises(RuntimeConfigurationError):
        registry.register("invalid operation", success)
    with pytest.raises(RuntimeConfigurationError):
        registry.register("ingest", object())  # type: ignore[arg-type]
    registry.register("ingest", success)
    with pytest.raises(RuntimeConfigurationError):
        registry.register("ingest", success)

    queue = FakeQueue([])
    runtime = RealWorkerRuntime(
        queue,
        worker_id="worker-a",
        scope=SCOPE,
        handlers={},
        clock=ManualClock(),
        sleep_fn=lambda _seconds: None,
    )
    with pytest.raises(StartupValidationError) as raised:
        runtime.start()
    assert "handlers_empty" in raised.value.errors

    unhealthy = FakeQueue([])
    unhealthy.healthy = False
    runtime = make_runtime(unhealthy, ManualClock(), success)
    with pytest.raises(StartupValidationError) as raised:
        runtime.start()
    assert raised.value.errors == ("queue_unavailable",)


def test_backpressure_caps_claims_and_active_handlers() -> None:
    clock = ManualClock()
    queue = FakeQueue([
        job(now=clock.value, suffix="1"),
        job(operation="ingest", now=clock.value, suffix="2"),
        job(operation="ingest", now=clock.value, suffix="3"),
    ])
    started = Event()
    release = Event()
    active = 0
    maximum = 0
    active_lock = Lock()

    def handler(_job: Job, _lease: JobLease, *, cancelled) -> JobResult:
        nonlocal active, maximum
        with active_lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                started.set()
        while not release.is_set():
            cancelled.checkpoint()
            time.sleep(0)
        with active_lock:
            active -= 1
        return success(_job, _lease, cancelled=cancelled)

    runtime = make_runtime(queue, clock, handler, max_concurrency=2)
    try:
        first = runtime.run_once(wait=False)
        assert first.claimed == 2
        assert started.wait(1)
        second = runtime.run_once(wait=False)
        assert second.backpressured is True
        assert second.claimed == 0
        assert queue.claim_calls[-1][0] == 2

        release.set()
        assert runtime.wait_for_idle(timeout=1)
        third = runtime.run_once(wait=True)
        assert third.claimed == 1
        assert third.succeeded == 1
        assert maximum <= 2
        assert runtime.metrics().max_active == 2
    finally:
        release.set()
        runtime.shutdown(timeout=1)


def test_cancellation_is_cooperative_and_never_acks_late() -> None:
    clock = ManualClock()
    queue = FakeQueue([job(now=clock.value)])
    started = Event()

    def handler(_job: Job, _lease: JobLease, *, cancelled) -> JobResult:
        started.set()
        while not cancelled():
            time.sleep(0)
        cancelled.checkpoint()
        raise AssertionError("checkpoint must cancel")

    runtime = make_runtime(queue, clock, handler)
    try:
        runtime.run_once(wait=False)
        assert started.wait(1)
        assert runtime.cancel("job-ingest-1") is True
        assert runtime.wait_for_idle(timeout=1)
        assert queue.cancel_lease_calls == ["job-ingest-1"]
        assert queue.acknowledged == []
        assert queue.failures == []
        assert runtime.metrics().cancelled == 1
    finally:
        runtime.shutdown(timeout=1)


def test_handler_timeout_maps_to_safe_failure_and_keeps_thread_bounded() -> None:
    clock = ManualClock()
    queue = FakeQueue([job(now=clock.value)])
    started = Event()
    release = Event()

    def handler(_job: Job, _lease: JobLease, *, cancelled) -> JobResult:
        started.set()
        release.wait(1)
        cancelled.checkpoint()
        return success(_job, _lease, cancelled=cancelled)

    runtime = make_runtime(queue, clock, handler, handler_timeout_seconds=0.01)
    try:
        result = runtime.run_once(wait=True)
        assert started.is_set()
        assert result.failed == 1
        assert result.timed_out == 1
        assert queue.failures[-1][1].code == "handler_timeout"
        assert "secret" not in repr(queue.failures[-1])
        release.set()
        assert runtime.wait_for_idle(timeout=1)
    finally:
        release.set()
        runtime.shutdown(timeout=1)


def test_handler_completion_after_deadline_is_still_a_timeout() -> None:
    clock = ManualClock()
    queue = FakeQueue([job(now=clock.value)])
    started = Event()
    release = Event()

    def handler(_job: Job, _lease: JobLease, *, cancelled) -> JobResult:
        started.set()
        release.wait(1)
        return success(_job, _lease, cancelled=cancelled)

    runtime = make_runtime(queue, clock, handler, handler_timeout_seconds=0.01)
    try:
        runtime.run_once(wait=False)
        assert started.wait(1)
        clock.advance(1.0)
        release.set()
        assert runtime.wait_for_idle(timeout=1)
        assert queue.acknowledged == []
        assert queue.failures[-1][1].code == "handler_timeout"
    finally:
        release.set()
        runtime.shutdown(timeout=1)


def test_heartbeat_lease_loss_cancels_without_ack_or_fail() -> None:
    clock = ManualClock()
    queue = FakeQueue([job(now=clock.value)], heartbeat_error=True)

    def handler(_job: Job, _lease: JobLease, *, cancelled) -> JobResult:
        while not cancelled():
            time.sleep(0)
        return success(_job, _lease, cancelled=cancelled)

    runtime = make_runtime(queue, clock, handler, heartbeat_interval_seconds=0.01)
    try:
        result = runtime.run_once(wait=True)
        assert result.lease_lost == 1
        assert queue.heartbeat_calls >= 1
        assert queue.acknowledged == []
        assert queue.failures == []
        assert runtime.metrics().lease_lost == 1
    finally:
        runtime.shutdown(timeout=1)


def test_payload_limit_turns_an_oversized_claim_into_a_poison_failure() -> None:
    clock = ManualClock()
    queue = FakeQueue([job(now=clock.value, payload={"source_key": "x" * 100})])
    runtime = make_runtime(queue, clock, success, max_payload_bytes=32)
    try:
        result = runtime.run_once()
        assert result.poisoned == 1
        assert result.failed == 1
        assert queue.failures[-1][1].code == "payload_too_large"
    finally:
        runtime.shutdown(timeout=1)


def test_poison_and_handler_errors_use_safe_error_mapping() -> None:
    clock = ManualClock()
    poison_queue = FakeQueue([job(operation="unregistered", now=clock.value)])
    events: list[dict[str, object]] = []
    poison_runtime = make_runtime(
        poison_queue,
        clock,
        success,
        event_sink=lambda event: events.append(event),
    )
    try:
        result = poison_runtime.run_once()
        assert result.poisoned == 1
        assert result.failed == 1
        assert poison_queue.failures[-1][1].code == "unknown_operation"
        assert all("job-unregistered" not in repr(event) for event in events)
    finally:
        poison_runtime.shutdown(timeout=1)

    error_queue = FakeQueue([job(now=clock.value)])

    def broken(_job: Job, _lease: JobLease, *, cancelled) -> JobResult:
        raise ProviderFailure("provider secret should not cross the boundary")

    error_runtime = make_runtime(error_queue, clock, broken)
    try:
        result = error_runtime.run_once()
        assert result.failed == 1
        assert error_queue.failures[-1][1].code == "provider_timeout"
        assert error_queue.failures[-1][1].message == "The provider operation timed out."
        assert "secret" not in repr(error_queue.failures[-1])
    finally:
        error_runtime.shutdown(timeout=1)


def test_shutdown_requests_cancellation_with_a_finite_deadline() -> None:
    clock = ManualClock()
    queue = FakeQueue([job(now=clock.value)])
    started = Event()

    def handler(_job: Job, _lease: JobLease, *, cancelled) -> JobResult:
        started.set()
        while not cancelled():
            time.sleep(0)
        raise WorkerCancelled()

    runtime = make_runtime(queue, clock, handler, shutdown_timeout_seconds=0.2)
    runtime.run_once(wait=False)
    assert started.wait(1)

    report = runtime.shutdown(timeout=0.2)
    assert report.drained is True
    assert report.timed_out is False
    assert report.cancelled == 1
    assert report.active == 0
    assert runtime.readiness().ready is False
    assert runtime.liveness().live is False
    with pytest.raises(RuntimeError):
        runtime.run_once()
