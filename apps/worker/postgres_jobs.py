"""Canonical PostgreSQL adapter for the :mod:`rick_jobs` contracts.

The adapter owns no connection or credential discovery.  A reviewed DB-API
connection factory is injected by the composition root.  Every mutation is
scoped by tenant/workspace/collection, uses an optimistic version predicate,
and commits the job row, attempt history, lifecycle event and audit projection
as one transaction.

``postgres_queue.PostgresIngestionQueue`` remains available as the legacy
compatibility facade.  New code should depend on this module's canonical
``PostgresJobQueue``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
import json
import math
import secrets
from typing import Protocol

from rick_jobs import (
    Job,
    JobAttempt,
    JobContractError,
    JobFailure,
    JobId,
    JobIdempotencyConflictError,
    JobLease,
    JobQueue,
    JobRepository,
    JobResult,
    JobScheduler,
    JobScope,
    JobState,
    WorkerId,
    ensure_idempotent,
)


class DbConnection(Protocol):
    def cursor(self) -> object: ...
    def commit(self) -> object: ...
    def rollback(self) -> object: ...
    def close(self) -> object: ...


class PostgresJobError(RuntimeError):
    """Base error for adapter failures."""

    _codes = {
        "queue_unavailable",
        "invalid_input",
        "closed",
        "not_found",
        "concurrency",
        "lease",
        "idempotency",
        "corrupt",
        "capacity",
        "invalid_transition",
    }

    def __init__(self, code: str = "queue_unavailable", message: str | None = None) -> None:
        self.code = code if code in self._codes else "queue_unavailable"
        super().__init__(message or self.code)


class PostgresJobConcurrencyError(PostgresJobError):
    def __init__(self, message: str = "job version changed") -> None:
        super().__init__("concurrency", message)


class PostgresJobLeaseError(PostgresJobError):
    def __init__(self, message: str = "lease is missing, expired, or owned by another worker") -> None:
        super().__init__("lease", message)


class PostgresJobIdempotencyError(PostgresJobError):
    def __init__(self, message: str = "idempotency key conflicts with an existing job") -> None:
        super().__init__("idempotency", message)


class PostgresJobNotFoundError(PostgresJobError):
    def __init__(self, message: str = "job was not found in the requested scope") -> None:
        super().__init__("not_found", message)


class PostgresJobCorruptionError(PostgresJobError):
    def __init__(self, message: str = "durable job data violates the canonical contract") -> None:
        super().__init__("corrupt", message)


_KEEP_LEASE = object()
_LEGACY_STATES = {
    "queued": JobState.QUEUED,
    "leased": JobState.RUNNING,
    "processing": JobState.RUNNING,
    "published": JobState.SUCCEEDED,
    "acked": JobState.SUCCEEDED,
    "failed": JobState.FAILED,
    "cancelled": JobState.CANCELLED,
    "dead": JobState.DEAD_LETTER,
}
_SELECT_COLUMNS = """
    job_id, idempotency_key, tenant_id, workspace_id, collection_id,
    document_id, operation, status, contract_state, contract_version,
    payload, max_attempts, attempts, available_at, lease_until, lease_owner,
    lease_worker_id, lease_acquired_at, result, failure, version,
    created_at, updated_at, last_error_code
