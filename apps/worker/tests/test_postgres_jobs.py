from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json

import pytest

from postgres_jobs import (
    PostgresJobCorruptionError,
    PostgresJobError,
    PostgresJobIdempotencyError,
    PostgresJobLeaseError,
    PostgresJobQueue,
)
from rick_jobs import (
    Job,
    JobAttempt,
    JobFailure,
    JobLease,
    JobQueue,
    JobRepository,
    JobResult,
    JobScheduler,
    JobScope,
    JobState,
)
from postgres_jobs import _json_object, _parse_result


def _json(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def test_result_decoder_rejects_non_string_metadata_and_document_references() -> None:
    with pytest.raises(PostgresJobCorruptionError):
        _parse_result({"output_refs": {"byte_size": 7}, "completed_at": 100.0})
    with pytest.raises(PostgresJobCorruptionError):
        _parse_result({"output_refs": {}, "document_id": 7, "completed_at": 100.0})
    restored = _parse_result({"output_refs": {}, "document_id": None, "completed_at": 100.0}, document_id="doc-1")
    assert restored is not None and restored.document_id == "doc-1"


def test_database_json_decoder_rejects_oversized_and_nonfinite_values() -> None:
    oversized = '{"source_key":"' + ("a" * (256 * 1024)) + '"}'

    with pytest.raises(PostgresJobCorruptionError):
        _json_object(oversized, field="payload")
    with pytest.raises(PostgresJobCorruptionError):
        _json_object('{"completed_at":NaN}', field="result")
    with pytest.raises(PostgresJobCorruptionError):
        _json_object('{"document_id":"first","document_id":"second"}', field="result")


class FakeConnection:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, object]] = {}
        self.attempts: dict[tuple[str, int], dict[str, object]] = {}
        self.trace: list[tuple[str, tuple[object, ...]]] = []
        self.database_now = 104.0
        self.migration_ready = True
        self.migration_version = '0010'
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self) -> "FakeCursor":
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.rows: list[Mapping[str, object]] = []
        self.rowcount = 0
        self.description = None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        self.connection.trace.append((" ".join(query.split()), params))
        self.rows = []
        self.rowcount = 0
        compact = " ".join(query.lower().split())
        if compact.startswith("select 1"):
            self.rows = [{"one": 1}]
            return
        if compact.startswith("select version from rick_schema_migrations"):
            required = '0010' if "version='0010'" in compact else '0005'
            self.rows = [{"version": required}] if self.connection.migration_ready and self.connection.migration_version == required else []
            return
        if compact.startswith("select pg_advisory_xact_lock"):
            return
        if "from rick_ingestion_job_attempts" in compact:
            job_id = str(params[0])
            self.rows = [
                dict(attempt)
                for (observed_job_id, _number), attempt in sorted(self.connection.attempts.items())
                if observed_job_id == job_id
            ]
            return
        if compact.startswith("select count(*) as count"):
            tenant, workspace, collection = params[:3]
            count = sum(
                1
                for row in self.connection.jobs.values()
                if (row["tenant_id"], row["workspace_id"], row["collection_id"])
                == (tenant, workspace, collection)
                and row["contract_state"] in {"PENDING", "QUEUED", "RETRYING", "RUNNING"}
            )
            self.rows = [{"count": count}]
            return
        if compact.startswith("select") and "from rick_ingestion_jobs" in compact:
            self._select_jobs(compact, params)
            return
        if compact.startswith("insert into rick_ingestion_jobs"):
            self._insert_job(params)
            return
        if compact.startswith("insert into rick_ingestion_job_attempts"):
            self._insert_attempt(params)
            return
        if compact.startswith("update rick_ingestion_jobs"):
            self._update_job(compact, params)
            return
        if compact.startswith("delete from rick_ingestion_jobs") or compact.startswith("with doomed"):
            if compact.startswith("delete from rick_ingestion_jobs"):
                job_id = str(params[0])
                row = self.connection.jobs.pop(job_id, None)
                if row is not None:
                    self.connection.attempts = {
                        key: value
                        for key, value in self.connection.attempts.items()
                        if key[0] != job_id
                    }
                    self.rowcount = 1
            return
        if compact.startswith("insert into rick_ingestion_job_events"):
            return
        if compact.startswith("insert into rick_outbox"):
            return
        if compact.startswith("insert into rick_audit_events"):
            return
        raise AssertionError(f"unhandled SQL: {compact}")

    def _select_jobs(self, compact: str, params: tuple[object, ...]) -> None:
        rows = list(self.connection.jobs.values())
        if "idempotency_key=%s" in compact:
            scope = tuple(params[:3])
            key = params[3]
            rows = [
                row
                for row in rows
                if (row["tenant_id"], row["workspace_id"], row["collection_id"]) == scope
                and row["idempotency_key"] == key
            ]
        elif "job_id=%s" in compact:
            job_id = params[0]
            rows = [row for row in rows if row["job_id"] == job_id]
            if len(params) >= 4 and "collection_id=%s" in compact:
                scope = tuple(params[1:4])
                rows = [
                    row
                    for row in rows
                    if (row["tenant_id"], row["workspace_id"], row["collection_id"]) == scope
                ]
            if "lease_worker_id=%s" in compact:
                worker, token, version = params[4:7]
                rows = [
                    row
                    for row in rows
                    if row["lease_worker_id"] == worker
                    and row["lease_owner"] == token
                    and row["version"] == version
                ]
        else:
            if "contract_state='running'" in compact or "contract_state='queued'" in compact:
                scope = tuple(params[:3])
                rows = [
                    row
                    for row in rows
                    if (row["tenant_id"], row["workspace_id"], row["collection_id"]) == scope
                ]
            if "contract_state='running'" in compact:
                rows = [row for row in rows if row["contract_state"] == "RUNNING"]
                if "lease_until <= clock_timestamp()" in compact:
                    rows = [row for row in rows if row["lease_until"] is not None and row["lease_until"] <= self.connection.database_now]
            elif "contract_state='queued'" in compact:
                rows = [row for row in rows if row["contract_state"] == "QUEUED"]
                if "available_at <= clock_timestamp()" in compact:
                    rows = [row for row in rows if float(row["available_at"]) <= self.connection.database_now]
            elif "contract_state='dead_letter'" in compact:
                scope = tuple(params[:3])
                rows = [
                    row
                    for row in rows
                    if (row["tenant_id"], row["workspace_id"], row["collection_id"]) == scope
                    and row["contract_state"] == "DEAD_LETTER"
                ]
            elif "contract_state in ('succeeded','cancelled','dead_letter')" in compact:
                tenant, workspace, collection, cutoff = params[:4]
                rows = [
                    row
                    for row in rows
                    if (row["tenant_id"], row["workspace_id"], row["collection_id"])
                    == (tenant, workspace, collection)
                    and row["contract_state"] in {"SUCCEEDED", "CANCELLED", "DEAD_LETTER"}
                    and float(row["updated_at"]) < float(cutoff)
                ]
        if "lease_until > clock_timestamp()" in compact:
            rows = [row for row in rows if row["lease_until"] is not None and row["lease_until"] > self.connection.database_now]
        if 'publication_recovery_at <= clock_timestamp()' in compact:
            rows = [row for row in rows if row.get('publication_recovery_at') is None or row['publication_recovery_at'] <= self.connection.database_now]
        if 'order by publication_recovery_at nulls first' in compact:
            rows.sort(key=lambda row: (row.get('publication_recovery_at') is not None, row.get('publication_recovery_at') or 0, float(row['created_at']), str(row['job_id'])))
        else:
            rows.sort(key=lambda row: (float(row["created_at"]), str(row["job_id"])))
        if "limit %s" in compact:
            rows = rows[: int(params[-1])]
        self.rows = [dict(row) for row in rows]

    def _insert_job(self, params: tuple[object, ...]) -> None:
        (
            job_id,
            idempotency_key,
            tenant_id,
            workspace_id,
            collection_id,
            document_id,
            operation,
            status,
            state,
            contract_version,
            payload,
            max_attempts,
            attempts,
            available_at,
            result,
            failure,
            version,
            created_at,
            updated_at,
        ) = params
        row = {
            "job_id": job_id,
            "idempotency_key": idempotency_key,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "collection_id": collection_id,
            "document_id": document_id,
            "operation": operation,
            "status": status,
            "contract_state": state,
            "contract_version": contract_version,
            "payload": _json(payload) or {},
            "max_attempts": max_attempts,
            "attempts": attempts,
            "available_at": available_at,
            "lease_until": None,
            "lease_owner": None,
            "lease_worker_id": None,
            "lease_acquired_at": None,
            "result": _json(result),
            "failure": _json(failure),
            "version": version,
            "created_at": created_at,
            "updated_at": updated_at,
            "last_error_code": None,
        }
        self.connection.jobs[str(job_id)] = row
        self.rows = [dict(row)]

    def _insert_attempt(self, params: tuple[object, ...]) -> None:
        job_id, number, worker_id, state, started, finished, failure = params
        self.connection.attempts[(str(job_id), int(number))] = {
            "attempt_no": number,
            "worker_id": worker_id,
            "state": state,
            "started_at": started,
            "finished_at": finished,
            "failure": _json(failure),
        }

    def _update_job(self, compact: str, params: tuple[object, ...]) -> None:
        if 'set publication_recovery_at=clock_timestamp()' in compact:
            reason, job_id, tenant, workspace, collection, version = params if 'last_error_code=%s' in compact else (None, *params)
            row = self.connection.jobs.get(str(job_id))
            if row and (row['tenant_id'], row['workspace_id'], row['collection_id'], row['version'], row['contract_state']) == (tenant, workspace, collection, version, 'RUNNING'):
                row['publication_recovery_at'] = self.connection.database_now + 1
                if 'last_error_code=%s' in compact:
                    row['last_error_code'] = reason
                self.rowcount = 1
            return
        if "set lease_until=clock_timestamp() +" in compact and "returning lease_acquired_at" in compact:
            duration = float(params[0])
            job_id = str(params[1])
            row = self.connection.jobs[job_id]
            row["lease_acquired_at"] = self.connection.database_now
            row["lease_until"] = self.connection.database_now + duration
            self.rows = [
                {
                    "lease_acquired_at": row["lease_acquired_at"],
                    "lease_until": row["lease_until"],
                    "database_now": self.connection.database_now,
                }
            ]
            return
        guarded = "and contract_state='running' and lease_worker_id=%s" in compact
        tail = list(params[-7:-2] if guarded else params[-5:])
        job_id = str(tail[0])
        row = self.connection.jobs.get(job_id)
        if row is None or row["version"] != tail[-1]:
            self.rows = []
            return
        base = list(params[:13])
        row.update(
            {
                "idempotency_key": base[0],
                "operation": base[1],
                "payload": _json(base[2]) or {},
                "status": base[3],
                "contract_state": base[4],
                "contract_version": base[5],
                "max_attempts": base[6],
                "attempts": base[7],
                "available_at": base[8],
                "result": _json(base[9]),
                "failure": _json(base[10]),
                "version": base[11],
                "updated_at": base[12],
            }
        )
        index = 13
        if "document_id=%s" in compact:
            row["document_id"] = params[index]
            index += 1
        if "lease_worker_id=%s" in compact:
            row["lease_worker_id"], row["lease_owner"] = params[index : index + 2]
            if "clock_timestamp() +" in compact:
                duration = float(params[index + 2])
                row["lease_acquired_at"] = self.connection.database_now
                row["lease_until"] = self.connection.database_now + duration
            else:
                row["lease_acquired_at"], row["lease_until"] = params[index + 2 : index + 4]
        self.rows = [dict(row)]

    def fetchone(self) -> Mapping[str, object] | None:
        return self.rows.pop(0) if self.rows else None

    def fetchall(self) -> list[Mapping[str, object]]:
        rows = list(self.rows)
        self.rows.clear()
        return rows

    def close(self) -> None:
        return None


