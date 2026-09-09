"""Injectable Phase 2.3 worker composition root.

This module owns the process boundary between the canonical ``rick_jobs``
contracts and operation handlers.  It deliberately does not construct a
database client, read environment variables, discover credentials, or make
claims about a live PostgreSQL deployment.  A reviewed queue, clock, sleep
function, handler registry, and optional event sink are supplied by the
composition root.

Handlers follow the existing :class:`rick_jobs.JobExecutor` shape::

    def execute(job, lease, *, cancelled) -> JobResult:
        cancelled.checkpoint()
        return JobResult(...)

``cancelled`` is a callable token and also exposes ``checkpoint()``.  The
runtime never forcefully interrupts a Python handler.  Timeouts, lease loss,
and shutdown therefore request cooperative cancellation and prevent any late
acknowledgement.  A queue that exposes ``cancel_lease`` can release a lease
explicitly; the canonical queue currently recovers an abandoned lease by its
durable expiry path, so the runtime leaves it untouched when that optional
capability is absent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from threading import Event, RLock, Thread, current_thread
import time
from typing import Any, Protocol, TypeAlias

from rick_jobs import (
    Job,
    JobFailure,
    JobId,
    JobLease,
    JobQueue,
    JobResult,
    JobScope,
    JobState,
    WorkerId,
)

try:  # The worker package can still be tested with only the jobs package.
    from rick_observability import emit_safely
except ImportError:  # pragma: no cover - exercised only in a minimal install
    def emit_safely(
        sink: object | None,
        event_name: str,
        fields: Mapping[str, object],
        *,
        timeout: float | None = None,
    ) -> bool:
        """Best-effort local fallback for an optional observability package."""

        if sink is None:
            return True
        event = {"event": event_name, "fields": dict(fields)}
        try:
            emitter = getattr(sink, "emit", None)
            if callable(emitter):
                emitter(event)
            elif callable(sink):
                sink(event)
            else:
                return False
        except Exception:
            return False
        return True


RUNTIME_CONTRACT_VERSION = "real-worker-runtime-v1"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OPERATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_MAX_CONCURRENCY = 64
_MAX_OPERATIONS = 256
_MAX_PAYLOAD_BYTES = 32 * 1024
_MAX_TIMEOUT_SECONDS = 24 * 60 * 60
_MAX_SLEEP_SECONDS = 300.0

_RETRYABLE_HANDLER_CODES = frozenset(
    {
        "handler_timeout",
        "handler_failed",
        "provider_timeout",
        "provider_unavailable",
        "storage_unavailable",
        "vector_store_unavailable",
        "lock_unavailable",
        "ingestion_failed",
        "recovery_required",
    }
)
_KNOWN_HANDLER_CODES = _RETRYABLE_HANDLER_CODES | frozenset(
    {"validation_error", "invalid_result", "vector_store_unavailable", "recovery_required", "cancelled"}
)
_SAFE_FAILURE_MESSAGES = {
    "handler_timeout": "The operation exceeded its execution deadline.",
    "handler_failed": "The operation failed.",
    "provider_timeout": "The provider operation timed out.",
    "provider_unavailable": "The provider was unavailable.",
    "storage_unavailable": "The storage operation was unavailable.",
    "vector_store_unavailable": "The vector store operation was unavailable.",
    "lock_unavailable": "The job lease was unavailable.",
    "ingestion_failed": "The operation failed.",
    "recovery_required": "The operation requires recovery.",
    "cancelled": "The operation was cancelled.",
    "validation_error": "The operation input was invalid.",
    "invalid_result": "The operation returned an invalid result.",
    "unknown_operation": "The job operation is not registered.",
    "payload_too_large": "The job payload exceeds the worker limit.",
    "invalid_job": "The claimed job is invalid.",
}


class RuntimeConfigurationError(ValueError):
    """A composition-root value is outside the finite runtime contract."""


class StartupValidationError(RuntimeConfigurationError):
    """Startup failed before the runtime accepted work."""

    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("worker startup validation failed")


class RuntimeClosed(RuntimeError):
    """The runtime has completed shutdown and cannot accept more work."""


class WorkerCancelled(RuntimeError):
    """A cooperative handler cancellation checkpoint was reached."""

    code = "cancelled"


class OperationHandler(Protocol):
    """The explicit operation handler boundary used by the runtime."""

    def execute(
        self,
        job: Job,
        lease: JobLease,
        *,
        cancelled: "CancellationToken",
    ) -> JobResult: ...


Handler: TypeAlias = OperationHandler | Callable[..., JobResult]
Clock: TypeAlias = Callable[[], float]
Sleeper: TypeAlias = Callable[[float], object]
VersionResolver: TypeAlias = Callable[[JobId], int]


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value.strip()) is None:
        raise RuntimeConfigurationError(f"{name} is invalid")
    return value.strip()


def _operation(value: object) -> str:
    if not isinstance(value, str) or _OPERATION.fullmatch(value.strip()) is None:
        raise RuntimeConfigurationError("operation is invalid")
    return value.strip()


def _finite_number(value: object, *, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeConfigurationError(f"{name} is invalid")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise RuntimeConfigurationError(f"{name} is out of range")
    return result


def _positive_int(value: object, *, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise RuntimeConfigurationError(f"{name} is out of range")
    return value


def _opaque(value: object) -> str:
    """Return a stable reference without retaining a job ID or operation."""

    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def _safe_code(value: object, *, fallback: str) -> str:
    if isinstance(value, str) and _SAFE_CODE.fullmatch(value) and value in _KNOWN_HANDLER_CODES:
        return value
    return fallback


class CancellationToken:
    """Callable, cooperative cancellation token passed to every handler."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = Event()

    def __call__(self) -> bool:
        return self._event.is_set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def checkpoint(self) -> None:
        if self._event.is_set():
            raise WorkerCancelled()

    def _request(self) -> None:
        self._event.set()