"""


def _row_dict(cursor: object, row: object) -> dict[str, object]:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    description = getattr(cursor, "description", None) or ()
    names = [item[0] for item in description if isinstance(item, (tuple, list)) and item]
    values = row if isinstance(row, (tuple, list)) else ()
    return dict(zip(names, values))


def _epoch(value: object, *, field: str) -> float:
    if isinstance(value, datetime):
        result = value.timestamp()
    else:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise PostgresJobCorruptionError(f"{field} is not a timestamp") from exc
    if not math.isfinite(result) or result < 0:
        raise PostgresJobCorruptionError(f"{field} is not a finite timestamp")
    return result


def _time(value: object, *, field: str = "time") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PostgresJobError("invalid_input", f"{field} must be a finite timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise PostgresJobError("invalid_input", f"{field} must be a finite timestamp")
    return result


def _json_value(value: object, *, field: str, default: object = None) -> object:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise PostgresJobCorruptionError(f"{field} is not valid JSON") from exc
    return value


def _json_object(value: object, *, field: str, default: Mapping[str, object] | None = None) -> Mapping[str, object] | None:
    parsed = _json_value(value, field=field, default=default)
    if parsed is None:
        return None
    if not isinstance(parsed, Mapping):
        raise PostgresJobCorruptionError(f"{field} must be a JSON object")
    return parsed


def _dump(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _failure_dict(failure: JobFailure | None) -> dict[str, object] | None:
    if failure is None:
        return None
    return {
        "code": failure.code,
        "message": failure.message,
        "retryable": failure.retryable,
        "attempt": failure.attempt,
        "occurred_at": failure.occurred_at,
    }


def _result_dict(result: JobResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "output_refs": dict(result.output_refs),
        "document_id": result.document_id,
        "completed_at": result.completed_at,
    }


def _parse_failure(value: object, *, field: str = "failure") -> JobFailure | None:
    raw = _json_object(value, field=field)
    if raw is None:
        return None
    try:
        return JobFailure(
            code=raw["code"],  # type: ignore[arg-type]
            message=raw["message"],  # type: ignore[arg-type]
            retryable=raw["retryable"],  # type: ignore[arg-type]
            attempt=raw["attempt"],  # type: ignore[arg-type]
            occurred_at=raw["occurred_at"],  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError, JobContractError) as exc:
        raise PostgresJobCorruptionError(f"{field} violates the jobs contract") from exc


def _parse_result(value: object, *, document_id: object = None) -> JobResult | None:
    raw = _json_object(value, field="result")
    if raw is None:
        return None
    observed_document = raw.get("document_id", document_id)
    try:
        return JobResult(
            output_refs=raw.get("output_refs", {}),  # type: ignore[arg-type]
            document_id=observed_document if isinstance(observed_document, str) else None,
            completed_at=raw["completed_at"],  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError, JobContractError) as exc:
        raise PostgresJobCorruptionError("result violates the jobs contract") from exc


def _legacy_state(row: Mapping[str, object]) -> JobState:
    raw = row.get("contract_state") or row.get("status")
    if isinstance(raw, JobState):
        return raw
    if not isinstance(raw, str):
        raise PostgresJobCorruptionError("job state is missing")
    try:
        return JobState(raw.upper())
    except ValueError:
        try:
            return _LEGACY_STATES[raw.lower()]
        except KeyError as exc:
            raise PostgresJobCorruptionError("job state is unknown") from exc


def _legacy_status(state: JobState) -> str:
    return {
        JobState.PENDING: "queued",
        JobState.QUEUED: "queued",
        JobState.RETRYING: "queued",
        JobState.RUNNING: "processing",
        JobState.SUCCEEDED: "published",
        JobState.FAILED: "failed",
        JobState.CANCELLED: "cancelled",
        JobState.DEAD_LETTER: "dead",
    }[state]


def _attempt_dict(attempt: JobAttempt) -> dict[str, object]:
    return {
        "number": attempt.number,
        "worker_id": str(attempt.worker_id),
        "state": attempt.state.value,
        "started_at": attempt.started_at,
        "finished_at": attempt.finished_at,
        "failure": _failure_dict(attempt.failure),
    }


class PostgresJobQueue(JobRepository, JobQueue, JobScheduler):
    """Transactional PostgreSQL implementation of the canonical job ports."""

    def __init__(
        self,
        connection_factory: Callable[[], DbConnection],
        *,
        max_pending: int = 256,
        max_attempts: int = 3,
        lease_seconds: float = 30.0,
        backoff_seconds: float = 1.0,
        close_connections: bool = True,
    ) -> None:
        if not callable(connection_factory):
            raise PostgresJobError("invalid_input", "connection_factory must be callable")
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or not 1 <= max_pending <= 100_000:
            raise PostgresJobError("invalid_input", "max_pending is out of range")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 64:
            raise PostgresJobError("invalid_input", "max_attempts is out of range")
        if isinstance(lease_seconds, bool) or not 0.1 <= float(lease_seconds) <= 86_400:
            raise PostgresJobError("invalid_input", "lease_seconds is out of range")
        if isinstance(backoff_seconds, bool) or not 0 <= float(backoff_seconds) <= 86_400:
            raise PostgresJobError("invalid_input", "backoff_seconds is out of range")
        self._factory = connection_factory
        self.max_pending = max_pending
        self.max_attempts = max_attempts
        self.lease_seconds = float(lease_seconds)
        self.backoff_seconds = float(backoff_seconds)
        self._close_connections = close_connections
        self._closed = False

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[tuple[DbConnection, object]]:
        if self._closed:
            raise PostgresJobError("closed")
        connection: DbConnection | None = None
        cursor: object | None = None
        try:
            connection = self._factory()
            if connection is None:
                raise PostgresJobError("queue_unavailable", "connection factory returned no connection")
            cursor = connection.cursor()
            yield connection, cursor
            if write:
                connection.commit()
        except (PostgresJobError, JobContractError):
            if write and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        except Exception as exc:
            if write and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise PostgresJobError("queue_unavailable") from exc
        finally:
            if cursor is not None:
                close = getattr(cursor, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            if self._close_connections and connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _execute(cursor: object, query: str, params: Sequence[object] = ()) -> None:
        execute = getattr(cursor, "execute", None)
        if not callable(execute):
            raise PostgresJobError("queue_unavailable", "cursor has no execute method")
        execute(query, tuple(params))

    @staticmethod
    def _one(cursor: object) -> dict[str, object] | None:
        row = getattr(cursor, "fetchone", lambda: None)()
        return None if row is None else _row_dict(cursor, row)

    @staticmethod
    def _many(cursor: object) -> list[dict[str, object]]:
        return [_row_dict(cursor, row) for row in getattr(cursor, "fetchall", lambda: [])()]

    @staticmethod
    def _scope_params(scope: JobScope) -> tuple[str, str, str]:
        return (scope.tenant_id, scope.workspace_id, scope.collection_id)

    @classmethod
    def _select_sql(cls, where: str, *, lock: bool = False) -> str:
        suffix = " FOR UPDATE" if lock else ""
        return f"SELECT { _SELECT_COLUMNS } FROM rick_ingestion_jobs WHERE {where}{suffix}"

    @classmethod
    def _select_one(
        cls,
        cursor: object,
        where: str,
        params: Sequence[object],
        *,
        lock: bool = False,
    ) -> dict[str, object] | None:
        cls._execute(cursor, cls._select_sql(where, lock=lock), params)
        return cls._one(cursor)

    @classmethod
    def _select_many(
        cls,
        cursor: object,
        where: str,
        params: Sequence[object],
        *,
        lock: bool = False,
        limit: int | None = None,
        skip_locked: bool = False,
    ) -> list[dict[str, object]]:
        query = cls._select_sql(where, lock=False)
        if limit is not None:
            query += " ORDER BY created_at, job_id LIMIT %s"
        if lock:
            query += " FOR UPDATE"
            if skip_locked:
                query += " SKIP LOCKED"
        values = list(params)
        if limit is not None:
            values.append(limit)
        cls._execute(cursor, query, values)
        return cls._many(cursor)

    @classmethod
    def _load_attempts(cls, cursor: object, job_id: str) -> tuple[JobAttempt, ...]:
        cls._execute(
            cursor,
            """
            SELECT attempt_no, worker_id, state, started_at, finished_at, failure
            FROM rick_ingestion_job_attempts
            WHERE job_id=%s
            ORDER BY attempt_no
            """,
            (job_id,),
        )
        attempts: list[JobAttempt] = []
        for row in cls._many(cursor):
            failure = _parse_failure(row.get("failure"), field="attempt.failure")
            try:
                attempts.append(
                    JobAttempt(
                        number=row.get("attempt_no"),  # type: ignore[arg-type]
                        worker_id=row.get("worker_id"),  # type: ignore[arg-type]
                        state=row.get("state"),  # type: ignore[arg-type]
                        started_at=_epoch(row.get("started_at"), field="attempt.started_at"),
                        finished_at=None
                        if row.get("finished_at") is None
                        else _epoch(row.get("finished_at"), field="attempt.finished_at"),
                        failure=failure,
                    )
                )
            except (TypeError, ValueError, JobContractError) as exc:
                raise PostgresJobCorruptionError("attempt history violates the jobs contract") from exc
        return tuple(attempts)

    @staticmethod
    def _legacy_attempts(row: Mapping[str, object], state: JobState) -> tuple[JobAttempt, ...]:
        """Reconstruct a read-only compatibility view for pre-0004 rows."""

        count = int(row.get("attempts") or 0)
        if count == 0:
            return ()
        if not 1 <= count <= 64:
            raise PostgresJobCorruptionError("legacy attempt count is out of range")
        created = _epoch(row.get("created_at"), field="created_at")
        updated = _epoch(row.get("updated_at"), field="updated_at")
        span = max(0.0, updated - created)
        worker = row.get("lease_worker_id") or row.get("lease_owner") or "legacy-worker"
        if isinstance(worker, str) and ":" in worker:
            worker = worker.split(":", 1)[0]
        if not isinstance(worker, str) or not worker:
            worker = "legacy-worker"
        observed_failure = _parse_failure(row.get("failure"))
        attempts: list[JobAttempt] = []
        for number in range(1, count + 1):
            started = created + span * ((number - 1) / count)
            finished = None if state is JobState.RUNNING and number == count else created + span * (number / count)
            if state is JobState.RUNNING and number == count:
                attempt_state = JobState.RUNNING
                failure = None
            elif state is JobState.SUCCEEDED and number == count:
                attempt_state = JobState.SUCCEEDED
                failure = None
            elif state is JobState.CANCELLED and number == count:
                attempt_state = JobState.CANCELLED
                failure = None
            else:
                attempt_state = JobState.FAILED
                if number == count and observed_failure is not None:
                    failure = observed_failure
                else:
                    occurred = finished if finished is not None else updated
                    failure = JobFailure(
                        code="legacy_retry",
                        message="legacy attempt history is reconstructed for compatibility",
                        retryable=True,
                        attempt=number,
                        occurred_at=occurred,
                    )
            attempts.append(
                JobAttempt(
                    number=number,
                    worker_id=worker,
                    state=attempt_state,
                    started_at=started,
                    finished_at=finished,
                    failure=failure,
                )
            )
        return tuple(attempts)

    @classmethod
    def _decode(cls, cursor: object, row: Mapping[str, object]) -> Job:
        job_id = row.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise PostgresJobCorruptionError("job_id is missing")
        state = _legacy_state(row)
        observed_attempts = int(row.get("attempts") or 0)
        attempts = cls._load_attempts(cursor, job_id)
        legacy_row = row.get("contract_state") is None
        if observed_attempts != len(attempts):
            if not legacy_row:
                raise PostgresJobCorruptionError(
                    f"attempt count mismatch for job {job_id}: row={observed_attempts} history={len(attempts)}"
                )
            attempts = cls._legacy_attempts(row, state)
        contract_version = row.get("contract_version")
        if contract_version not in (None, "jobs-contract-v1"):
            raise PostgresJobCorruptionError("unsupported jobs contract version")
        payload = _json_object(row.get("payload"), field="payload", default={}) or {}
        result = _parse_result(row.get("result"), document_id=row.get("document_id"))
        failure = _parse_failure(row.get("failure"))
        if legacy_row and state is JobState.SUCCEEDED and result is None:
            result = JobResult(
                output_refs={},
                document_id=row.get("document_id") if isinstance(row.get("document_id"), str) else None,
                completed_at=_epoch(row.get("updated_at"), field="updated_at"),
            )
        if legacy_row and state in {JobState.FAILED, JobState.DEAD_LETTER} and failure is None:
            failure = attempts[-1].failure if attempts and attempts[-1].failure is not None else JobFailure(
                code="legacy_failure",
                message="legacy failure reconstructed for compatibility",
                retryable=state is JobState.FAILED,
                attempt=max(1, observed_attempts),
                occurred_at=_epoch(row.get("updated_at"), field="updated_at"),
            )
        max_attempts = int(row.get("max_attempts") or cls_default_max_attempts(row))
        if legacy_row:
            max_attempts = max(max_attempts, observed_attempts, 1)
        try:
            return Job(
                job_id=job_id,
                tenant_id=row.get("tenant_id"),  # type: ignore[arg-type]
                workspace_id=row.get("workspace_id"),  # type: ignore[arg-type]
                collection_id=row.get("collection_id"),  # type: ignore[arg-type]
                operation=row.get("operation") or "ingest",
                idempotency_key=row.get("idempotency_key"),  # type: ignore[arg-type]
                payload=payload,  # type: ignore[arg-type]
                state=state,
                max_attempts=max_attempts,
                attempts=attempts,
                result=result,
                failure=failure,
                available_at=_epoch(row.get("available_at"), field="available_at"),
                created_at=_epoch(row.get("created_at"), field="created_at"),
                updated_at=_epoch(row.get("updated_at"), field="updated_at"),
                version=int(row.get("version") or 1),
            )
        except (TypeError, ValueError, JobContractError) as exc:
            raise PostgresJobCorruptionError("job row violates the jobs contract") from exc

    @staticmethod
    def _event_metadata(job: Job) -> str:
        return _dump(
            {
                "contract_version": "jobs-contract-v1",
                "state": job.state.value,
                "attempt_count": job.attempt_count,
                "max_attempts": job.max_attempts,
            }
        ) or "{}"

    @classmethod
    def _write_attempts(cls, cursor: object, job: Job) -> None:
        for attempt in job.attempts:
            cls._execute(
                cursor,
                """
                INSERT INTO rick_ingestion_job_attempts
                    (job_id, attempt_no, worker_id, state, started_at, finished_at, failure)
                VALUES (%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s),CAST(%s AS jsonb))
                ON CONFLICT (job_id, attempt_no) DO UPDATE SET
                    worker_id=EXCLUDED.worker_id,
                    state=EXCLUDED.state,
                    started_at=EXCLUDED.started_at,
                    finished_at=EXCLUDED.finished_at,
                    failure=EXCLUDED.failure
                WHERE rick_ingestion_job_attempts.state = 'RUNNING'
                """,
                (
                    str(job.job_id),
                    attempt.number,
                    str(attempt.worker_id),
                    attempt.state.value,
                    attempt.started_at,
                    attempt.finished_at,
                    _dump(_failure_dict(attempt.failure)),
                ),
            )

    @staticmethod
    def _ensure_attempt_history_mutation(existing: Job, candidate: Job) -> None:
        if len(candidate.attempts) < len(existing.attempts):
            raise PostgresJobError("invalid_transition", "attempt history cannot be truncated")
        for previous, observed in zip(existing.attempts, candidate.attempts):
            if previous == observed:
                continue
            if previous.state is not JobState.RUNNING:
                raise PostgresJobError("invalid_transition", "finished attempt history is immutable")
            if (
                observed.number != previous.number
                or observed.worker_id != previous.worker_id
                or observed.started_at != previous.started_at
                or observed.state is JobState.RUNNING
            ):
                raise PostgresJobError("invalid_transition", "active attempt identity is immutable")

    @staticmethod
    def _require_canonical_row(row: Mapping[str, object]) -> None:
        if row.get("contract_state") is None:
            raise PostgresJobError(
                "invalid_transition",
                "legacy jobs require the Phase 2.3 canonical rewrite",
            )

    @classmethod
    def _write_projection_event(
        cls,
        cursor: object,
        job: Job,
        *,
        event_id: str,
        event_type: str,
        metadata: str,
    ) -> None:
        cls._execute(
            cursor,
            """
            INSERT INTO rick_outbox
                (event_id, tenant_id, aggregate_type, aggregate_id, event_type, payload)
            VALUES (%s,%s,%s,%s,%s,CAST(%s AS jsonb))
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event_id,
                job.tenant_id,
                "job",
                str(job.job_id),
                f"jobs.{event_type}",
                metadata,
            ),
        )
        cls._execute(
            cursor,
            """
            INSERT INTO rick_audit_events
                (event_id, tenant_id, actor_user_id, action, target_type,
                 target_id, workspace_id, metadata)
            VALUES (%s,%s,NULL,%s,%s,%s,%s,CAST(%s AS jsonb))
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event_id,
                job.tenant_id,
                f"jobs.{event_type}",
                "job",
                str(job.job_id),
                job.workspace_id,
                metadata,
            ),
        )

    @classmethod
    def _write_lifecycle_event(
        cls,
        cursor: object,
        job: Job,
        *,
        event_id: str,
        from_state: JobState | None,
        event_type: str,
        metadata: str,
    ) -> None:
        cls._execute(
            cursor,
            """
            INSERT INTO rick_ingestion_job_events
                (event_id, job_id, tenant_id, workspace_id, collection_id,
                 event_type, from_state, to_state, version, metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb))
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event_id,
                str(job.job_id),
                job.tenant_id,
                job.workspace_id,
                job.collection_id,
                event_type,
                None if from_state is None else from_state.value,
                job.state.value,
                job.version,
                metadata,
            ),
        )

    @classmethod
    def _write_event(
        cls,
        cursor: object,
        job: Job,
        *,
        from_state: JobState | None,
        event_type: str,
    ) -> None:
        event_id = f"job:{job.job_id}:{job.version}"
        metadata = cls._event_metadata(job)
        cls._write_lifecycle_event(
            cursor,
            job,
            event_id=event_id,
            from_state=from_state,
            event_type=event_type,
            metadata=metadata,
        )
        cls._write_projection_event(
            cursor,
            job,
            event_id=event_id,
            event_type=event_type,
            metadata=metadata,
        )

    @classmethod
    def _persist(
        cls,
        cursor: object,
        job: Job,
        *,
        expected_version: int,
        from_state: JobState,
        lease: tuple[str | None, str | None, float | None, float | None] | object = _KEEP_LEASE,
        lease_duration: float | None = None,
        lease_guard: JobLease | None = None,
        document_id: str | None | object = _KEEP_LEASE,
        event_type: str = "transition",
    ) -> Job:
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise PostgresJobError("invalid_input", "expected_version is invalid")
        if job.version != expected_version + 1:
            raise PostgresJobConcurrencyError("persisted job version must be expected_version + 1")
        if lease_guard is not None and not isinstance(lease_guard, JobLease):
            raise PostgresJobError("invalid_input", "lease_guard is invalid")
        assignments = [
            "idempotency_key=%s",
            "operation=%s",
            "payload=CAST(%s AS jsonb)",
            "status=%s",
            "contract_state=%s",
            "contract_version=%s",
            "max_attempts=%s",
            "attempts=%s",
            "available_at=to_timestamp(%s)",
            "result=CAST(%s AS jsonb)",
            "failure=CAST(%s AS jsonb)",
            "version=%s",
            "updated_at=to_timestamp(%s)",
        ]
        params: list[object] = [
            job.idempotency_key,
            job.operation,
            _dump(dict(job.payload)),
            _legacy_status(job.state),
            job.state.value,
            "jobs-contract-v1",
            job.max_attempts,
            job.attempt_count,
            job.available_at,
            _dump(_result_dict(job.result)),
            _dump(_failure_dict(job.failure)),
            job.version,
            job.updated_at,
        ]
        if document_id is not _KEEP_LEASE:
            assignments.append("document_id=%s")
            params.append(document_id)
        if lease is not _KEEP_LEASE:
            if lease is None:
                lease_worker, lease_token, acquired_at, expires_at = None, None, None, None
            else:
                lease_worker, lease_token, acquired_at, expires_at = lease  # type: ignore[misc]
            assignments.extend(("lease_worker_id=%s", "lease_owner=%s"))
            params.extend((lease_worker, lease_token))
            if lease_duration is None:
                assignments.extend(
                    (
                        "lease_acquired_at=to_timestamp(%s)",
                        "lease_until=to_timestamp(%s)",
                    )
                )
                params.extend((acquired_at, expires_at))
            else:
                assignments.extend(
                    (
                        "lease_acquired_at=clock_timestamp()",
                        "lease_until=clock_timestamp() + (%s * INTERVAL '1 second')",
                    )
                )
                params.append(lease_duration)
        where = "job_id=%s AND tenant_id=%s AND workspace_id=%s AND collection_id=%s AND version=%s"
        params.extend(
            (
                str(job.job_id),
                job.tenant_id,
                job.workspace_id,
                job.collection_id,
                expected_version,
            )
        )
        if lease_guard is not None:
            where += (
                " AND contract_state='RUNNING' AND lease_worker_id=%s"
                " AND lease_owner=%s AND lease_until > clock_timestamp()"
            )
            params.extend((str(lease_guard.worker_id), str(lease_guard.token)))
        cls._execute(
            cursor,
            f"""
            UPDATE rick_ingestion_jobs
            SET {', '.join(assignments)}
            WHERE {where} AND contract_state IS NOT NULL
            RETURNING {_SELECT_COLUMNS}
            """,
            params,
        )
        row = cls._one(cursor)
        if row is None:
            if lease_guard is not None:
                raise PostgresJobLeaseError("lease expired or was replaced before persistence")
            raise PostgresJobConcurrencyError()
        cls._write_attempts(cursor, job)
        cls._write_event(cursor, job, from_state=from_state, event_type=event_type)
        return cls._decode(cursor, row)

    @classmethod
    def _insert(cls, cursor: object, job: Job) -> Job:
        document_id = job.result.document_id if job.result is not None else None
        cls._execute(
            cursor,
            f"""
            INSERT INTO rick_ingestion_jobs
                (job_id, idempotency_key, tenant_id, workspace_id, collection_id,
                 document_id, operation, status, contract_state, contract_version,
                 payload, max_attempts, attempts, available_at, result, failure, version,
                 created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),%s,%s,
                    to_timestamp(%s),CAST(%s AS jsonb),CAST(%s AS jsonb),%s,
                    to_timestamp(%s),to_timestamp(%s))
            RETURNING {_SELECT_COLUMNS}
            """,
            (
                str(job.job_id),
                job.idempotency_key,
                job.tenant_id,
                job.workspace_id,
                job.collection_id,
                document_id,
                job.operation,
                _legacy_status(job.state),
                job.state.value,
                "jobs-contract-v1",
                _dump(dict(job.payload)),
                job.max_attempts,
                job.attempt_count,
                job.available_at,
                _dump(_result_dict(job.result)),
                _dump(_failure_dict(job.failure)),
                job.version,
                job.created_at,
                job.updated_at,
            ),
        )
        row = cls._one(cursor)
        if row is None:
            raise PostgresJobError("queue_unavailable", "insert returned no job")
        cls._write_attempts(cursor, job)
        cls._write_event(cursor, job, from_state=None, event_type="created")
        return cls._decode(cursor, row)

    def _idempotency_row(self, cursor: object, job: Job, *, lock: bool) -> dict[str, object] | None:
        return self._select_one(
            cursor,
            "tenant_id=%s AND workspace_id=%s AND collection_id=%s AND idempotency_key=%s",
            (
                job.tenant_id,
                job.workspace_id,
                job.collection_id,
                job.idempotency_key,
            ),
            lock=lock,
        )

    @classmethod
    def _lock_scope(cls, cursor: object, scope: JobScope) -> None:
        cls._execute(
            cursor,
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"rick-jobs:{scope.tenant_id}:{scope.workspace_id}:{scope.collection_id}",),
        )

    @staticmethod
    def _check_expected(expected_version: int, observed: int, *, allow_zero: bool = False) -> None:
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise PostgresJobError("invalid_input", "expected_version is invalid")
        if expected_version == 0 and allow_zero:
            return
        if expected_version != observed:
            raise PostgresJobConcurrencyError()

    @staticmethod
    def _queue_candidate(job: Job, *, now: float) -> Job:
        if job.state is JobState.PENDING:
            return job.transition(JobState.QUEUED, now=max(now, job.updated_at))
        if job.state is JobState.QUEUED:
            return job
        raise PostgresJobError("invalid_transition", "only pending or queued jobs can be enqueued")

    def create_or_replay(self, job: Job, *, expected_version: int) -> Job:
        if not isinstance(job, Job):
            raise PostgresJobError("invalid_input", "job is invalid")
        with self._session(write=True) as (_connection, cursor):
            self._lock_scope(cursor, job.scope)
            existing_row = self._idempotency_row(cursor, job, lock=True)
            if existing_row is not None:
                existing = self._decode(cursor, existing_row)
                if expected_version != 0:
                    self._check_expected(expected_version, existing.version)
                try:
                    return ensure_idempotent(existing, job)
                except JobIdempotencyConflictError as exc:
                    raise PostgresJobIdempotencyError() from exc
            self._check_expected(expected_version, 0, allow_zero=True)
            return self._insert(cursor, job)

    def enqueue(self, job: Job, *, expected_version: int) -> Job:
        if not isinstance(job, Job):
            raise PostgresJobError("invalid_input", "job is invalid")
        with self._session(write=True) as (_connection, cursor):
            self._lock_scope(cursor, job.scope)
            existing_row = self._idempotency_row(cursor, job, lock=True)
            if existing_row is not None:
                existing = self._decode(cursor, existing_row)
                if expected_version != 0:
                    self._check_expected(expected_version, existing.version)
                try:
                    existing = ensure_idempotent(existing, job)
                except JobIdempotencyConflictError as exc:
                    raise PostgresJobIdempotencyError() from exc
                if existing_row.get("contract_state") is None:
                    return existing
                if existing.state is JobState.PENDING:
                    queued = self._queue_candidate(existing, now=existing.updated_at)
                    return self._persist(
                        cursor,
                        queued,
                        expected_version=existing.version,
                        from_state=existing.state,
                        lease=None,
                        event_type="enqueued",
                    )
                return existing

            self._execute(
                cursor,
                """
                SELECT COUNT(*) AS count
                FROM rick_ingestion_jobs
                WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s
                  AND contract_state IN ('PENDING','QUEUED','RETRYING','RUNNING')
                """,
                self._scope_params(job.scope),
            )
            count_row = self._one(cursor)
            if int((count_row or {}).get("count") or 0) >= self.max_pending:
                raise PostgresJobError("capacity", "scoped pending capacity is exhausted")
            if expected_version != 0:
                raise PostgresJobConcurrencyError("a new job must use expected_version=0")
            inserted = self._insert(cursor, job)
            if inserted.state is JobState.PENDING:
                queued = self._queue_candidate(inserted, now=inserted.updated_at)
                return self._persist(
                    cursor,
                    queued,
                    expected_version=inserted.version,
                    from_state=inserted.state,
                    lease=None,
                    event_type="enqueued",
                )
            return inserted

    def get(
        self,
        job_id: JobId,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
    ) -> Job | None:
        scope = JobScope(tenant_id, workspace_id, collection_id)
        with self._session() as (_connection, cursor):
            row = self._select_one(
                cursor,
                "job_id=%s AND tenant_id=%s AND workspace_id=%s AND collection_id=%s",
                (str(job_id), *self._scope_params(scope)),
            )
            return None if row is None else self._decode(cursor, row)

    def get_by_idempotency(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        idempotency_key: str,
    ) -> Job | None:
        scope = JobScope(tenant_id, workspace_id, collection_id)
        with self._session() as (_connection, cursor):
            row = self._select_one(
                cursor,
                "tenant_id=%s AND workspace_id=%s AND collection_id=%s AND idempotency_key=%s",
                (*self._scope_params(scope), idempotency_key),
            )
            return None if row is None else self._decode(cursor, row)

    def save(self, job: Job, *, expected_version: int) -> Job:
        if not isinstance(job, Job):
            raise PostgresJobError("invalid_input", "job is invalid")
        with self._session(write=True) as (_connection, cursor):
            row = self._select_one(
                cursor,
                "job_id=%s AND tenant_id=%s AND workspace_id=%s AND collection_id=%s",
                (str(job.job_id), job.tenant_id, job.workspace_id, job.collection_id),
                lock=True,
            )
            if row is None:
                raise PostgresJobNotFoundError()
            self._require_canonical_row(row)
            existing = self._decode(cursor, row)
            self._check_expected(expected_version, existing.version)
            if existing.state is JobState.RUNNING or job.state is JobState.RUNNING:
                raise PostgresJobLeaseError("running jobs require owner-bound lifecycle operations")
            try:
                ensure_idempotent(existing, job)
            except JobIdempotencyConflictError as exc:
                raise PostgresJobIdempotencyError() from exc
            self._ensure_attempt_history_mutation(existing, job)
            return self._persist(
                cursor,
                job,
                expected_version=expected_version,
                from_state=existing.state,
            )

    def transition(self, job: Job, to_state: JobState, *, now: float, expected_version: int) -> Job:
        with self._session(write=True) as (_connection, cursor):
            row = self._select_one(
                cursor,
                "job_id=%s AND tenant_id=%s AND workspace_id=%s AND collection_id=%s",
                (str(job.job_id), job.tenant_id, job.workspace_id, job.collection_id),
                lock=True,
            )
            if row is None:
                raise PostgresJobNotFoundError()
            self._require_canonical_row(row)
            existing = self._decode(cursor, row)
            self._check_expected(expected_version, existing.version)
            if existing != job:
                raise PostgresJobConcurrencyError("caller job snapshot is stale")
            if existing.state is JobState.RUNNING and to_state is JobState.CANCELLED:
                raise PostgresJobLeaseError("running jobs require owner-bound cancellation")
            try:
                next_job = existing.transition(to_state, now=_time(now))
            except JobContractError as exc:
                raise PostgresJobError("invalid_transition", str(exc)) from exc
            return self._persist(
                cursor,
                next_job,
                expected_version=expected_version,
                from_state=existing.state,
                lease=None if next_job.state is not JobState.RUNNING else _KEEP_LEASE,
            )

    def schedule(self, job: Job, *, available_at: float, expected_version: int) -> Job:
        target = _time(available_at, field="available_at")
        if job.state is JobState.RETRYING:
            scheduled = job.transition(JobState.QUEUED, now=max(target, job.updated_at), available_at=target)
        elif job.state is JobState.QUEUED:
            scheduled = replace(
                job,
                available_at=max(target, job.created_at),
                updated_at=max(target, job.updated_at),
                version=job.version + 1,
            )
        else:
            raise PostgresJobError("invalid_transition", "only retrying or queued jobs can be scheduled")
        return self.save(scheduled, expected_version=expected_version)

    def _recover_expired(self, cursor: object, scope: JobScope, *, now: float) -> int:
        rows = self._select_many(
            cursor,
            """
            tenant_id=%s AND workspace_id=%s AND collection_id=%s
            AND contract_state='RUNNING'
            AND lease_until IS NOT NULL AND lease_until <= clock_timestamp()
            """,
            self._scope_params(scope),
            lock=True,
            skip_locked=True,
        )
        recovered = 0
        for row in rows:
            job = self._decode(cursor, row)
            if not job.attempts or job.attempts[-1].state is not JobState.RUNNING:
                raise PostgresJobCorruptionError("running job has no active attempt")
            recovery_now = max(now, job.updated_at)
            failure = JobFailure(
                code="lease_expired",
                message="worker lease expired before completion",
                retryable=True,
                attempt=job.attempt_count,
                occurred_at=recovery_now,
            )
            failed = job.finish_attempt(JobState.FAILED, now=recovery_now, failure=failure)
            failed = self._persist(
                cursor,
                failed,
                expected_version=job.version,
                from_state=job.state,
                lease=None,
                event_type="lease_expired",
            )
            if failed.retry_eligible:
                retrying = failed.transition(JobState.RETRYING, now=recovery_now)
                retrying = self._persist(
                    cursor,
                    retrying,
                    expected_version=failed.version,
                    from_state=failed.state,
                    lease=None,
                    event_type="retrying",
                )
                queued = retrying.transition(
                    JobState.QUEUED,
                    now=recovery_now,
                    available_at=recovery_now + self._backoff(retrying.attempt_count),
                )
                self._persist(
                    cursor,
                    queued,
                    expected_version=retrying.version,
                    from_state=retrying.state,
                    lease=None,
                    event_type="requeued",
                )
            else:
                dead = failed.transition(JobState.DEAD_LETTER, now=recovery_now, failure=failed.failure)
                self._persist(
                    cursor,
                    dead,
                    expected_version=failed.version,
                    from_state=failed.state,
                    lease=None,
                    event_type="dead_lettered",
                )
            recovered += 1
        return recovered

    def _backoff(self, attempt: int) -> float:
        bounded_power = 2 ** min(max(0, attempt - 1), 16)
        return min(86_400.0, self.backoff_seconds * bounded_power)

    def claim(
        self,
        *,
        worker_id: WorkerId,
        scope: JobScope,
        expected_versions: Mapping[JobId, int],
        limit: int = 1,
        now: float,
    ) -> tuple[tuple[Job, JobLease], ...]:
        if not isinstance(scope, JobScope):
            raise PostgresJobError("invalid_input", "scope is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise PostgresJobError("invalid_input", "limit is out of range")
        now = _time(now, field="now")
        worker = WorkerId(str(worker_id))
        with self._session(write=True) as (_connection, cursor):
            self._recover_expired(cursor, scope, now=now)
            rows = self._select_many(
                cursor,
                """
                tenant_id=%s AND workspace_id=%s AND collection_id=%s
                AND contract_state='QUEUED' AND available_at <= clock_timestamp()
                """,
                self._scope_params(scope),
                limit=limit,
                lock=True,
                skip_locked=True,
            )
            claimed: list[tuple[Job, JobLease]] = []
            for row in rows:
                job = self._decode(cursor, row)
                if job.job_id not in expected_versions:
                    raise PostgresJobConcurrencyError("claim requires an expected version for every selected job")
                expected = expected_versions[job.job_id]
                self._check_expected(expected, job.version)
                try:
                    running = job.start_attempt(worker_id=worker, now=now)
                except JobContractError as exc:
                    raise PostgresJobError("invalid_transition", str(exc)) from exc
                token = f"lease-{secrets.token_urlsafe(24)}"
                persisted = self._persist(
                    cursor,
                    running,
                    expected_version=expected,
                    from_state=job.state,
                    lease=(str(worker), token, None, None),
                    lease_duration=self.lease_seconds,
                    event_type="claimed",
                )
                lease_row = self._select_one(
                    cursor,
                    "job_id=%s AND tenant_id=%s AND workspace_id=%s AND collection_id=%s",
                    (str(persisted.job_id), *self._scope_params(scope)),
                    lock=True,
                )
                if lease_row is None:
                    raise PostgresJobLeaseError("claim did not return its durable lease")
                acquired = _epoch(lease_row.get("lease_acquired_at"), field="lease_acquired_at")
                expires = _epoch(lease_row.get("lease_until"), field="lease_until")
                lease = JobLease(
                    job_id=persisted.job_id,
                    scope=persisted.scope,
                    worker_id=worker,
                    token=token,
                    acquired_at=acquired,
                    expires_at=expires,
                    heartbeat_at=acquired,
                )
                claimed.append((persisted, lease))
            return tuple(claimed)

    def _lock_lease(
        self,
        cursor: object,
        lease: JobLease,
        *,
        expected_version: int,
        now: float,
    ) -> tuple[dict[str, object], Job]:
        _time(now, field="now")
        row = self._select_one(
            cursor,
            """
            job_id=%s AND tenant_id=%s AND workspace_id=%s AND collection_id=%s
            AND contract_state='RUNNING' AND lease_worker_id=%s AND lease_owner=%s
            AND version=%s AND lease_until IS NOT NULL
            AND lease_until > clock_timestamp()
            """,
            (
                str(lease.job_id),
                *self._scope_params(lease.scope),
                str(lease.worker_id),
                str(lease.token),
                expected_version,
            ),
            lock=True,
        )
        if row is None:
            raise PostgresJobLeaseError()
        job = self._decode(cursor, row)
        if not lease.matches(job, worker_id=lease.worker_id, token=lease.token):
            raise PostgresJobLeaseError("lease scope or owner does not match the durable row")
        if job.version != expected_version:
            raise PostgresJobConcurrencyError()
        return row, job

    def heartbeat(self, lease: JobLease, *, now: float, expected_version: int) -> JobLease:
        if not isinstance(lease, JobLease):
            raise PostgresJobError("invalid_input", "lease is invalid")
        now = _time(now, field="now")
        with self._session(write=True) as (_connection, cursor):
            _row, job = self._lock_lease(cursor, lease, expected_version=expected_version, now=now)
            self._execute(
                cursor,
                """
                UPDATE rick_ingestion_jobs
                SET lease_until=clock_timestamp() + (%s * INTERVAL '1 second')
                WHERE job_id=%s AND tenant_id=%s AND workspace_id=%s
                  AND collection_id=%s AND contract_state='RUNNING'
                  AND lease_worker_id=%s AND lease_owner=%s AND version=%s
                  AND lease_until > clock_timestamp()
                RETURNING lease_acquired_at, lease_until,
                          EXTRACT(EPOCH FROM clock_timestamp()) AS database_now
                """,
                (
                    self.lease_seconds,
                    str(lease.job_id),
                    *self._scope_params(lease.scope),
                    str(lease.worker_id),
                    str(lease.token),
                    expected_version,
                ),
            )
            updated = self._one(cursor)
            if updated is None:
                raise PostgresJobLeaseError()
            acquired = _epoch(updated.get("lease_acquired_at"), field="lease_acquired_at")
            durable_expires = _epoch(updated.get("lease_until"), field="lease_until")
            database_now = _epoch(updated.get("database_now"), field="database_now")
            heartbeat_event_id = f"job:{job.job_id}:heartbeat:{secrets.token_hex(8)}"
            heartbeat_metadata = _dump(
                {
                    "contract_version": "jobs-contract-v1",
                    "state": job.state.value,
                    "worker_id": str(lease.worker_id),
                }
            ) or "{}"
            self._write_lifecycle_event(
                cursor,
                job,
                event_id=heartbeat_event_id,
                from_state=job.state,
                event_type="lease_heartbeat",
                metadata=heartbeat_metadata,
            )
            self._write_projection_event(
                cursor,
                job,
                event_id=heartbeat_event_id,
                event_type="lease_heartbeat",
                metadata=heartbeat_metadata,
            )
            return JobLease(
                job_id=lease.job_id,
                scope=lease.scope,
                worker_id=lease.worker_id,
                token=lease.token,
                acquired_at=acquired,
                expires_at=durable_expires,
                heartbeat_at=database_now,
            )

    def acknowledge(
        self,
        lease: JobLease,
        result: JobResult,
        *,
        now: float,
        expected_version: int,
    ) -> Job:
        if not isinstance(result, JobResult):
            raise PostgresJobError("invalid_input", "result is invalid")
        now = _time(now, field="now")
        with self._session(write=True) as (_connection, cursor):
            _row, job = self._lock_lease(cursor, lease, expected_version=expected_version, now=now)
            try:
                succeeded = job.finish_attempt(JobState.SUCCEEDED, now=now, result=result)
            except JobContractError as exc:
                raise PostgresJobError("invalid_transition", str(exc)) from exc
            return self._persist(
                cursor,
                succeeded,
                expected_version=expected_version,
                from_state=job.state,
                lease=None,
                lease_guard=lease,
                document_id=result.document_id if result.document_id is not None else _KEEP_LEASE,
                event_type="acknowledged",
            )

    def fail(
        self,
        lease: JobLease,
        failure: JobFailure,
        *,
        now: float,
        expected_version: int,
    ) -> Job:
        if not isinstance(failure, JobFailure):
            raise PostgresJobError("invalid_input", "failure is invalid")
        now = _time(now, field="now")
        with self._session(write=True) as (_connection, cursor):
            _row, job = self._lock_lease(cursor, lease, expected_version=expected_version, now=now)
            try:
                failed = job.finish_attempt(JobState.FAILED, now=now, failure=failure)
            except JobContractError as exc:
                raise PostgresJobError("invalid_transition", str(exc)) from exc
            failed = self._persist(
                cursor,
                failed,
                expected_version=expected_version,
                from_state=job.state,
                lease=None,
                lease_guard=lease,
                event_type="failed",
            )
            if failed.retry_eligible:
                retrying = failed.transition(JobState.RETRYING, now=now)
                retrying = self._persist(
                    cursor,
                    retrying,
                    expected_version=failed.version,
                    from_state=failed.state,
                    lease=None,
                    event_type="retrying",
                )
                queued = retrying.transition(
                    JobState.QUEUED,
                    now=now,
                    available_at=now + self._backoff(retrying.attempt_count),
                )
                return self._persist(
                    cursor,
                    queued,
                    expected_version=retrying.version,
                    from_state=retrying.state,
                    lease=None,
                    event_type="requeued",
                )
            dead = failed.transition(JobState.DEAD_LETTER, now=now, failure=failed.failure)
            return self._persist(
                cursor,
                dead,
                expected_version=failed.version,
                from_state=failed.state,
                lease=None,
                event_type="dead_lettered",
            )

    def cancel(
        self,
        job_id: JobId,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        now: float,
        expected_version: int,
    ) -> Job:
        scope = JobScope(tenant_id, workspace_id, collection_id)
        with self._session(write=True) as (_connection, cursor):
            row = self._select_one(
                cursor,
                "job_id=%s AND tenant_id=%s AND workspace_id=%s AND collection_id=%s",
                (str(job_id), *self._scope_params(scope)),
                lock=True,
            )
            if row is None:
                raise PostgresJobNotFoundError()
            job = self._decode(cursor, row)
            self._require_canonical_row(row)
            self._check_expected(expected_version, job.version)
            if job.state is JobState.RUNNING:
                raise PostgresJobLeaseError("running jobs require owner-bound cancellation")
            try:
                cancelled = job.transition(JobState.CANCELLED, now=_time(now))
            except JobContractError as exc:
                raise PostgresJobError("invalid_transition", str(exc)) from exc
            return self._persist(
                cursor,
                cancelled,
                expected_version=expected_version,
                from_state=job.state,
                lease=None,
                event_type="cancelled",
            )

    def replay_dead_letter(
        self,
        job_id: JobId,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        replay_job_id: str,
        replay_idempotency_key: str,
        now: float,
        expected_version: int,
        max_attempts: int | None = None,
    ) -> Job:
        scope = JobScope(tenant_id, workspace_id, collection_id)
        now = _time(now, field="now")
        with self._session(write=True) as (_connection, cursor):
            self._lock_scope(cursor, scope)
            row = self._select_one(
                cursor,
                "job_id=%s AND tenant_id=%s AND workspace_id=%s AND collection_id=%s",
                (str(job_id), *self._scope_params(scope)),
                lock=True,
            )
            if row is None:
                raise PostgresJobNotFoundError()
            original = self._decode(cursor, row)
            self._require_canonical_row(row)
            self._check_expected(expected_version, original.version)
            if original.state is not JobState.DEAD_LETTER:
                raise PostgresJobError("invalid_transition", "only dead-letter jobs can be replayed")
            attempts = original.max_attempts if max_attempts is None else max_attempts
            try:
                candidate = Job.create(
                    job_id=replay_job_id,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    collection_id=scope.collection_id,
                    operation=original.operation,
                    idempotency_key=replay_idempotency_key,
                    payload=dict(original.payload),
                    now=now,
                    max_attempts=attempts,
                )
            except JobContractError as exc:
                raise PostgresJobError("invalid_input", str(exc)) from exc
            existing_row = self._idempotency_row(cursor, candidate, lock=True)
            if existing_row is not None:
                existing = self._decode(cursor, existing_row)
                try:
                    return ensure_idempotent(existing, candidate)
                except JobIdempotencyConflictError as exc:
                    raise PostgresJobIdempotencyError() from exc
            inserted = self._insert(cursor, candidate)
            queued = candidate.transition(JobState.QUEUED, now=now)
            return self._persist(
                cursor,
                queued,
                expected_version=inserted.version,
                from_state=candidate.state,
                lease=None,
                event_type="replay_enqueued",
            )

    def list_dead_letters(self, *, scope: JobScope, limit: int = 100) -> tuple[Job, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise PostgresJobError("invalid_input", "limit is out of range")
        with self._session() as (_connection, cursor):
            rows = self._select_many(
                cursor,
                "tenant_id=%s AND workspace_id=%s AND collection_id=%s AND contract_state='DEAD_LETTER'",
                self._scope_params(scope),
                limit=limit,
            )
            return tuple(self._decode(cursor, row) for row in rows)

    def prune_terminal(self, *, scope: JobScope, older_than: float, limit: int = 100) -> int:
        cutoff = _time(older_than, field="older_than")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
            raise PostgresJobError("invalid_input", "limit is out of range")
        with self._session(write=True) as (_connection, cursor):
            rows = self._select_many(
                cursor,
                """
                tenant_id=%s AND workspace_id=%s AND collection_id=%s
                AND contract_state IN ('SUCCEEDED','CANCELLED','DEAD_LETTER')
                AND updated_at < to_timestamp(%s)
                """,
                (*self._scope_params(scope), cutoff),
                limit=limit,
                lock=True,
                skip_locked=True,
            )
            removed = 0
            for row in rows:
                job = self._decode(cursor, row)
                event_id = f"job:{job.job_id}:retention:{secrets.token_hex(8)}"
                metadata = _dump(
                    {
                        "contract_version": "jobs-contract-v1",
                        "state": job.state.value,
                        "attempt_count": job.attempt_count,
                        "retention_cutoff": cutoff,
                    }
                ) or "{}"
                self._write_lifecycle_event(
                    cursor,
                    job,
                    event_id=event_id,
                    from_state=job.state,
                    event_type="retention_pruned",
                    metadata=metadata,
                )
                self._write_projection_event(
                    cursor,
                    job,
                    event_id=event_id,
                    event_type="retention_pruned",
                    metadata=metadata,
                )
                self._execute(
                    cursor,
                    """
                    DELETE FROM rick_ingestion_jobs
                    WHERE job_id=%s AND tenant_id=%s AND workspace_id=%s
                      AND collection_id=%s
                    """,
                    (str(job.job_id), *self._scope_params(scope)),
                )
                removed += max(0, int(getattr(cursor, "rowcount", 0) or 0))
            return removed

    def health_check(self) -> bool:
        try:
            with self._session() as (_connection, cursor):
                self._execute(cursor, "SELECT 1")
                return self._one(cursor) is not None
        except PostgresJobError:
            return False

    def close(self) -> None:
        self._closed = True


def cls_default_max_attempts(row: Mapping[str, object]) -> int:
    """Use the legacy default only when reading pre-0004 rows in a test seam."""

    raw = row.get("max_attempts")
    if raw is None:
        return 3
    return int(raw)


PostgresCanonicalJobQueue = PostgresJobQueue


__all__ = [
    "DbConnection",
    "PostgresCanonicalJobQueue",
    "PostgresJobConcurrencyError",
    "PostgresJobCorruptionError",
    "PostgresJobError",
    "PostgresJobIdempotencyError",
    "PostgresJobLeaseError",
    "PostgresJobNotFoundError",
    "PostgresJobQueue",
]