def make_queue() -> tuple[PostgresJobQueue, FakeConnection]:
    connection = FakeConnection()
    return PostgresJobQueue(lambda: connection, lease_seconds=10.0, backoff_seconds=1.0), connection


def make_job(*, scope: JobScope | None = None, job_id: str = "job-1", key: str = "idem-1", now: float = 100.0, max_attempts: int = 3, payload: Mapping[str, str] | None = None) -> Job:
    scope = scope or JobScope("tenant-a", "workspace-a", "collection-a")
    return Job.create(
        job_id=job_id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        collection_id=scope.collection_id,
        operation="ingest",
        idempotency_key=key,
        payload=payload or {"source_key": "objects/one.txt"},
        now=now,
        max_attempts=max_attempts,
    )


def test_adapter_implements_all_canonical_ports() -> None:
    queue, _connection = make_queue()
    assert isinstance(queue, JobRepository)
    assert isinstance(queue, JobQueue)
    assert isinstance(queue, JobScheduler)


def test_enqueue_claim_heartbeat_ack_is_scoped_and_versioned() -> None:
    queue, connection = make_queue()
    job = make_job()
    queued = queue.enqueue(job, expected_version=0)
    assert queued.state is JobState.QUEUED
    assert queued.version == 2

    claimed = queue.claim(
        worker_id="worker-a",
        scope=job.scope,
        expected_versions={queued.job_id: queued.version},
        now=103.0,
    )
    running, lease = claimed[0]
    assert running.state is JobState.RUNNING
    assert running.attempt_count == 1
    assert running.version == 3
    with pytest.raises(PostgresJobLeaseError, match="owner-bound cancellation"):
        queue.transition(
            running,
            JobState.CANCELLED,
            now=103.0,
            expected_version=running.version,
        )
    with pytest.raises(PostgresJobLeaseError, match="owner-bound lifecycle"):
        queue.save(replace(running, version=running.version + 1), expected_version=running.version)

    renewed = queue.heartbeat(lease, now=104.0, expected_version=running.version)
    assert renewed.heartbeat_at == 104.0
    succeeded = queue.acknowledge(
        renewed,
        JobResult(output_refs={"object_key": "objects/one.txt"}, document_id="doc-1", completed_at=105.0),
        now=105.0,
        expected_version=running.version,
    )
    assert succeeded.state is JobState.SUCCEEDED
    assert succeeded.version == 4
    assert succeeded.attempts[-1].state is JobState.SUCCEEDED
    assert connection.commits == 4
    assert any("FOR UPDATE SKIP LOCKED" in query for query, _params in connection.trace)
    assert any("clock_timestamp()" in query for query, _params in connection.trace)
    assert any(
        "INSERT INTO rick_ingestion_job_events" in query
        and any("lease_heartbeat" in str(item) for item in params)
        for query, params in connection.trace
    )
    assert any(
        "tenant_id=%s AND workspace_id=%s AND collection_id=%s AND idempotency_key=%s" in query
        for query, _params in connection.trace
    )
    assert any("AND collection_id=%s AND version=%s" in query for query, _params in connection.trace)

    with pytest.raises(PostgresJobLeaseError):
        queue.acknowledge(
            lease,
            JobResult(output_refs={}, completed_at=106.0),
            now=106.0,
            expected_version=running.version,
        )