class OperationRegistry:
    """Finite, explicit operation-to-handler registry.

    Registration is closed by :class:`RealWorkerRuntime` at startup.  There is
    no import scanning, plugin discovery, or fallback handler.
    """

    __slots__ = ("_handlers", "_frozen")

    def __init__(self, handlers: Mapping[str, Handler] | None = None) -> None:
        self._handlers: dict[str, Handler] = {}
        self._frozen = False
        if handlers is not None:
            if not isinstance(handlers, Mapping):
                raise RuntimeConfigurationError("handlers must be a mapping")
            if len(handlers) > _MAX_OPERATIONS:
                raise RuntimeConfigurationError("too many operation handlers")
            for operation, handler in handlers.items():
                self.register(operation, handler)

    def register(self, operation: str, handler: Handler) -> "OperationRegistry":
        if self._frozen:
            raise RuntimeConfigurationError("operation registry is closed")
        name = _operation(operation)
        if not callable(getattr(handler, "execute", None)) and not callable(handler):
            raise RuntimeConfigurationError("handler is not callable")
        if name in self._handlers:
            raise RuntimeConfigurationError("operation is already registered")
        if len(self._handlers) >= _MAX_OPERATIONS:
            raise RuntimeConfigurationError("too many operation handlers")
        self._handlers[name] = handler
        return self

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def get(self, operation: str) -> Handler | None:
        return self._handlers.get(operation)

    def __contains__(self, operation: object) -> bool:
        return operation in self._handlers

    def __len__(self) -> int:
        return len(self._handlers)


@dataclass(frozen=True, slots=True)
class StartupReport:
    contract_version: str
    worker_id: str
    scope: JobScope
    operations: tuple[str, ...]
    max_concurrency: int
    max_payload_bytes: int


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    contract_version: str
    live: bool
    ready: bool
    reason: str
    worker_id: str
    active: int
    operations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "live": self.live,
            "ready": self.ready,
            "reason": self.reason,
            "worker_id": _opaque(self.worker_id),
            "active": self.active,
            "operations": list(self.operations),
        }


@dataclass(frozen=True, slots=True)
class RuntimeMetrics:
    claimed: int = 0
    started: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    lease_lost: int = 0
    timed_out: int = 0
    poisoned: int = 0
    heartbeats: int = 0
    heartbeat_failures: int = 0
    queue_errors: int = 0
    active: int = 0
    max_active: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "started": self.started,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "lease_lost": self.lease_lost,
            "timed_out": self.timed_out,
            "poisoned": self.poisoned,
            "heartbeats": self.heartbeats,
            "heartbeat_failures": self.heartbeat_failures,
            "queue_errors": self.queue_errors,
            "active": self.active,
            "max_active": self.max_active,
        }


@dataclass(frozen=True, slots=True)
class RunResult:
    claimed: int = 0
    started: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    lease_lost: int = 0
    poisoned: int = 0
    queue_errors: int = 0
    timed_out: int = 0
    backpressured: bool = False
    active: int = 0

    @property
    def completed(self) -> int:
        return self.succeeded + self.failed + self.cancelled + self.lease_lost

    def as_dict(self) -> dict[str, object]:
        return {
            "claimed": self.claimed,
            "started": self.started,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "lease_lost": self.lease_lost,
            "poisoned": self.poisoned,
            "queue_errors": self.queue_errors,
            "timed_out": self.timed_out,
            "backpressured": self.backpressured,
            "active": self.active,
        }


@dataclass(frozen=True, slots=True)
class ShutdownReport:
    drained: bool
    timed_out: bool
    cancelled: int
    active: int

    def as_dict(self) -> dict[str, object]:
        return {
            "drained": self.drained,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "active": self.active,
        }


class _MetricState:
    __slots__ = ("_lock", "_values")

    def __init__(self) -> None:
        self._lock = RLock()
        self._values: dict[str, int] = {}

    def increment(self, name: str) -> None:
        with self._lock:
            self._values[name] = self._values.get(name, 0) + 1

    def snapshot(self, *, active: int, max_active: int) -> RuntimeMetrics:
        with self._lock:
            values = dict(self._values)
        return RuntimeMetrics(
            claimed=values.get("claimed", 0),
            started=values.get("started", 0),
            succeeded=values.get("succeeded", 0),
            failed=values.get("failed", 0),
            cancelled=values.get("cancelled", 0),
            lease_lost=values.get("lease_lost", 0),
            timed_out=values.get("timed_out", 0),
            poisoned=values.get("poisoned", 0),
            heartbeats=values.get("heartbeats", 0),
            heartbeat_failures=values.get("heartbeat_failures", 0),
            queue_errors=values.get("queue_errors", 0),
            active=active,
            max_active=max_active,
        )


