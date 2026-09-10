from __future__ import annotations

from dataclasses import replace
import json

import pytest

from rick_jobs import (
    Job,
    JobAttempt,
    JobFailure,
    JobIdempotencyConflictError,
    JobLease,
    JobResult,
    JobScope,
    JobState,
    InvalidTransitionError,
    JobValidationError,
    can_transition,
    ensure_idempotent,
    idempotency_identity,
)


def make_job(**overrides: object) -> Job:
    values: dict[str, object] = {
        "job_id": "job-1",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "collection_id": "collection-a",
        "operation": "ingest",
        "idempotency_key": "idem-1",
        "payload": {"source_key": "objects/one.txt", "filename": "one.txt"},
        "now": 100.0,
    }
    values.update(overrides)
    return Job.create(**values)  # type: ignore[arg-type]


def queued_job(**overrides: object) -> Job:
    return make_job(**overrides).transition(JobState.QUEUED, now=101.0)


def active_job(**overrides: object) -> Job:
    return queued_job(**overrides).start_attempt(worker_id="worker-a", now=102.0)


def failure(*, attempt: int = 1, retryable: bool = True, occurred_at: float = 103.0) -> JobFailure:
    return JobFailure(
        code="provider_timeout",
        message="provider timed out",
        retryable=retryable,
        attempt=attempt,
        occurred_at=occurred_at,
    )


def test_state_vocabulary_and_terminal_behavior_are_explicit() -> None:
    assert {state.value for state in JobState} == {
        "PENDING", "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "RETRYING", "DEAD_LETTER"
    }
    assert JobState.SUCCEEDED.terminal
    assert JobState.CANCELLED.terminal
    assert JobState.DEAD_LETTER.terminal
    assert not JobState.RETRYING.terminal
    assert can_transition(JobState.PENDING, JobState.QUEUED)
    assert not can_transition(JobState.SUCCEEDED, JobState.QUEUED)
    assert not can_transition(JobState.RUNNING, JobState.RETRYING)


@pytest.mark.parametrize("operation", ["bad operation", "bad/operation", "", "x" * 65])
def test_operation_uses_the_runtime_identifier_grammar(operation: str) -> None:
    with pytest.raises(JobValidationError):
        make_job(operation=operation)


def test_payload_allows_only_bounded_w3c_trace_identity_fields() -> None:
    traceparent = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    job = make_job(payload={"source_key": "objects/one.txt", "traceparent": traceparent, "tracestate": "vendor=value"})
    assert job.payload["traceparent"] == traceparent
    assert job.payload["tracestate"] == "vendor=value"
    with pytest.raises(JobValidationError):
        make_job(payload={"source_key": "objects/one.txt", "baggage": "password=secret"})


def test_attempt_lifecycle_is_explicit_and_serialized() -> None:
    job = queued_job()
    running = job.start_attempt(worker_id="worker-a", now=102.0)
    assert running.state is JobState.RUNNING
    assert running.attempt_count == 1
    assert running.attempts[-1].state is JobState.RUNNING

    result = JobResult(output_refs={"object_key": "objects/one.txt"}, document_id="doc-1", completed_at=103.0)
    succeeded = running.finish_attempt(JobState.SUCCEEDED, now=103.0, result=result)
    assert succeeded.state is JobState.SUCCEEDED
    assert succeeded.result == result
    assert succeeded.attempts[-1].state is JobState.SUCCEEDED
    assert succeeded.version == 4
    serialized = json.loads(succeeded.to_json())
    assert serialized["attempt_count"] == 1
    assert serialized["attempts"][0]["state"] == "SUCCEEDED"
    assert serialized["attempts"][0]["finished_at"] == 103.0

    with pytest.raises(InvalidTransitionError):
        succeeded.transition(JobState.QUEUED, now=104.0)
    with pytest.raises(InvalidTransitionError):
        running.finish_attempt(JobState.SUCCEEDED, now=103.0)
    with pytest.raises(InvalidTransitionError):
        queued_job().transition(JobState.RUNNING, now=102.0)