def test_claim_can_derive_locked_version_and_running_cancel_is_owner_bound() -> None:
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(), expected_version=0)
    running, lease = queue.claim(
        worker_id="worker-a",
        scope=queued.scope,
        expected_versions={},
        now=103.0,
    )[0]

    cancelled = queue.cancel_lease(
        lease,
        now=104.0,
        expected_version=running.version,
    )

    assert cancelled.state is JobState.CANCELLED
    assert cancelled.attempts[-1].state is JobState.CANCELLED
    assert connection.jobs[str(cancelled.job_id)]["lease_owner"] is None
    with pytest.raises(PostgresJobLeaseError):
        queue.cancel_lease(lease, now=105.0, expected_version=running.version)


def test_readiness_requires_the_publication_recovery_schema_marker() -> None:
    queue, connection = make_queue()

    assert queue.readiness_check() is True
    connection.migration_version = '0005'
    assert queue.readiness_check() is False
    connection.migration_version = '0010'
    connection.migration_ready = False
    assert queue.readiness_check() is False


def test_failure_retry_exhaustion_and_authorized_replay_preserve_scope() -> None:
    queue, connection = make_queue()
    scope = JobScope("tenant-a", "workspace-a", "collection-a")
    original = queue.enqueue(make_job(scope=scope, max_attempts=2), expected_version=0)
    running, lease = queue.claim(
        worker_id="worker-a",
        scope=scope,
        expected_versions={original.job_id: original.version},
        now=103.0,
    )[0]
    retrying = queue.fail(
        lease,
        JobFailure("provider_timeout", "provider timed out", True, 1, 104.0),
        now=104.0,
        expected_version=running.version,
    )
    assert retrying.state is JobState.QUEUED
    assert retrying.attempt_count == 1

    connection.database_now = 106.0
    running_again, lease_again = queue.claim(
        worker_id="worker-b",
        scope=scope,
        expected_versions={retrying.job_id: retrying.version},
        now=106.0,
    )[0]
    dead = queue.fail(
        lease_again,
        JobFailure("schema_invalid", "schema is invalid", False, 2, 107.0),
        now=107.0,
        expected_version=running_again.version,
    )
    assert dead.state is JobState.DEAD_LETTER
    assert len(dead.attempts) == 2

    replay = queue.replay_dead_letter(
        dead.job_id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        collection_id=scope.collection_id,
        replay_job_id="job-replay-1",
        replay_idempotency_key="idem-replay-1",
        now=108.0,
        expected_version=dead.version,
    )
    assert replay.state is JobState.QUEUED
    assert replay.job_id == "job-replay-1"
    assert replay.attempt_count == 0
    assert connection.jobs[str(dead.job_id)]["contract_state"] == "DEAD_LETTER"