@dataclass(slots=True)
class _Execution:
    job: Job
    lease: JobLease
    handler: Handler
    token: CancellationToken
    started_at: float
    deadline: float
    next_heartbeat_at: float
    handler_done: Event = field(default_factory=Event)
    logical_done: Event = field(default_factory=Event)
    lock: RLock = field(default_factory=RLock)
    result: object = None
    error: BaseException | None = None
    outcome: str | None = None
    failure_code: str | None = None
    cancel_requested: bool = False
    lease_lost: bool = False
    finalizing: bool = False
    timed_out: bool = False
    thread: Thread | None = None


class _ExpectedVersionHints(Mapping[JobId, int]):
    """Lazy mapping for the current queue claim port.

    ``PostgresJobQueue.claim`` selects rows under its transaction but asks its
    caller for each selected row's expected version.  The runtime cannot know
    those IDs before the claim, so this bounded mapping resolves a selected ID
    only when the adapter indexes it.  A composition root can inject a
    stronger version oracle when its admission layer already owns one.
    """

    __slots__ = ("_runtime",)

    def __init__(self, runtime: "RealWorkerRuntime") -> None:
        self._runtime = runtime

    def __contains__(self, _key: object) -> bool:
        return True

    def __getitem__(self, key: JobId) -> int:
        return self._runtime._resolve_expected_version(key)

    def get(self, _key: JobId, default: int | None = None) -> int | None:
        """Let adapters use their row-locked version default.

        Legacy fakes that index the mapping still exercise the injected
        resolver; the canonical PostgreSQL adapter uses ``get`` and resolves
        the selected row while it holds its claim lock.
        """

        return default

    def __iter__(self) -> Iterator[JobId]:
        return iter(())

    def __len__(self) -> int:
        return 0


