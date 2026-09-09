"""Canonical, adapter-neutral durable job contracts.

This module deliberately contains no persistence or transport implementation.
It is the shared boundary between API admission, durable queues and workers.
Values are bounded and serializable so adapters cannot silently persist raw
documents, provider responses or credential material in a job envelope.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import json
import math
import re
from types import MappingProxyType
from typing import NewType, Protocol, TypeAlias, runtime_checkable


CONTRACT_VERSION = "jobs-contract-v1"
MAX_IDENTIFIER_LENGTH = 128
MAX_OPERATION_LENGTH = 64
MAX_ERROR_CODE_LENGTH = 64
MAX_MESSAGE_LENGTH = 256
MAX_PAYLOAD_FIELDS = 32
MAX_PAYLOAD_KEY_LENGTH = 64
MAX_PAYLOAD_VALUE_LENGTH = 512
MAX_METADATA_FIELDS = 32
MAX_ATTEMPTS = 64

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_FIELD = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_METADATA_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@?=&%+~,\-]{0,511}$")
_SENSITIVE_METADATA_VALUE = re.compile(
    r"(?ix)"
    r"(?:^|[^a-z0-9])(?:sk|pk|rk|ghp|glpat|xox[baprs])_[a-z0-9_-]*(?:$|[^a-z0-9])"
    r"|(?:bearer|basic)\s+[a-z0-9._~+/=-]{8,}"
    r"|(?:api[_-]?key|authorization|password|secret|token|private[_ -]?key)\s*[:=]"
    r"|(?:raw[-_. ]?(?:document[-_. ]?)?(?:content|body|text))"
    r"|(?:(?:full[-_. ]?)?document[-_. ]?(?:content|body|text))"
    r"|(?:provider[-_. ]?(?:response|result))"
    r"|-----begin[-_ ]*(?:private|secret)?[-_ ]*key-----"
)
_SAFE_METADATA_KEYS = frozenset(
    {
        "attempt_id",
        "bytes",
        "checksum",
        "chunk_id",
        "collection_id",
        "document_id",
        "etag",
        "filename",
        "hash",
        "index_version",
        "job_id",
        "lease_id",
        "mime_type",
        "model_id",
        "object_key",
        "operation",
        "page",
        "provider_id",
        "schema_version",
        "section",
        "size",
        "source_key",
        "stage",
        "state",
        "status",
        "tenant_id",
        "trace_id",
        "uri",
        "url",
        "version",
        "vector_id",
        "workspace_id",
    }
)
_FORBIDDEN_FIELD_PARTS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "credential",
        "content",
        "document_text",
        "password",
        "pem",
        "prompt",
        "private",
        "provider_response",
        "provider_result",
        "raw_content",
        "response",
        "result",
        "secret",
        "token",
        "text",
    }
)

JobId = NewType("JobId", str)
WorkerId = NewType("WorkerId", str)
LeaseToken = NewType("LeaseToken", str)
JobPayload: TypeAlias = Mapping[str, str]
JobMetadata: TypeAlias = Mapping[str, str]


class JobContractError(ValueError):
    """Base error for malformed or unsafe contract values."""


class JobValidationError(JobContractError):
    """A value does not satisfy the bounded job contract."""


class JobIdempotencyConflictError(JobContractError):
    """An idempotency key was reused for a different immutable request."""


class InvalidTransitionError(JobContractError):
    """A job state transition is not permitted by the contract."""


class JobState(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RETRYING = "RETRYING"
    DEAD_LETTER = "DEAD_LETTER"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.CANCELLED, self.DEAD_LETTER}


@dataclass(frozen=True, slots=True)
class JobScope:
    """The complete authorization and uniqueness scope of a job."""

    tenant_id: str
    workspace_id: str
    collection_id: str

    def __post_init__(self) -> None:
        for name in ("tenant_id", "workspace_id", "collection_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), field_name=name))


_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.PENDING: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.CANCELLED}),
    JobState.RUNNING: frozenset(
        {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.FAILED: frozenset({JobState.RETRYING, JobState.DEAD_LETTER}),
    JobState.RETRYING: frozenset({JobState.QUEUED, JobState.DEAD_LETTER, JobState.CANCELLED}),
    JobState.SUCCEEDED: frozenset(),
    JobState.CANCELLED: frozenset(),
    JobState.DEAD_LETTER: frozenset(),
}


def allowed_transitions(state: JobState) -> frozenset[JobState]:
    """Return the immutable transition set for *state*."""

    try:
        return _TRANSITIONS[JobState(state)]
    except (KeyError, ValueError) as exc:
        raise JobValidationError("state is invalid") from exc


def can_transition(from_state: JobState, to_state: JobState) -> bool:
    """Return whether the state machine permits the requested transition."""

    try:
        return JobState(to_state) in allowed_transitions(JobState(from_state))
    except (TypeError, ValueError, JobValidationError):
        return False


def _text(value: object, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise JobValidationError(f"{field_name} must be text")
    result = value.strip()
    if not result or len(result) > maximum or "\x00" in result:
        raise JobValidationError(f"{field_name} is invalid")
    if any(ord(char) < 0x20 and char not in "\t" for char in result):
        raise JobValidationError(f"{field_name} contains a control character")
    return result


def _identifier(value: object, *, field_name: str) -> str:
    result = _text(value, field_name=field_name, maximum=MAX_IDENTIFIER_LENGTH)
    if not _IDENTIFIER.fullmatch(result):
        raise JobValidationError(f"{field_name} is not a valid identifier")
    return result


def _field_name(value: object, *, field_name: str) -> str:
    result = _text(value, field_name=field_name, maximum=MAX_PAYLOAD_KEY_LENGTH).lower()
    if not _FIELD.fullmatch(result):
        raise JobValidationError(f"{field_name} is not a valid field name")
    if any(
        forbidden in part
        for part in result.split(".")
        for forbidden in _FORBIDDEN_FIELD_PARTS
    ):
        raise JobValidationError(f"{field_name} is sensitive or untrusted")
    return result


def _metadata_key(value: object, *, field_name: str) -> str:
    key = _field_name(value, field_name=field_name)
    if key not in _SAFE_METADATA_KEYS and not key.endswith(
        ("_id", "_key", "_ref", "_version", "_hash", "_checksum", "_uri", "_url")
    ):
        raise JobValidationError(f"{field_name} is not an approved metadata field")
    return key


def _bounded_map(
    value: Mapping[str, str],
    *,
    field_name: str,
    maximum_fields: int,
    value_limit: int,
) -> MappingProxyType[str, str]:
    if not isinstance(value, Mapping):
        raise JobValidationError(f"{field_name} must be a mapping")
    if len(value) > maximum_fields:
        raise JobValidationError(f"{field_name} has too many fields")
    clean: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _metadata_key(raw_key, field_name=f"{field_name}.key")
        clean_value = _text(raw_value, field_name=f"{field_name}.{key}", maximum=value_limit)
        if not _METADATA_VALUE.fullmatch(clean_value):
            raise JobValidationError(f"{field_name}.{key} must be a compact metadata reference")
        if _SENSITIVE_METADATA_VALUE.search(clean_value):
            raise JobValidationError(f"{field_name}.{key} looks like secret or raw content")
        clean[key] = clean_value
    return MappingProxyType(dict(sorted(clean.items())))


def _timestamp(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobValidationError(f"{field_name} must be a finite timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise JobValidationError(f"{field_name} must be a finite timestamp")
    return result


def _attempt_number(value: object, *, field_name: str = "attempt") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_ATTEMPTS:
        raise JobValidationError(f"{field_name} is out of range")
    return value


@dataclass(frozen=True, slots=True)
class JobFailure:
    code: str
    message: str
    retryable: bool
    attempt: int
    occurred_at: float

    def __post_init__(self) -> None:
        code = _text(self.code, field_name="failure.code", maximum=MAX_ERROR_CODE_LENGTH).lower()
        if not _SAFE_ERROR.fullmatch(code) or any(
            forbidden in part
            for part in code.split(".")
            for forbidden in _FORBIDDEN_FIELD_PARTS
        ):
            raise JobValidationError("failure.code is invalid")
        object.__setattr__(self, "code", code)
        object.__setattr__(
            self,
            "message",
            _text(self.message, field_name="failure.message", maximum=MAX_MESSAGE_LENGTH),
        )
        if not isinstance(self.retryable, bool):
            raise JobValidationError("failure.retryable must be boolean")
        object.__setattr__(self, "attempt", _attempt_number(self.attempt, field_name="failure.attempt"))
        object.__setattr__(
            self,
            "occurred_at",
            _timestamp(self.occurred_at, field_name="failure.occurred_at"),
        )


def _failure_dict(failure: JobFailure) -> dict[str, object]:
    return {
        "code": failure.code,
        "message": failure.message,
        "retryable": failure.retryable,
        "attempt": failure.attempt,
        "occurred_at": failure.occurred_at,
    }


@dataclass(frozen=True, slots=True)
class JobResult:
    output_refs: JobMetadata = field(default_factory=dict)
    document_id: str | None = None
    completed_at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "output_refs",
            _bounded_map(
                self.output_refs,
                field_name="result.output_refs",
                maximum_fields=MAX_METADATA_FIELDS,
                value_limit=MAX_PAYLOAD_VALUE_LENGTH,
            ),
        )
        if self.document_id is not None:
            object.__setattr__(self, "document_id", _identifier(self.document_id, field_name="result.document_id"))
        object.__setattr__(self, "completed_at", _timestamp(self.completed_at, field_name="result.completed_at"))


@dataclass(frozen=True, slots=True)
class JobLease:
    job_id: JobId
    scope: JobScope
    worker_id: WorkerId
    token: LeaseToken
    acquired_at: float
    expires_at: float
    heartbeat_at: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", JobId(_identifier(self.job_id, field_name="lease.job_id")))
        if not isinstance(self.scope, JobScope):
            raise JobValidationError("lease.scope is invalid")
        object.__setattr__(self, "worker_id", WorkerId(_identifier(self.worker_id, field_name="lease.worker_id")))
        object.__setattr__(self, "token", LeaseToken(_identifier(self.token, field_name="lease.token")))
        acquired = _timestamp(self.acquired_at, field_name="lease.acquired_at")
        expires = _timestamp(self.expires_at, field_name="lease.expires_at")
        heartbeat = _timestamp(self.heartbeat_at, field_name="lease.heartbeat_at")
        if expires <= acquired:
            raise JobValidationError("lease.expires_at must be after lease.acquired_at")
        if not acquired <= heartbeat <= expires:
            raise JobValidationError("lease.heartbeat_at must be within the lease window")
        object.__setattr__(self, "acquired_at", acquired)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(self, "heartbeat_at", heartbeat)

    def active_at(self, now: float) -> bool:
        timestamp = _timestamp(now, field_name="now")
        return self.acquired_at <= timestamp < self.expires_at

    def matches(
        self,
        job: "Job",
        *,
        worker_id: WorkerId,
        token: LeaseToken,
    ) -> bool:
        """Return whether this lease is bound to the exact job scope and owner."""

        return (
            self.job_id == job.job_id
            and self.scope == job.scope
            and self.worker_id == worker_id
            and self.token == token
        )


@dataclass(frozen=True, slots=True)
class JobAttempt:
    number: int
    worker_id: WorkerId
    state: JobState
    started_at: float
    finished_at: float | None = None
    failure: JobFailure | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "number", _attempt_number(self.number, field_name="attempt.number"))
        if self.worker_id is None:
            raise JobValidationError("attempt.worker_id is required")
        object.__setattr__(self, "worker_id", WorkerId(_identifier(self.worker_id, field_name="attempt.worker_id")))
        try:
            state = JobState(self.state)
        except (TypeError, ValueError) as exc:
            raise JobValidationError("attempt.state is invalid") from exc
        if state not in {
            JobState.RUNNING,
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
        }:
            raise JobValidationError("attempt.state is not an attempt lifecycle state")
        object.__setattr__(self, "state", state)
        started = _timestamp(self.started_at, field_name="attempt.started_at")
        object.__setattr__(self, "started_at", started)
        if self.finished_at is not None:
            finished = _timestamp(self.finished_at, field_name="attempt.finished_at")
            if finished < started:
                raise JobValidationError("attempt.finished_at precedes attempt.started_at")
            object.__setattr__(self, "finished_at", finished)
        if self.failure is not None and not isinstance(self.failure, JobFailure):
            raise JobValidationError("attempt.failure is invalid")
        if state is JobState.RUNNING:
            if self.finished_at is not None or self.failure is not None:
                raise JobValidationError("running attempts cannot be finished or failed")
        elif self.finished_at is None:
            raise JobValidationError("finished attempts require finished_at")
        elif state is JobState.FAILED:
            if self.failure is None or self.failure.attempt != self.number:
                raise JobValidationError("failed attempts require their matching failure")
            if self.failure.occurred_at < started:
                raise JobValidationError("attempt.failure.occurred_at precedes attempt.started_at")
            if self.failure.occurred_at > self.finished_at:
                raise JobValidationError("attempt.failure.occurred_at is after attempt.finished_at")
        elif self.failure is not None:
            raise JobValidationError("only failed attempts may contain a failure")

    def as_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "worker_id": self.worker_id,
            "state": self.state.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "failure": None if self.failure is None else _failure_dict(self.failure),
        }


@dataclass(frozen=True, slots=True)
class Job:
    job_id: JobId
    tenant_id: str
    workspace_id: str
    collection_id: str
    operation: str
    idempotency_key: str
    payload: JobPayload
    state: JobState = JobState.PENDING
    max_attempts: int = 3
    attempts: tuple[JobAttempt, ...] = ()
    result: JobResult | None = None
    failure: JobFailure | None = None
    available_at: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", JobId(_identifier(self.job_id, field_name="job_id")))
        for name in ("tenant_id", "workspace_id", "collection_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), field_name=name))
        object.__setattr__(self, "operation", _text(self.operation, field_name="operation", maximum=MAX_OPERATION_LENGTH))
        object.__setattr__(
            self,
            "idempotency_key",
            _identifier(self.idempotency_key, field_name="idempotency_key"),
        )
        object.__setattr__(
            self,
            "payload",
            _bounded_map(
                self.payload,
                field_name="payload",
                maximum_fields=MAX_PAYLOAD_FIELDS,
                value_limit=MAX_PAYLOAD_VALUE_LENGTH,
            ),
        )
        try:
            state = JobState(self.state)
        except (TypeError, ValueError) as exc:
            raise JobValidationError("state is invalid") from exc
        object.__setattr__(self, "state", state)
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or not 0 < self.max_attempts <= MAX_ATTEMPTS:
            raise JobValidationError("max_attempts is out of range")
        if not isinstance(self.attempts, Sequence) or len(self.attempts) > MAX_ATTEMPTS:
            raise JobValidationError("attempts is invalid")
        attempts = tuple(self.attempts)
        if any(not isinstance(attempt, JobAttempt) for attempt in attempts):
            raise JobValidationError("attempts contains an invalid value")
        if tuple(attempt.number for attempt in attempts) != tuple(range(1, len(attempts) + 1)):
            raise JobValidationError("attempt numbers must be contiguous")
        if len(attempts) > self.max_attempts:
            raise JobValidationError("attempt count exceeds max_attempts")
        for previous, current in zip(attempts, attempts[1:]):
            if previous.finished_at is None or current.started_at < previous.finished_at:
                raise JobValidationError("attempt history is not chronological")
        object.__setattr__(self, "attempts", attempts)
        if self.result is not None and not isinstance(self.result, JobResult):
            raise JobValidationError("result is invalid")
        if self.failure is not None and not isinstance(self.failure, JobFailure):
            raise JobValidationError("failure is invalid")
        for name in ("available_at", "created_at", "updated_at"):
            object.__setattr__(self, name, _timestamp(getattr(self, name), field_name=name))
        if self.available_at < self.created_at:
            raise JobValidationError("available_at precedes created_at")
        if self.updated_at < self.created_at:
            raise JobValidationError("updated_at precedes created_at")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise JobValidationError("version is invalid")
        for attempt in attempts:
            if attempt.started_at < self.created_at or attempt.started_at > self.updated_at:
                raise JobValidationError("attempt.started_at is outside the job lifetime")
            if attempt.finished_at is not None and attempt.finished_at > self.updated_at:
                raise JobValidationError("attempt.finished_at is after job.updated_at")
            if attempt.failure is not None and not self.created_at <= attempt.failure.occurred_at <= self.updated_at:
                raise JobValidationError("attempt.failure.occurred_at is outside the job lifetime")
        if self.result is not None and not self.created_at <= self.result.completed_at <= self.updated_at:
            raise JobValidationError("result.completed_at is outside the job lifetime")
        if self.failure is not None and not self.created_at <= self.failure.occurred_at <= self.updated_at:
            raise JobValidationError("failure.occurred_at is outside the job lifetime")

        last_attempt = attempts[-1] if attempts else None
        if self.state is JobState.PENDING:
            if attempts or self.result is not None or self.failure is not None:
                raise JobValidationError("pending jobs cannot contain execution history")
        elif self.state is JobState.QUEUED:
            if self.result is not None or self.failure is not None:
                raise JobValidationError("queued jobs cannot contain a result or active failure")
            if last_attempt is not None and last_attempt.state is not JobState.FAILED:
                raise JobValidationError("queued jobs may only resume after a failed attempt")
            if last_attempt is not None and (
                last_attempt.failure is None
                or not last_attempt.failure.retryable
                or self.attempt_count >= self.max_attempts
            ):
                raise JobValidationError("queued jobs may only resume when retry remains eligible")
        elif self.state is JobState.RUNNING:
            if last_attempt is None or last_attempt.state is not JobState.RUNNING:
                raise JobValidationError("running jobs require an active attempt")
            if self.result is not None or self.failure is not None:
                raise JobValidationError("running jobs cannot contain a result or failure")
        elif self.state is JobState.SUCCEEDED:
            if last_attempt is None or last_attempt.state is not JobState.SUCCEEDED:
                raise JobValidationError("succeeded jobs require a succeeded attempt")
            if self.result is None or self.failure is not None:
                raise JobValidationError("succeeded jobs require only a result")
        elif self.state in {JobState.FAILED, JobState.RETRYING, JobState.DEAD_LETTER}:
            if last_attempt is None or last_attempt.state is not JobState.FAILED:
                raise JobValidationError(f"{self.state.value.lower()} jobs require a failed attempt")
            if self.failure is None or self.failure.attempt != last_attempt.number:
                raise JobValidationError(f"{self.state.value.lower()} jobs require their latest failure")
            if self.failure != last_attempt.failure:
                raise JobValidationError(f"{self.state.value.lower()} job failure differs from latest attempt")
            latest_attempt_time = last_attempt.finished_at if last_attempt.finished_at is not None else self.updated_at
            if self.failure.occurred_at < last_attempt.started_at:
                raise JobValidationError("failure.occurred_at is before the latest attempt")
            if self.failure.occurred_at > latest_attempt_time:
                raise JobValidationError("failure.occurred_at is after the latest attempt")
            if self.result is not None:
                raise JobValidationError(f"{self.state.value.lower()} jobs cannot contain a result")
            if self.state is JobState.RETRYING and not self.failure.retryable:
                raise JobValidationError("retrying jobs require a retryable failure")
            if self.state is JobState.RETRYING and self.attempt_count >= self.max_attempts:
                raise JobValidationError("retrying jobs cannot exceed max_attempts")
        elif self.state is JobState.CANCELLED:
            if self.result is not None or self.failure is not None:
                raise JobValidationError("cancelled jobs cannot contain a result or active failure")
            if last_attempt is not None and last_attempt.state is JobState.RUNNING:
                raise JobValidationError("cancelled jobs cannot contain an active attempt")
            if last_attempt is not None and last_attempt.state not in {JobState.FAILED, JobState.CANCELLED}:
                raise JobValidationError("cancelled jobs require no attempt or a cancelled/failed latest attempt")
        if self.state is JobState.SUCCEEDED and self.result is not None:
            latest_attempt_time = last_attempt.finished_at if last_attempt.finished_at is not None else self.updated_at
            if self.result.completed_at < last_attempt.started_at:
                raise JobValidationError("result.completed_at is before the succeeded attempt")
            if self.result.completed_at > latest_attempt_time:
                raise JobValidationError("result.completed_at is after the succeeded attempt")

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        operation: str,
        idempotency_key: str,
        payload: JobPayload,
        now: float,
        max_attempts: int = 3,
    ) -> "Job":
        timestamp = _timestamp(now, field_name="now")
        return cls(
            job_id=JobId(job_id),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            collection_id=collection_id,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
            max_attempts=max_attempts,
            available_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def scope(self) -> JobScope:
        return JobScope(
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            collection_id=self.collection_id,
        )

    @property
    def retry_eligible(self) -> bool:
        return (
            self.attempt_count < self.max_attempts
            and self.state in {
            JobState.FAILED,
            JobState.RETRYING,
            }
            and self.failure is not None
            and self.failure.retryable
        )

    def start_attempt(self, *, worker_id: WorkerId, now: float) -> "Job":
        """Claim a queued job and append one active attempt."""

        if self.state is not JobState.QUEUED:
            raise InvalidTransitionError("only queued jobs can start an attempt")
        if self.attempt_count >= self.max_attempts:
            raise InvalidTransitionError("attempt limit is exhausted")
        timestamp = _timestamp(now, field_name="now")
        if timestamp < self.updated_at:
            raise InvalidTransitionError("job time cannot move backwards")
        attempt = JobAttempt(
            number=self.attempt_count + 1,
            worker_id=worker_id,
            state=JobState.RUNNING,
            started_at=timestamp,
        )
        return Job(
            job_id=self.job_id,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            collection_id=self.collection_id,
            operation=self.operation,
            idempotency_key=self.idempotency_key,
            payload=self.payload,
            state=JobState.RUNNING,
            max_attempts=self.max_attempts,
            attempts=self.attempts + (attempt,),
            result=None,
            failure=None,
            available_at=self.available_at,
            created_at=self.created_at,
            updated_at=timestamp,
            version=self.version + 1,
        )

    def finish_attempt(
        self,
        to_state: JobState,
        *,
        now: float,
        result: JobResult | None = None,
        failure: JobFailure | None = None,
        available_at: float | None = None,
    ) -> "Job":
        """Finish the active attempt and move the job to its resulting state."""

        try:
            target = JobState(to_state)
        except (TypeError, ValueError) as exc:
            raise InvalidTransitionError("target state is invalid") from exc
        if self.state is not JobState.RUNNING or not self.attempts:
            raise InvalidTransitionError("only running jobs can finish an attempt")
        current = self.attempts[-1]
        if current.state is not JobState.RUNNING:
            raise InvalidTransitionError("job has no active attempt")
        if target not in {
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
        }:
            raise InvalidTransitionError(f"RUNNING -> {target} cannot finish an attempt")
        timestamp = _timestamp(now, field_name="now")
        if timestamp < self.updated_at:
            raise InvalidTransitionError("job time cannot move backwards")
        if target is JobState.SUCCEEDED:
            if result is None or failure is not None:
                raise InvalidTransitionError("SUCCEEDED requires only a result")
            if result.completed_at > timestamp:
                raise InvalidTransitionError("result.completed_at is after the transition")
            attempt_state = JobState.SUCCEEDED
            observed_failure = None
        elif target is JobState.CANCELLED:
            if result is not None or failure is not None:
                raise InvalidTransitionError("CANCELLED cannot contain a result or failure")
            attempt_state = JobState.CANCELLED
            observed_failure = None
        else:
            observed_failure = failure
            if observed_failure is None:
                raise InvalidTransitionError(f"{target.value} requires a failure")
            if observed_failure.attempt != current.number:
                raise InvalidTransitionError("failure.attempt must match the active attempt")
            if observed_failure.occurred_at > timestamp:
                raise InvalidTransitionError("failure.occurred_at is after the transition")
            if result is not None:
                raise InvalidTransitionError(f"{target.value} cannot contain a result")
            attempt_state = JobState.FAILED
        finished_attempt = JobAttempt(
            number=current.number,
            worker_id=current.worker_id,
            state=attempt_state,
            started_at=current.started_at,
            finished_at=timestamp,
            failure=observed_failure,
        )
        next_available = self.available_at if available_at is None else _timestamp(available_at, field_name="available_at")
        return Job(
            job_id=self.job_id,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            collection_id=self.collection_id,
            operation=self.operation,
            idempotency_key=self.idempotency_key,
            payload=self.payload,
            state=target,
            max_attempts=self.max_attempts,
            attempts=self.attempts[:-1] + (finished_attempt,),
            result=result,
            failure=observed_failure,
            available_at=next_available,
            created_at=self.created_at,
            updated_at=timestamp,
            version=self.version + 1,
        )

    def transition(
        self,
        to_state: JobState,
        *,
        now: float,
        result: JobResult | None = None,
        failure: JobFailure | None = None,
        available_at: float | None = None,
    ) -> "Job":
        try:
            target = JobState(to_state)
        except (TypeError, ValueError) as exc:
            raise InvalidTransitionError("target state is invalid") from exc
        if not can_transition(self.state, target):
            raise InvalidTransitionError(f"{self.state} -> {target} is not allowed")
        if target is JobState.RUNNING:
            raise InvalidTransitionError("use start_attempt to enter RUNNING")
        if self.state is JobState.RUNNING:
            return self.finish_attempt(
                target,
                now=now,
                result=result,
                failure=failure,
                available_at=available_at,
            )
        if target is JobState.SUCCEEDED:
            raise InvalidTransitionError("only an active attempt can succeed")
        if result is not None:
            raise InvalidTransitionError(f"{target.value} cannot contain a result")
        observed_failure = failure if failure is not None else self.failure
        if target in {JobState.FAILED, JobState.RETRYING, JobState.DEAD_LETTER}:
            if observed_failure is None:
                raise InvalidTransitionError(f"{target.value} requires a failure")
            if observed_failure.attempt != self.attempt_count:
                raise InvalidTransitionError("failure.attempt must match the latest attempt")
            if target is JobState.RETRYING:
                if not observed_failure.retryable:
                    raise InvalidTransitionError("RETRYING requires a retryable failure")
                if self.attempt_count >= self.max_attempts:
                    raise InvalidTransitionError("retry limit is exhausted")
        elif failure is not None:
            raise InvalidTransitionError(f"{target.value} cannot contain a failure")
        timestamp = _timestamp(now, field_name="now")
        if timestamp < self.updated_at:
            raise InvalidTransitionError("job time cannot move backwards")
        if observed_failure is not None and observed_failure.occurred_at > timestamp:
            raise InvalidTransitionError("failure.occurred_at is after the transition")
        next_available = self.available_at if available_at is None else _timestamp(available_at, field_name="available_at")
        next_failure = observed_failure if target in {JobState.FAILED, JobState.RETRYING, JobState.DEAD_LETTER} else None
        return Job(
            job_id=self.job_id,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            collection_id=self.collection_id,
            operation=self.operation,
            idempotency_key=self.idempotency_key,
            payload=self.payload,
            state=target,
            max_attempts=self.max_attempts,
            attempts=self.attempts,
            result=result,
            failure=next_failure,
            available_at=next_available,
            created_at=self.created_at,
            updated_at=timestamp,
            version=self.version + 1,
        )

    def as_dict(self) -> dict[str, object]:
        """Return a deterministic, metadata-only representation for adapters."""

        return {
            "contract_version": CONTRACT_VERSION,
            "job_id": str(self.job_id),
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "collection_id": self.collection_id,
            "operation": self.operation,
            "idempotency_key": self.idempotency_key,
            "payload": dict(self.payload),
            "state": self.state.value,
            "max_attempts": self.max_attempts,
            "attempt_count": self.attempt_count,
            "attempts": [attempt.as_dict() for attempt in self.attempts],
            "available_at": self.available_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "result": None
            if self.result is None
            else {
                "output_refs": dict(self.result.output_refs),
                "document_id": self.result.document_id,
                "completed_at": self.result.completed_at,
            },
            "failure": None if self.failure is None else _failure_dict(self.failure),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def idempotency_identity(job: Job) -> tuple[str, str, str, str]:
    """Return the database uniqueness identity for a job request."""

    return (job.tenant_id, job.workspace_id, job.collection_id, job.idempotency_key)


def ensure_idempotent(existing: Job | None, candidate: Job) -> Job:
    """Return an existing replay or reject reuse for a different request."""

    if existing is None:
        return candidate
    if not isinstance(existing, Job) or not isinstance(candidate, Job):
        raise JobValidationError("idempotency values must be jobs")
    if idempotency_identity(existing) != idempotency_identity(candidate):
        raise JobIdempotencyConflictError("idempotency key is outside the existing job scope")
    existing_envelope = (existing.operation, tuple(existing.payload.items()), existing.max_attempts)
    candidate_envelope = (candidate.operation, tuple(candidate.payload.items()), candidate.max_attempts)
    if existing_envelope != candidate_envelope:
        raise JobIdempotencyConflictError("idempotency key was reused for a different request")
    return existing


@runtime_checkable
class JobRepository(Protocol):
    def get(
        self,
        job_id: JobId,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
    ) -> Job | None: ...

    def get_by_idempotency(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        idempotency_key: str,
    ) -> Job | None: ...

    def create_or_replay(self, job: Job, *, expected_version: int) -> Job:
        """Atomically enforce scoped uniqueness; use 0 for a new insert."""
        ...

    def save(self, job: Job, *, expected_version: int) -> Job: ...

    def transition(self, job: Job, to_state: JobState, *, now: float, expected_version: int) -> Job: ...


@runtime_checkable
class JobQueue(Protocol):
    def enqueue(self, job: Job, *, expected_version: int) -> Job: ...

    def claim(
        self,
        *,
        worker_id: WorkerId,
        scope: JobScope,
        expected_versions: Mapping[JobId, int],
        limit: int = 1,
        now: float,
    ) -> tuple[tuple[Job, JobLease], ...]: ...

    def heartbeat(self, lease: JobLease, *, now: float, expected_version: int) -> JobLease: ...

    def acknowledge(
        self,
        lease: JobLease,
        result: JobResult,
        *,
        now: float,
        expected_version: int,
    ) -> Job: ...

    def fail(
        self,
        lease: JobLease,
        failure: JobFailure,
        *,
        now: float,
        expected_version: int,
    ) -> Job: ...

    def cancel(
        self,
        job_id: JobId,
        *,
        tenant_id: str,
        workspace_id: str,
        collection_id: str,
        now: float,
        expected_version: int,
    ) -> Job: ...

    def health_check(self) -> bool: ...


@runtime_checkable
class JobExecutor(Protocol):
    def execute(
        self,
        job: Job,
        lease: JobLease,
        *,
        cancelled: Callable[[], bool],
    ) -> JobResult: ...


@runtime_checkable
class JobScheduler(Protocol):
    def schedule(self, job: Job, *, available_at: float, expected_version: int) -> Job: ...


__all__ = [
    "CONTRACT_VERSION",
    "Job",
    "JobAttempt",
    "JobContractError",
    "JobFailure",
    "JobIdempotencyConflictError",
    "JobId",
    "JobLease",
    "JobMetadata",
    "JobPayload",
    "JobScope",
    "JobQueue",
    "JobRepository",
    "JobResult",
    "JobScheduler",
    "JobExecutor",
    "JobState",
    "InvalidTransitionError",
    "JobValidationError",
    "LeaseToken",
    "WorkerId",
    "allowed_transitions",
    "can_transition",
    "ensure_idempotent",
    "idempotency_identity",
]