@pytest.mark.parametrize("max_attempts", [1, 2])
def test_claim_recovers_only_expired_leases_without_consuming_an_extra_attempt(max_attempts) -> None:
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(max_attempts=max_attempts), expected_version=0)
    running, lease = queue.claim(worker_id="worker-a", scope=queued.scope, expected_versions={}, now=104.0)[0]
    assert (lease.acquired_at, lease.expires_at) == (104.0, 114.0)
    assert running.attempt_count == 1

    connection.database_now = 113.0
    assert queue.claim(worker_id="worker-b", scope=queued.scope, expected_versions={}, now=113.0) == ()
    assert connection.jobs[str(queued.job_id)]["contract_state"] == "RUNNING"
    assert connection.attempts[(str(queued.job_id), 1)]["state"] == "RUNNING"

    connection.database_now = 114.0
    commits = connection.commits
    assert queue.claim(worker_id="worker-b", scope=queued.scope, expected_versions={}, now=114.0) == ()
    assert connection.commits == commits + 1
    row = connection.jobs[str(queued.job_id)]
    assert row["attempts"] == 1
    assert row["lease_owner"] is None
    assert row["contract_state"] == ("QUEUED" if max_attempts == 2 else "DEAD_LETTER")
    attempt = connection.attempts[(str(queued.job_id), 1)]
    assert attempt["state"] == "FAILED"
    assert attempt["finished_at"] == 114.0
    assert attempt["failure"]["code"] == "lease_expired"
    assert len(connection.attempts) == 1

    connection.database_now = 115.0
    recovered = queue.claim(worker_id="worker-b", scope=queued.scope, expected_versions={}, now=115.0)
    if max_attempts == 1:
        assert recovered == ()
    else:
        retried, next_lease = recovered[0]
        assert retried.attempt_count == 2
        assert [attempt.number for attempt in retried.attempts] == [1, 2]
        assert next_lease.token != lease.token
        assert next_lease.worker_id == "worker-b"
        with pytest.raises(PostgresJobLeaseError):
            queue.heartbeat(lease, now=115.0, expected_version=retried.version)