def test_failed_transitions_require_failure_and_retry_policy() -> None:
    running = active_job(max_attempts=2)
    with pytest.raises(InvalidTransitionError):
        running.transition(JobState.FAILED, now=103.0)

    failed = running.finish_attempt(JobState.FAILED, now=103.0, failure=failure())
    assert failed.state is JobState.FAILED
    assert failed.failure == failed.attempts[-1].failure
    retrying = failed.transition(JobState.RETRYING, now=104.0)
    queued = retrying.transition(JobState.QUEUED, now=105.0)
    retried = queued.start_attempt(worker_id="worker-b", now=106.0)
    assert retried.attempt_count == 2
    assert retried.failure is None

    non_retryable = active_job(max_attempts=3).finish_attempt(
        JobState.FAILED,
        now=103.0,
        failure=failure(retryable=False),
    )
    with pytest.raises(InvalidTransitionError):
        non_retryable.transition(JobState.RETRYING, now=104.0)


def test_retry_limit_and_dead_letter_failure_are_explicit() -> None:
    failed = active_job(max_attempts=1).finish_attempt(JobState.FAILED, now=103.0, failure=failure())
    with pytest.raises(InvalidTransitionError):
        failed.transition(JobState.RETRYING, now=104.0)
    dead = failed.transition(JobState.DEAD_LETTER, now=104.0, failure=failed.failure)
    assert dead.state is JobState.DEAD_LETTER
    assert dead.failure == failure()


def test_constructor_rejects_impossible_execution_states() -> None:
    with pytest.raises(JobValidationError):
        Job(
            job_id="job-1",
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            collection_id="collection-a",
            operation="ingest",
            idempotency_key="idem-1",
            payload={"source_key": "objects/one.txt"},
            state=JobState.RUNNING,
            created_at=100.0,
            updated_at=100.0,
        )
    with pytest.raises(JobValidationError):
        Job(
            job_id="job-1",
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            collection_id="collection-a",
            operation="ingest",
            idempotency_key="idem-1",
            payload={"source_key": "objects/one.txt"},
            state=JobState.FAILED,
            failure=failure(),
            created_at=100.0,
            updated_at=103.0,
        )

    failed = active_job(max_attempts=2).finish_attempt(JobState.FAILED, now=103.0, failure=failure())
    with pytest.raises(JobValidationError):
        replace(failed, state=JobState.RETRYING, max_attempts=1, updated_at=104.0)
    with pytest.raises(JobValidationError):
        replace(
            failed,
            failure=JobFailure(
                code="other_error",
                message="different failure",
                retryable=True,
                attempt=1,
                occurred_at=103.0,
            ),
            updated_at=104.0,
        )
    with pytest.raises(JobValidationError):
        replace(failed, state=JobState.QUEUED, max_attempts=1, failure=None, updated_at=104.0)
    exhausted_non_retryable = active_job(max_attempts=2).finish_attempt(
        JobState.FAILED,
        now=103.0,
        failure=failure(retryable=False),
    )
    with pytest.raises(JobValidationError):
        replace(exhausted_non_retryable, state=JobState.QUEUED, failure=None, updated_at=104.0)

    succeeded = active_job().finish_attempt(
        JobState.SUCCEEDED,
        now=103.0,
        result=JobResult(output_refs={"object_key": "objects/one.txt"}, document_id="doc-1", completed_at=103.0),
    )
    with pytest.raises(JobValidationError):
        replace(succeeded, state=JobState.CANCELLED, result=None, updated_at=104.0)
    with pytest.raises(JobValidationError):
        replace(
            succeeded,
            result=JobResult(output_refs={"object_key": "objects/one.txt"}, document_id="doc-1", completed_at=104.0),
            updated_at=104.0,
        )
    with pytest.raises(JobValidationError):
        JobAttempt(1, "worker-a", JobState.FAILED, 102.0, 103.0, failure(occurred_at=104.0))
    with pytest.raises(JobValidationError):
        JobAttempt(1, None, JobState.RUNNING, 102.0)
    with pytest.raises(JobValidationError):
        JobAttempt(1, "worker-a", JobState.FAILED, 102.0, 103.0, failure(occurred_at=101.0))
    with pytest.raises(JobValidationError):
        replace(
            succeeded,
            result=JobResult(output_refs={"object_key": "objects/one.txt"}, document_id="doc-1", completed_at=101.0),
            updated_at=103.0,
        )
    with pytest.raises(JobValidationError):
        Job(
            job_id="job-1",
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            collection_id="collection-a",
            operation="ingest",
            idempotency_key="idem-1",
            payload={"source_key": "objects/one.txt"},
            state=JobState.RUNNING,
            attempts=(
                JobAttempt(1, "worker-a", JobState.FAILED, 100.0, 103.0, failure()),
                JobAttempt(2, "worker-b", JobState.RUNNING, 102.0),
            ),
            created_at=100.0,
            updated_at=103.0,
        )