class RealWorkerRuntime:
    """Bounded canonical worker runtime with injected external dependencies."""

    def __init__(
        self,
        queue: JobQueue,
        *,
        worker_id: str,
        scope: JobScope,
        handlers: Mapping[str, Handler] | OperationRegistry,
        max_concurrency: int = 4,
        max_payload_bytes: int = _MAX_PAYLOAD_BYTES,
        handler_timeout_seconds: float = 300.0,
        heartbeat_interval_seconds: float | None = None,
        poll_interval_seconds: float = 0.1,
        shutdown_timeout_seconds: float = 30.0,
        max_consecutive_queue_errors: int = 3,
        clock: Clock = time.time,
        sleep_fn: Sleeper = time.sleep,
        event_sink: object | None = None,
        expected_version_resolver: VersionResolver | None = None,
    ) -> None:
        self.queue = queue
        self.worker_id = WorkerId(_identifier(worker_id, name="worker_id"))
        if not isinstance(scope, JobScope):
            raise RuntimeConfigurationError("scope is invalid")
        self.scope = scope
        if isinstance(handlers, OperationRegistry):
            self.registry = handlers
        else:
            self.registry = OperationRegistry(handlers)
        self.max_concurrency = _positive_int(
            max_concurrency, name="max_concurrency", maximum=_MAX_CONCURRENCY
        )
        self.max_payload_bytes = _positive_int(
            max_payload_bytes, name="max_payload_bytes", maximum=_MAX_PAYLOAD_BYTES
        )
        self.handler_timeout_seconds = _finite_number(
            handler_timeout_seconds,
            name="handler_timeout_seconds",
            minimum=0.01,
            maximum=_MAX_TIMEOUT_SECONDS,
        )
        if heartbeat_interval_seconds is None:
            self.heartbeat_interval_seconds: float | None = None
        else:
            self.heartbeat_interval_seconds = _finite_number(
                heartbeat_interval_seconds,
                name="heartbeat_interval_seconds",
                minimum=0.01,
                maximum=_MAX_TIMEOUT_SECONDS,
            )
        self.poll_interval_seconds = _finite_number(
            poll_interval_seconds,
            name="poll_interval_seconds",
            minimum=0.001,
            maximum=_MAX_SLEEP_SECONDS,
        )
        self.shutdown_timeout_seconds = _finite_number(
            shutdown_timeout_seconds,
            name="shutdown_timeout_seconds",
            minimum=0.0,
            maximum=_MAX_TIMEOUT_SECONDS,
        )
        self.max_consecutive_queue_errors = _positive_int(
            max_consecutive_queue_errors,
            name="max_consecutive_queue_errors",
            maximum=1_000,
        )
        if not callable(clock):
            raise RuntimeConfigurationError("clock is not callable")
        if not callable(sleep_fn):
            raise RuntimeConfigurationError("sleep_fn is not callable")
        if expected_version_resolver is not None and not callable(expected_version_resolver):
            raise RuntimeConfigurationError("expected_version_resolver is not callable")
        self.clock = clock
        self.sleep_fn = sleep_fn
        self.event_sink = event_sink
        self.expected_version_resolver = expected_version_resolver

        self._lock = RLock()
        self._active: dict[str, _Execution] = {}
        self._started = False
        self._closing = False
        self._closed = False
        self._stop_requested = False
        self._fatal_reason: str | None = None
        self._last_now = 0.0
        self._max_active = 0
        self._consecutive_queue_errors = 0
        self._metrics = _MetricState()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def is_started(self) -> bool:
        with self._lock:
            return self._started

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def _now(self) -> float:
        try:
            observed = float(self.clock())
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeConfigurationError("clock returned an invalid value") from exc
        if not math.isfinite(observed):
            raise RuntimeConfigurationError("clock returned an invalid value")
        with self._lock:
            self._last_now = max(self._last_now, observed)
            return self._last_now

    def _emit(
        self,
        event_name: str,
        *,
        execution: _Execution | None = None,
        code: str | None = None,
        reason: str | None = None,
    ) -> None:
        fields: dict[str, object] = {
            "worker_ref": _opaque(self.worker_id),
            "active": self.active_count,
        }
        if execution is not None:
            fields["job_ref"] = _opaque(execution.job.job_id)
            fields["operation_ref"] = _opaque(execution.job.operation)
        if code is not None and _SAFE_CODE.fullmatch(code):
            fields["code"] = code
        if reason is not None and _SAFE_CODE.fullmatch(reason):
            fields["reason"] = reason
        emit_safely(self.event_sink, event_name, fields)

    def _required_queue_methods(self) -> tuple[str, ...]:
        return (
            "claim",
            "heartbeat",
            "acknowledge",
            "fail",
            "health_check",
        )

    def validate_startup(self) -> StartupReport:
        """Validate every injected boundary before accepting a claim."""

        errors: list[str] = []
        if self.queue is None:
            errors.append("queue_missing")
        else:
            for name in self._required_queue_methods():
                if not callable(getattr(self.queue, name, None)):
                    errors.append(f"queue_{name}_missing")
            if self.expected_version_resolver is None and not callable(
                getattr(self.queue, "get", None)
            ):
                errors.append("queue_get_missing")
        if not isinstance(self.scope, JobScope):
            errors.append("scope_invalid")
        if len(self.registry) == 0:
            errors.append("handlers_empty")
        if not callable(self.clock):
            errors.append("clock_invalid")
        if not callable(self.sleep_fn):
            errors.append("sleep_invalid")
        if not errors:
            try:
                if not bool(self.queue.health_check()):
                    errors.append("queue_unavailable")
            except Exception:
                errors.append("queue_unavailable")
        readiness = getattr(self.queue, "readiness_check", None)
        if not errors and callable(readiness):
            try:
                if not bool(readiness()):
                    errors.append("queue_not_ready")
            except Exception:
                errors.append("queue_not_ready")
        if errors:
            raise StartupValidationError(tuple(errors))
        return StartupReport(
            contract_version=RUNTIME_CONTRACT_VERSION,
            worker_id=str(self.worker_id),
            scope=self.scope,
            operations=self.registry.operations,
            max_concurrency=self.max_concurrency,
            max_payload_bytes=self.max_payload_bytes,
        )

    def start(self) -> StartupReport:
        with self._lock:
            if self._closed:
                raise RuntimeClosed()
            if self._started:
                return StartupReport(
                    contract_version=RUNTIME_CONTRACT_VERSION,
                    worker_id=str(self.worker_id),
                    scope=self.scope,
                    operations=self.registry.operations,
                    max_concurrency=self.max_concurrency,
                    max_payload_bytes=self.max_payload_bytes,
                )
        report = self.validate_startup()
        with self._lock:
            if self._closed:
                raise RuntimeClosed()
            self.registry.freeze()
            self._started = True
        self._emit("worker.runtime.started")
        return report

    # Deployment launchers use the neutral startup name so the same contract
    # works with factories that return a runtime directly or via Providers.
    startup = start

    def _ensure_started(self) -> None:
        with self._lock:
            closed = self._closed
            started = self._started
        if closed:
            raise RuntimeClosed()
        if not started:
            self.start()

    def health(self) -> RuntimeHealth:
        with self._lock:
            started = self._started
            closing = self._closing
            closed = self._closed
            fatal = self._fatal_reason
        active = self.active_count
        if not started:
            return RuntimeHealth(
                RUNTIME_CONTRACT_VERSION,
                live=False,
                ready=False,
                reason="startup_not_complete",
                worker_id=str(self.worker_id),
                active=active,
                operations=self.registry.operations,
            )
        if closed:
            reason = "closed"
        elif closing:
            reason = "shutting_down"
        elif fatal is not None:
            reason = fatal
        else:
            reason = "ok"
        live = not closed
        ready = live and not closing and fatal is None
        if ready:
            readiness = getattr(self.queue, "readiness_check", None)
            try:
                ready = bool(readiness()) if callable(readiness) else bool(self.queue.health_check())
            except Exception:
                ready = False
            if not ready:
                reason = "queue_unavailable"
        return RuntimeHealth(
            RUNTIME_CONTRACT_VERSION,
            live=live,
            ready=ready,
            reason=reason,
            worker_id=str(self.worker_id),
            active=active,
            operations=self.registry.operations,
        )

    def readiness(self) -> RuntimeHealth:
        return self.health()

    def liveness(self) -> RuntimeHealth:
        observed = self.health()
        return RuntimeHealth(
            observed.contract_version,
            live=observed.live,
            ready=observed.ready,
            reason=observed.reason if observed.live else "not_live",
            worker_id=observed.worker_id,
            active=observed.active,
            operations=observed.operations,
        )

    def is_ready(self) -> bool:
        return self.readiness().ready

    def is_live(self) -> bool:
        return self.liveness().live

    def readiness_check(self) -> bool:
        return self.readiness().ready

    def liveness_check(self) -> bool:
        return self.liveness().live

    def health_check(self) -> bool:
        """Docker compatibility: health means ready to accept work."""

        return self.readiness_check()

    def metrics(self) -> RuntimeMetrics:
        with self._lock:
            active = len(self._active)
            maximum = self._max_active
        return self._metrics.snapshot(active=active, max_active=maximum)

    def _resolve_expected_version(self, job_id: JobId) -> int:
        try:
            if self.expected_version_resolver is not None:
                version = self.expected_version_resolver(job_id)
            else:
                observed = self.queue.get(
                    job_id,
                    tenant_id=self.scope.tenant_id,
                    workspace_id=self.scope.workspace_id,
                    collection_id=self.scope.collection_id,
                )
                if not isinstance(observed, Job):
                    raise RuntimeConfigurationError("queue returned no job version")
                version = observed.version
        except RuntimeConfigurationError:
            raise
        except Exception as exc:
            raise RuntimeConfigurationError("expected version could not be resolved") from exc
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise RuntimeConfigurationError("expected version is invalid")
        return version

    def _claim(self, limit: int) -> tuple[tuple[Job, JobLease], ...] | None:
        try:
            claimed = self.queue.claim(
                worker_id=self.worker_id,
                scope=self.scope,
                expected_versions=_ExpectedVersionHints(self),
                limit=limit,
                now=self._now(),
            )
            iterator = iter(claimed)
            bounded: list[tuple[Job, JobLease]] = []
            for index in range(limit + 1):
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                if index >= limit:
                    self._metrics.increment("queue_errors")
                    self._emit("worker.queue.error", reason="claim_overflow")
                    return None
                bounded.append(item)
            return tuple(bounded)
        except Exception:
            self._metrics.increment("queue_errors")
            self._emit("worker.queue.error", reason="claim_failed")
            return None

    @staticmethod
    def _payload_size(job: Job) -> int:
        encoded = json.dumps(
            dict(job.payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return len(encoded.encode("utf-8"))

    @staticmethod
    def _handler_callable(handler: Handler) -> Callable[..., JobResult]:
        method = getattr(handler, "execute", None)
        if callable(method):
            return method
        if callable(handler):
            return handler
        raise RuntimeConfigurationError("handler is not callable")

    def _failure(
        self,
        job: Job,
        *,
        code: str,
        retryable: bool,
        now: float,
    ) -> JobFailure:
        attempt = job.attempt_count
        if not 1 <= attempt <= 64:
            raise RuntimeConfigurationError("claimed job attempt is invalid")
        occurred_at = max(now, job.updated_at)
        return JobFailure(
            code=code,
            message=_SAFE_FAILURE_MESSAGES.get(code, "The operation failed."),
            retryable=retryable,
            attempt=attempt,
            occurred_at=occurred_at,
        )

    @staticmethod
    def _is_lease_error(error: BaseException) -> bool:
        return getattr(error, "code", None) == "lease"

    def _record_outcome(self, execution: _Execution, outcome: str, *, code: str | None = None) -> None:
        with execution.lock:
            if execution.outcome is not None:
                return
            execution.outcome = outcome
            execution.failure_code = code
            execution.logical_done.set()
        self._metrics.increment(outcome)
        if code == "handler_timeout":
            self._metrics.increment("timed_out")
        if outcome == "succeeded":
            self._emit("worker.job.succeeded", execution=execution)
        elif outcome == "failed":
            self._emit("worker.job.failed", execution=execution, code=code or "handler_failed")
        elif outcome == "cancelled":
            self._emit("worker.job.cancelled", execution=execution, reason="cooperative_cancel")
        elif outcome == "lease_lost":
            self._emit("worker.job.lease_lost", execution=execution, reason="lease_unavailable")
        elif outcome == "queue_error":
            self._emit("worker.queue.error", execution=execution, reason="mutation_failed")

    def _begin_finalization(self, execution: _Execution) -> bool:
        with execution.lock:
            if execution.logical_done.is_set() or execution.finalizing:
                return False
            execution.finalizing = True
            return True

    def _end_finalization(self, execution: _Execution, outcome: str, *, code: str | None = None) -> None:
        with execution.lock:
            execution.finalizing = False
        self._record_outcome(execution, outcome, code=code)

    def _release_cancelled_lease(self, execution: _Execution) -> str:
        release = getattr(self.queue, "cancel_lease", None)
        if not callable(release):
            return "cancelled"
        try:
            release(
                execution.lease,
                now=self._now(),
                expected_version=execution.job.version,
            )
        except Exception as exc:
            if self._is_lease_error(exc):
                return "lease_lost"
            self._metrics.increment("queue_errors")
            return "cancelled"
        return "cancelled"

    def _finalize_cancel(self, execution: _Execution) -> None:
        if not self._begin_finalization(execution):
            return
        outcome = self._release_cancelled_lease(execution)
        self._end_finalization(execution, outcome)

    def _finalize_lease_lost(self, execution: _Execution) -> None:
        if not self._begin_finalization(execution):
            return
        self._end_finalization(execution, "lease_lost")

    def _finalize_failure(self, execution: _Execution, code: str, retryable: bool) -> None:
        if not self._begin_finalization(execution):
            return
        try:
            failure = self._failure(
                execution.job,
                code=code,
                retryable=retryable,
                now=self._now(),
            )
            self.queue.fail(
                execution.lease,
                failure,
                now=self._now(),
                expected_version=execution.job.version,
            )
        except Exception as exc:
            if self._is_lease_error(exc):
                self._end_finalization(execution, "lease_lost")
            else:
                self._metrics.increment("queue_errors")
                self._end_finalization(execution, "queue_error", code=code)
        else:
            self._end_finalization(execution, "failed", code=code)

    def _finalize_handler(self, execution: _Execution) -> None:
        with execution.lock:
            error = execution.error
            result = execution.result
            cancelled = execution.cancel_requested or execution.token.cancelled
            lease_lost = execution.lease_lost
            timed_out = execution.timed_out
        if lease_lost:
            self._finalize_lease_lost(execution)
            return
        if cancelled or isinstance(error, WorkerCancelled):
            self._finalize_cancel(execution)
            return
        now = self._now()
        if timed_out or now >= execution.deadline:
            with execution.lock:
                execution.timed_out = True
                execution.token._request()
            self._finalize_failure(execution, "handler_timeout", True)
            return
        if error is not None:
            code = _safe_code(getattr(error, "code", None), fallback="handler_failed")
            self._finalize_failure(execution, code, code in _RETRYABLE_HANDLER_CODES)
            return
        if not isinstance(result, JobResult):
            self._finalize_failure(execution, "invalid_result", False)
            return
        if not self._begin_finalization(execution):
            return
        try:
            self.queue.acknowledge(
                execution.lease,
                result,
                now=now,
                expected_version=execution.job.version,
                deadline=execution.deadline,
            )
        except Exception as exc:
            if self._is_lease_error(exc):
                self._end_finalization(execution, "lease_lost")
            else:
                self._metrics.increment("queue_errors")
                self._end_finalization(execution, "queue_error")
        else:
            self._end_finalization(execution, "succeeded")

    def _heartbeat(self, execution: _Execution, now: float) -> None:
        try:
            renewed = self.queue.heartbeat(
                execution.lease,
                now=now,
                expected_version=execution.job.version,
            )
            if (
                not isinstance(renewed, JobLease)
                or renewed.job_id != execution.lease.job_id
                or renewed.scope != execution.lease.scope
                or renewed.worker_id != execution.lease.worker_id
                or renewed.token != execution.lease.token
                or not renewed.matches(
                execution.job,
                worker_id=self.worker_id,
                token=execution.lease.token,
                )
            ):
                raise RuntimeConfigurationError("queue returned an invalid lease")
        except Exception:
            with execution.lock:
                execution.lease_lost = True
                execution.token._request()
            self._metrics.increment("heartbeat_failures")
            self._finalize_lease_lost(execution)
            return
        with execution.lock:
            if execution.logical_done.is_set():
                return
            execution.lease = renewed
            interval = self._lease_interval(renewed)
            execution.next_heartbeat_at = max(now, renewed.heartbeat_at) + interval
        self._metrics.increment("heartbeats")
        self._emit("worker.job.heartbeat", execution=execution)

    def _lease_interval(self, lease: JobLease) -> float:
        if self.heartbeat_interval_seconds is not None:
            return self.heartbeat_interval_seconds
        duration = max(0.01, lease.expires_at - lease.acquired_at)
        return max(0.01, min(10.0, duration / 3.0))

    def _monitor_one(self, execution: _Execution, now: float) -> None:
        with execution.lock:
            if execution.logical_done.is_set() or execution.finalizing:
                return
            lease_lost = execution.lease_lost
            cancelled = execution.cancel_requested or execution.token.cancelled
            handler_done = execution.handler_done.is_set()
            timed_out = now >= execution.deadline
            heartbeat_due = now >= execution.next_heartbeat_at
        if lease_lost:
            self._finalize_lease_lost(execution)
        elif cancelled:
            self._finalize_cancel(execution)
        elif timed_out:
            with execution.lock:
                execution.timed_out = True
                execution.token._request()
            self._finalize_failure(execution, "handler_timeout", True)
        elif handler_done:
            self._finalize_handler(execution)
        elif heartbeat_due:
            self._heartbeat(execution, now)

    def _monitor_active(self) -> None:
        now = self._now()
        with self._lock:
            executions = tuple(self._active.values())
        for execution in executions:
            self._monitor_one(execution, now)
        self._reap()

    def _reap(self) -> None:
        with self._lock:
            finished = [
                job_id
                for job_id, execution in self._active.items()
                if execution.handler_done.is_set() and execution.logical_done.is_set()
            ]
            for job_id in finished:
                execution = self._active.pop(job_id)
                thread = execution.thread
                if thread is not None and thread is not current_thread():
                    thread.join(timeout=0)

    def _start_execution(self, job: Job, lease: JobLease) -> _Execution:
        handler = self.registry.get(job.operation)
        if handler is None:
            raise RuntimeConfigurationError("handler is not registered")
        callable_handler = self._handler_callable(handler)
        now = self._now()
        execution = _Execution(
            job=job,
            lease=lease,
            handler=handler,
            token=CancellationToken(),
            started_at=now,
            deadline=now + self.handler_timeout_seconds,
            next_heartbeat_at=now + self._lease_interval(lease),
        )

        def invoke() -> None:
            try:
                execution.result = callable_handler(
                    job,
                    lease,
                    cancelled=execution.token,
                )
            except BaseException as error:  # worker isolation boundary
                execution.error = error
            finally:
                execution.handler_done.set()
                self._reap()

        thread = Thread(
            target=invoke,
            name=f"rick-worker-{_opaque(job.job_id)}",
            daemon=True,
        )
        execution.thread = thread
        with self._lock:
            self._active[str(job.job_id)] = execution
            self._max_active = max(self._max_active, len(self._active))
        self._metrics.increment("started")
        self._emit("worker.job.started", execution=execution)
        thread.start()
        return execution

    def _poison_claim(self, job: Job, lease: JobLease, *, code: str) -> tuple[str, bool]:
        self._metrics.increment("poisoned")
        try:
            failure = self._failure(job, code=code, retryable=False, now=self._now())
            self.queue.fail(lease, failure, now=self._now(), expected_version=job.version)
        except Exception as exc:
            if self._is_lease_error(exc):
                self._metrics.increment("lease_lost")
                self._emit("worker.job.lease_lost", code=code, reason="poison_ack")
                return "lease_lost", True
            self._metrics.increment("queue_errors")
            self._emit("worker.queue.error", code=code, reason="poison_mutation")
            return "queue_error", True
        self._metrics.increment("failed")
        self._emit("worker.job.poisoned", code=code, reason="non_retryable")
        return "failed", True

    def _validate_claim(self, item: object, now: float) -> tuple[Job, JobLease] | None:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            return None
        job, lease = item
        if not isinstance(job, Job) or not isinstance(lease, JobLease):
            return None
        if job.scope != self.scope or lease.scope != self.scope:
            return None
        if lease.worker_id != self.worker_id or not lease.matches(
            job,
            worker_id=self.worker_id,
            token=lease.token,
        ):
            return None
        if job.state is not JobState.RUNNING or not lease.active_at(now):
            return None
        return job, lease

    def _sleep(self, seconds: float) -> None:
        bounded = max(0.0, min(float(seconds), _MAX_SLEEP_SECONDS))
        try:
            self.sleep_fn(bounded)
        except Exception:
            # A test or process supervisor sleep hook cannot corrupt queue state.
            time.sleep(min(0.01, bounded))

    def _next_wait(self, executions: tuple[_Execution, ...], now: float) -> float:
        deadlines: list[float] = [self.poll_interval_seconds]
        for execution in executions:
            with execution.lock:
                if execution.logical_done.is_set():
                    continue
                deadlines.append(max(0.0, execution.deadline - now))
                deadlines.append(max(0.0, execution.next_heartbeat_at - now))
        return max(0.0005, min(deadlines))

    def _wait_for(self, executions: tuple[_Execution, ...]) -> None:
        while True:
            self._monitor_active()
            if all(execution.logical_done.is_set() for execution in executions):
                return
            with self._lock:
                if self._closed:
                    return
            now = self._now()
            self._sleep(self._next_wait(executions, now))

    def cancel(self, job_id: JobId | str) -> bool:
        """Request cooperative cancellation for an active claimed job."""

        key = str(job_id)
        with self._lock:
            execution = self._active.get(key)
        if execution is None:
            return False
        with execution.lock:
            if execution.logical_done.is_set():
                return False
            execution.cancel_requested = True
            execution.token._request()
        self._emit("worker.job.cancel_requested", execution=execution, reason="caller")
        return True

    def run_once(self, *, wait: bool = True) -> RunResult:
        """Claim at most the available finite capacity and process one cycle."""

        if not isinstance(wait, bool):
            raise RuntimeConfigurationError("wait must be a boolean")
        self._ensure_started()
        with self._lock:
            if self._closing or self._closed or self._stop_requested:
                return RunResult(active=len(self._active))
            capacity = self.max_concurrency - len(self._active)
        self._monitor_active()
        with self._lock:
            capacity = self.max_concurrency - len(self._active)
            existing = tuple(self._active.values())
        backpressured = capacity <= 0
        claimed_count = 0
        started: list[_Execution] = []
        immediate_failed = immediate_poisoned = immediate_lease_lost = 0
        queue_errors = 0
        if capacity > 0:
            claimed = self._claim(capacity)
            if claimed is None:
                queue_errors = 1
                claimed = ()
            claimed_count = len(claimed)
            self._metrics.increment("claimed") if claimed_count else None
            now = self._now()
            for item in claimed:
                observed = self._validate_claim(item, now)
                if observed is None:
                    self._metrics.increment("poisoned")
                    self._metrics.increment("queue_errors")
                    self._emit("worker.queue.error", reason="invalid_claim")
                    queue_errors += 1
                    continue
                job, lease = observed
                try:
                    payload_size = self._payload_size(job)
                except (TypeError, ValueError, OverflowError):
                    payload_size = self.max_payload_bytes + 1
                if payload_size > self.max_payload_bytes:
                    outcome, _ = self._poison_claim(job, lease, code="payload_too_large")
                    if outcome == "failed":
                        immediate_failed += 1
                    elif outcome == "lease_lost":
                        immediate_lease_lost += 1
                    else:
                        queue_errors += 1
                    immediate_poisoned += 1
                    continue
                if self.registry.get(job.operation) is None:
                    outcome, _ = self._poison_claim(job, lease, code="unknown_operation")
                    if outcome == "failed":
                        immediate_failed += 1
                    elif outcome == "lease_lost":
                        immediate_lease_lost += 1
                    else:
                        queue_errors += 1
                    immediate_poisoned += 1
                    continue
                try:
                    started.append(self._start_execution(job, lease))
                except Exception:
                    outcome, _ = self._poison_claim(job, lease, code="invalid_job")
                    if outcome == "failed":
                        immediate_failed += 1
                    elif outcome == "lease_lost":
                        immediate_lease_lost += 1
                    else:
                        queue_errors += 1
                    immediate_poisoned += 1

        targets = tuple(started)
        if wait:
            if targets:
                self._wait_for(targets)
            elif backpressured or existing:
                self._wait_for(existing)
        self._monitor_active()
        outcomes = [execution.outcome for execution in started]
        succeeded = outcomes.count("succeeded")
        failed = immediate_failed + outcomes.count("failed")
        cancelled = outcomes.count("cancelled")
        lease_lost = immediate_lease_lost + outcomes.count("lease_lost")
        timed_out = sum(1 for execution in started if execution.timed_out)
        poisoned = immediate_poisoned
        queue_errors += outcomes.count("queue_error")
        self._reap()
        return RunResult(
            claimed=claimed_count,
            started=len(started),
            succeeded=succeeded,
            failed=failed,
            cancelled=cancelled,
            lease_lost=lease_lost,
            poisoned=poisoned,
            queue_errors=queue_errors,
            timed_out=timed_out,
            backpressured=backpressured,
            active=self.active_count,
        )

    def run_forever(self, *, max_runtime_seconds: float | None = None) -> RunResult:
        self._ensure_started()
        if max_runtime_seconds is not None:
            max_runtime = _finite_number(
                max_runtime_seconds,
                name="max_runtime_seconds",
                minimum=0.001,
                maximum=_MAX_TIMEOUT_SECONDS,
            )
            deadline = self._now() + max_runtime
        else:
            deadline = None
        totals = RunResult()
        while True:
            with self._lock:
                if self._stop_requested or self._closing or self._closed:
                    break
            if deadline is not None and self._now() >= deadline:
                break
            batch = self.run_once(wait=False)
            if batch.queue_errors:
                self._consecutive_queue_errors += batch.queue_errors
                if self._consecutive_queue_errors >= self.max_consecutive_queue_errors:
                    with self._lock:
                        self._fatal_reason = "queue_unavailable"
                        self._stop_requested = True
            else:
                self._consecutive_queue_errors = 0
            totals = RunResult(
                claimed=totals.claimed + batch.claimed,
                started=totals.started + batch.started,
                succeeded=totals.succeeded + batch.succeeded,
                failed=totals.failed + batch.failed,
                cancelled=totals.cancelled + batch.cancelled,
                lease_lost=totals.lease_lost + batch.lease_lost,
                poisoned=totals.poisoned + batch.poisoned,
                queue_errors=totals.queue_errors + batch.queue_errors,
                timed_out=totals.timed_out + batch.timed_out,
                backpressured=totals.backpressured or batch.backpressured,
                active=batch.active,
            )
            remaining = self.poll_interval_seconds
            if deadline is not None:
                remaining = min(remaining, max(0.0, deadline - self._now()))
            if remaining <= 0:
                break
            self._sleep(remaining)
        self._monitor_active()
        return totals

    def shutdown(
        self,
        *,
        timeout: float | None = None,
        deadline_seconds: float | None = None,
    ) -> ShutdownReport:
        """Stop claims, request cooperative cancellation, and honor a deadline."""

        if timeout is not None and deadline_seconds is not None:
            raise RuntimeConfigurationError("timeout and deadline_seconds are mutually exclusive")
        selected = self.shutdown_timeout_seconds if timeout is None and deadline_seconds is None else (
            timeout if timeout is not None else deadline_seconds
        )
        bounded = _finite_number(
            selected,
            name="shutdown_timeout_seconds",
            minimum=0.0,
            maximum=_MAX_TIMEOUT_SECONDS,
        )
        with self._lock:
            if self._closed:
                return ShutdownReport(True, False, 0, len(self._active))
            self._closing = True
            self._stop_requested = True
            executions = tuple(self._active.values())
        cancelled = 0
        for execution in executions:
            with execution.lock:
                if not execution.logical_done.is_set():
                    execution.cancel_requested = True
                    execution.token._request()
                    cancelled += 1
        self._emit("worker.runtime.stopping", reason="shutdown")
        deadline = self._now() + bounded
        while True:
            self._monitor_active()
            with self._lock:
                active = tuple(self._active.values())
            if not active:
                break
            if self._now() >= deadline:
                break
            self._sleep(min(self.poll_interval_seconds, max(0.0, deadline - self._now())))
        self._monitor_active()
        with self._lock:
            remaining = len(self._active)
            self._closed = True
        timed_out = remaining > 0
        self._emit("worker.runtime.stopped", reason="deadline" if timed_out else "drained")
        return ShutdownReport(
            drained=not timed_out,
            timed_out=timed_out,
            cancelled=cancelled,
            active=remaining,
        )

    close = shutdown

    def request_stop(self) -> None:
        with self._lock:
            self._stop_requested = True

    stop = request_stop

    def wait_for_idle(self, *, timeout: float | None = None) -> bool:
        bounded = None if timeout is None else _finite_number(
            timeout,
            name="timeout",
            minimum=0.0,
            maximum=_MAX_TIMEOUT_SECONDS,
        )
        deadline = None if bounded is None else self._now() + bounded
        while True:
            self._monitor_active()
            if self.active_count == 0:
                return True
            if deadline is not None and self._now() >= deadline:
                return False
            remaining = self.poll_interval_seconds
            if deadline is not None:
                remaining = min(remaining, max(0.0, deadline - self._now()))
            self._sleep(remaining)

    def __enter__(self) -> "RealWorkerRuntime":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.shutdown()


WorkerRuntime = RealWorkerRuntime


__all__ = [
    "CancellationToken",
    "Handler",
    "OperationHandler",
    "OperationRegistry",
    "RealWorkerRuntime",
    "RuntimeConfigurationError",
    "RuntimeHealth",
    "RuntimeMetrics",
    "RuntimeClosed",
    "RunResult",
    "ShutdownReport",
    "StartupReport",
    "StartupValidationError",
    "WorkerCancelled",
    "WorkerRuntime",
]