@pytest.mark.parametrize("operation", ["heartbeat", "acknowledge", "fail"])
def test_expired_lease_rejects_owner_mutations_even_with_a_stale_client_clock(operation) -> None:
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(), expected_version=0)
    running, lease = queue.claim(worker_id="worker-a", scope=queued.scope, expected_versions={}, now=104.0)[0]
    connection.database_now = lease.expires_at
    commits = connection.commits
    kwargs = {"now": 105.0, "expected_version": running.version}
    if operation == "acknowledge":
        kwargs["result"] = JobResult(output_refs={}, completed_at=105.0)
    elif operation == "fail":
        kwargs["failure"] = JobFailure("provider_timeout", "timed out", True, 1, 105.0)
    with pytest.raises(PostgresJobLeaseError):
        getattr(queue, operation)(lease, **kwargs)
    assert connection.commits == commits
    assert connection.rollbacks == 1
    assert connection.jobs[str(queued.job_id)]["contract_state"] == "RUNNING"
    assert connection.attempts[(str(queued.job_id), 1)]["state"] == "RUNNING"


def test_retry_backoff_and_exhaustion_count_only_successful_claims() -> None:
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(max_attempts=2), expected_version=0)
    for number, claimed_at in [(1, 104.0), (2, 106.0)]:
        connection.database_now = claimed_at
        running, lease = queue.claim(worker_id="worker-a", scope=queued.scope, expected_versions={}, now=claimed_at)[0]
        assert running.attempt_count == number
        commits = connection.commits
        connection.database_now = claimed_at + 1
        failed = queue.fail(
            lease, JobFailure("provider_timeout", "timed out", True, number, claimed_at + 1),
            now=claimed_at + 1, expected_version=running.version,
        )
        assert connection.commits == commits + 1
        assert failed.attempt_count == number
        assert failed.attempts[-1].state is JobState.FAILED
        assert failed.state is (JobState.QUEUED if number == 1 else JobState.DEAD_LETTER)
        assert queue.claim(worker_id="worker-b", scope=queued.scope, expected_versions={}, now=claimed_at + 1) == ()
        if number == 1:
            assert failed.available_at == 106.0
    assert len(connection.attempts) == 2