def test_lease_is_time_bounded_scoped_and_owner_specific() -> None:
    scope = JobScope("tenant-a", "workspace-a", "collection-a")
    lease = JobLease(
        job_id="job-1",
        scope=scope,
        worker_id="worker-a",
        token="lease-a",
        acquired_at=10.0,
        expires_at=20.0,
        heartbeat_at=15.0,
    )
    assert not lease.active_at(9.0)
    assert lease.active_at(10.0)
    assert lease.active_at(19.99)
    assert not lease.active_at(20.0)
    assert lease.matches(make_job(job_id="job-1"), worker_id="worker-a", token="lease-a")
    assert not lease.matches(make_job(job_id="job-1", tenant_id="tenant-b"), worker_id="worker-a", token="lease-a")
    assert not lease.matches(make_job(job_id="job-1"), worker_id="worker-b", token="lease-a")
    assert not lease.matches(make_job(job_id="job-1"), worker_id="worker-a", token="lease-b")
    with pytest.raises(JobValidationError):
        JobLease("job-1", scope, "worker-a", "lease-a", 10.0, 10.0, 10.0)


def test_payload_is_deterministic_bounded_and_rejects_secret_or_raw_content() -> None:
    one = make_job(payload={"filename": "one.txt", "source_key": "objects/one.txt"})
    two = make_job(payload={"source_key": "objects/one.txt", "filename": "one.txt"})
    assert one.to_json() == two.to_json()
    assert json.loads(one.to_json())["contract_version"] == "jobs-contract-v1"
    assert dict(make_job(payload={"byte_size": "7"}).payload) == {"byte_size": "7"}
    for unsafe in (
        {"provider_token": "do-not-store"},
        {"raw_content": "document body"},
        {"content": "document body"},
        {"provider_result": "full provider response"},
        {"private_key": "-----BEGIN PRIVATE KEY-----"},
        {"document_text": "document body"},
    ):
        with pytest.raises(JobValidationError):
            make_job(payload=unsafe)
    with pytest.raises(JobValidationError):
        make_job(payload={"source_key": "\x00"})
    with pytest.raises(JobValidationError):
        make_job(payload={"source_key": "full document body"})
    with pytest.raises(JobValidationError):
        make_job(payload={"source_key": "sk_live_123"})
    with pytest.raises(JobValidationError):
        make_job(payload={"source_key": "raw-document-body"})
    with pytest.raises(JobValidationError):
        make_job(payload={"notes": "free-text"})


def test_scope_time_and_result_metadata_validation_fail_closed() -> None:
    with pytest.raises(JobValidationError):
        make_job(tenant_id="")
    with pytest.raises(JobValidationError):
        make_job(now=float("nan"))
    with pytest.raises(JobValidationError):
        make_job(max_attempts=0)
    with pytest.raises(InvalidTransitionError):
        active_job().finish_attempt(
            JobState.SUCCEEDED,
            now=103.0,
            result=JobResult(output_refs={"object_key": "objects/a"}, completed_at=104.0),
        )
    result = JobResult(output_refs={"object_key": "objects/a", "index_version": "v1"}, completed_at=3.0)
    assert dict(result.output_refs)["object_key"] == "objects/a"
    with pytest.raises(JobValidationError):
        JobResult(output_refs={"provider_token": "secret"}, completed_at=3.0)


def test_idempotency_is_scoped_and_replay_or_conflict_is_deterministic() -> None:
    existing = make_job(job_id="job-existing")
    replay = make_job(job_id="job-replay")
    assert idempotency_identity(existing) == (
        "tenant-a", "workspace-a", "collection-a", "idem-1"
    )
    assert ensure_idempotent(existing, replay) is existing
    trace_replay = make_job(
        job_id="job-trace-replay",
        payload={
            "source_key": "objects/one.txt",
            "filename": "one.txt",
            "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
        },
    )
    assert ensure_idempotent(existing, trace_replay) is existing
    with pytest.raises(JobIdempotencyConflictError):
        ensure_idempotent(existing, make_job(job_id="job-other", payload={"source_key": "objects/two.txt"}))
    with pytest.raises(JobIdempotencyConflictError):
        ensure_idempotent(existing, make_job(job_id="job-other", tenant_id="tenant-b"))