def test_claim_attempt_write_failure_rolls_back_without_committing(monkeypatch) -> None:
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(), expected_version=0)
    commits = connection.commits
    closed = connection.closed

    def fail_attempt(_cursor, _params):
        raise TimeoutError("synthetic attempt write timeout")

    monkeypatch.setattr(FakeCursor, "_insert_attempt", fail_attempt)
    with pytest.raises(PostgresJobError, match="queue_unavailable"):
        queue.claim(worker_id="worker-a", scope=queued.scope, expected_versions={}, now=104.0)
    assert connection.commits == commits
    assert connection.rollbacks == 1
    assert connection.closed == closed + 1
    assert connection.attempts == {}


def test_idempotency_is_complete_scope_and_conflicts_are_rejected() -> None:
    queue, _connection = make_queue()
    first = make_job()
    queued = queue.enqueue(first, expected_version=0)
    replay = queue.enqueue(first, expected_version=queued.version)
    assert replay.job_id == queued.job_id

    with pytest.raises(PostgresJobIdempotencyError):
        queue.enqueue(
            make_job(job_id="job-other", now=100.0, payload={"source_key": "objects/two.txt"}),
            expected_version=0,
        )

    other_scope = JobScope("tenant-a", "workspace-b", "collection-a")
    other = queue.enqueue(
        make_job(scope=other_scope, job_id="job-other-scope", now=100.0),
        expected_version=0,
    )
    assert other.scope == other_scope
    assert queue.get(
        queued.job_id,
        tenant_id=other_scope.tenant_id,
        workspace_id=other_scope.workspace_id,
        collection_id=other_scope.collection_id,
    ) is None


def test_finished_attempt_history_cannot_be_mutated_through_save() -> None:
    queue, _connection = make_queue()
    queued = queue.enqueue(make_job(), expected_version=0)
    running, lease = queue.claim(
        worker_id="worker-a",
        scope=queued.scope,
        expected_versions={queued.job_id: queued.version},
        now=103.0,
    )[0]
    succeeded = queue.acknowledge(
        lease,
        JobResult(output_refs={}, completed_at=104.0),
        now=104.0,
        expected_version=running.version,
    )
    finished = succeeded.attempts[0]
    tampered = replace(
        succeeded,
        attempts=(
            JobAttempt(
                number=finished.number,
                worker_id="worker-b",
                state=finished.state,
                started_at=finished.started_at,
                finished_at=finished.finished_at,
            ),
        ),
        version=succeeded.version + 1,
    )
    with pytest.raises(PostgresJobError, match="finished attempt history is immutable"):
        queue.save(tampered, expected_version=succeeded.version)


def test_legacy_rows_are_read_as_compatibility_views() -> None:
    queue, connection = make_queue()
    connection.jobs["legacy-job"] = {
        "job_id": "legacy-job",
        "idempotency_key": "legacy-key",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "collection_id": "collection-a",
        "document_id": None,
        "operation": "ingest",
        "status": "published",
        "contract_state": None,
        "contract_version": None,
        "payload": {"source_key": "objects/legacy.txt"},
        "max_attempts": 3,
        "attempts": 1,
        "available_at": 100.0,
        "lease_until": None,
        "lease_owner": None,
        "lease_worker_id": None,
        "lease_acquired_at": None,
        "result": None,
        "failure": None,
        "version": 1,
        "created_at": 100.0,
        "updated_at": 101.0,
        "last_error_code": None,
    }
    observed = queue.get(
        "legacy-job",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        collection_id="collection-a",
    )
    assert observed is not None
    assert observed.state is JobState.SUCCEEDED
    assert len(observed.attempts) == 1
    assert observed.result is not None
    with pytest.raises(PostgresJobError, match="canonical rewrite"):
        queue.cancel(
            "legacy-job",
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            collection_id="collection-a",
            now=102.0,
            expected_version=observed.version,
        )


def test_retention_projects_audit_and_outbox_before_delete() -> None:
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(), expected_version=0)
    running, lease = queue.claim(
        worker_id="worker-a",
        scope=queued.scope,
        expected_versions={queued.job_id: queued.version},
        now=103.0,
    )[0]
    succeeded = queue.acknowledge(
        lease,
        JobResult(output_refs={}, completed_at=104.0),
        now=104.0,
        expected_version=running.version,
    )
    assert queue.prune_terminal(scope=succeeded.scope, older_than=200.0, limit=10) == 1
    assert str(succeeded.job_id) not in connection.jobs
    assert any(
        "INSERT INTO rick_ingestion_job_events" in query
        and any("retention_pruned" in str(item) for item in params)
        for query, params in connection.trace
    )
    assert any(
        "INSERT INTO rick_outbox" in query and any("retention_pruned" in str(item) for item in params)
        for query, params in connection.trace
    )
    assert any(
        "INSERT INTO rick_audit_events" in query and any("retention_pruned" in str(item) for item in params)
        for query, params in connection.trace
    )
