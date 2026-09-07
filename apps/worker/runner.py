"""Bounded process-local job runner seam.

This module deliberately provides an in-process boundary only.  Jobs live in
memory, are lost on process restart, and have no distributed durability or
restart recovery.  The queue is a bounded deque and each runner owns a fixed
number of daemon threads.  There are no automatic retries: an integrator must
make any retry a new, explicit submission after inspecting the terminal result.

The normal integration path is::

    runner = LocalJobRunner(max_pending=32, max_workers=2)
    job_id = runner.submit(run_ingestion, document_id)
    snapshot = runner.get_status(job_id)
    runner.cancel(job_id)  # succeeds while the job is still queued
    runner.shutdown()

For deterministic tests, construct with ``autostart=False`` and use
``run_next()`` or ``drain()``.  A task can opt into ``JobContext`` and call
``context.checkpoint()`` to honor a running cancellation request.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import re
from threading import Condition, Event, Thread
from time import monotonic, time
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping
import uuid

from rick_observability import emit_safely, opaque_ref


RUNNER_CONTRACT_VERSION = "worker-runner-v1"

QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
PUBLISHED = "published"
FAILED = "failed"
CANCELLED = "cancelled"

JobStatus = Literal["queued", "running", "completed", "published", "failed", "cancelled"]
TERMINAL_STATES = frozenset({COMPLETED, PUBLISHED, FAILED, CANCELLED})

_MAX_WORKERS = 64
_MAX_PENDING = 100_000
_MAX_RETAINED = 100_000
_MAX_PROGRESS_HISTORY = 256
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,47}$")
_SAFE_TEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,127}$")
_UNSAFE_MARKERS = (
    "authorization",
    "bearer",
    "credential",
    "exception",
    "password",
    "provider response",
    "secret",
    "stack trace",
    "token",
)


class JobRunnerError(RuntimeError):
    """Base class for safe runner control errors."""


class JobRejected(JobRunnerError):
    """Submission was rejected without retaining or executing the task."""

    def __init__(self, code: str):
        self.code = code
        messages = {
            "queue_full": "Job queue is full.",
            "history_full": "Job history is full.",
            "runner_closed": "Job runner is shut down.",
            "duplicate_job_id": "Job ID is already in use.",
        }
        super().__init__(messages.get(code, "Job submission was rejected."))


class RunnerClosed(JobRejected):
    """Compatibility-specific name for submissions after shutdown."""

    def __init__(self):
        super().__init__("runner_closed")


class JobCancelled(Exception):
    """A cooperative task cancellation signal for ``JobContext.checkpoint``."""


SafeValue = str | int | float | bool | None


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _safe_text(value: object, *, fallback: str | None = None) -> str | None:
    if not isinstance(value, str):
        return fallback
    candidate = value.strip()
    lowered = candidate.lower()
    if (
        not candidate
        or len(candidate) > 128
        or not _SAFE_TEXT_RE.fullmatch(candidate)
        or any(marker in lowered for marker in _UNSAFE_MARKERS)
    ):
        return fallback
    return candidate


def _safe_metadata(metadata: Mapping[str, object] | None) -> dict[str, SafeValue]:
    """Keep only small, scalar, non-sensitive metadata for status responses."""

    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise TypeError("metadata must be a mapping")

    safe: dict[str, SafeValue] = {}
    # Inspect a finite prefix even if a caller supplies a custom unbounded
    # mapping.  Status metadata is an observability hint, never a data bag.
    for index, (key, value) in enumerate(metadata.items()):
        if index >= 64:
            break
        if not isinstance(key, str) or not _SAFE_KEY_RE.fullmatch(key):
            continue
        lowered_key = key.lower()
        if any(marker.replace(" ", "") in lowered_key.replace("_", "") for marker in _UNSAFE_MARKERS):
            continue
        if value is None or isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, int) and not isinstance(value, bool) and -(2**53) < value < 2**53:
            safe[key] = value
        elif isinstance(value, float) and math.isfinite(value) and abs(value) < 1e15:
            safe[key] = value
        elif isinstance(value, str):
            cleaned = _safe_text(value)
            if cleaned is not None:
                safe[key] = cleaned
    return dict(list(safe.items())[:16])


def _validate_limit(name: str, value: object, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}.")
    return value


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """Optional bounded success outcome returned by an integration task."""

    status: Literal["completed", "published", "cancelled"] = COMPLETED
    stage: str = COMPLETED
    progress: float = 1.0

    def __post_init__(self) -> None:
        if self.status not in {COMPLETED, PUBLISHED, CANCELLED}:
            raise ValueError("JobOutcome status must be completed, published, or cancelled.")
        if _safe_text(self.stage) is None:
            raise ValueError("JobOutcome stage is invalid.")
        if not _finite_number(self.progress) or not 0.0 <= float(self.progress) <= 1.0:
            raise ValueError("JobOutcome progress must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """Safe, immutable job state suitable for an API response."""

    contract_version: str
    job_id: str
    status: JobStatus
    stage: str
    progress: float
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    error_code: str | None = None
    safe_error_message: str | None = None
    cancel_requested: bool = False
    metadata: Mapping[str, SafeValue] = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    @property
    def is_terminal(self) -> bool:
        return self.terminal

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_code": self.error_code,
            "safe_error_message": self.safe_error_message,
            "cancel_requested": self.cancel_requested,
            "metadata": dict(self.metadata),
        }

    to_dict = as_dict

    def __getitem__(self, key: str) -> object:
        return self.as_dict()[key]

    def get(self, key: str, default: object = None) -> object:
        return self.as_dict().get(key, default)


@dataclass(slots=True)
class _Job:
    job_id: str
    task: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    metadata: dict[str, SafeValue]
    with_context: bool
    status: JobStatus = QUEUED
    stage: str = QUEUED
    progress: float = 0.0
    created_at: float = field(default_factory=time)
    started_at: float | None = None
    finished_at: float | None = None
    error_code: str | None = None
    safe_error_message: str | None = None
    cancel_requested: bool = False
    cancel_event: Event = field(default_factory=Event)
    # Keep only a finite, sanitized tail for internal heartbeat diagnostics.
    # The public snapshot intentionally exposes only the current progress.
    progress_history: deque[tuple[str, float]] = field(
        default_factory=lambda: deque(maxlen=_MAX_PROGRESS_HISTORY)
    )


class JobContext:
    """Small cooperative context exposed only when ``with_context=True``."""

    __slots__ = ("_runner", "job_id", "_cancel_event")

    def __init__(self, runner: "LocalJobRunner", job_id: str, cancel_event: Event):
        self._runner = runner
        self.job_id = job_id
        self._cancel_event = cancel_event

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    def is_cancel_requested(self) -> bool:
        return self.cancel_requested

    def checkpoint(self) -> None:
        if self.cancel_requested:
            raise JobCancelled()

    def update(self, *, stage: str, progress: float) -> bool:
        return self._runner.update_progress(self.job_id, stage=stage, progress=progress)


class LocalJobRunner:
    """A bounded, in-memory runner for one application process.

    ``max_pending`` counts queued jobs, excluding jobs already claimed by a
    worker.  ``max_workers`` is the exact upper bound on concurrently running
    tasks.  Terminal snapshots are retained up to ``max_retained``; progress
    diagnostics retain only a fixed tail and no task return value is retained,
    which keeps this status seam safe and bounded.
    """

    def __init__(
        self,
        max_pending: int = 100,
        max_workers: int = 1,
        *,
        max_retained: int = 1_000,
        autostart: bool = True,
        start_workers: bool | None = None,
        start: bool | None = None,
        thread_name_prefix: str = "rick-local-job",
        event_sink: object | None = None,
    ) -> None:
        self.max_pending = _validate_limit("max_pending", max_pending, maximum=_MAX_PENDING)
        self.max_workers = _validate_limit("max_workers", max_workers, maximum=_MAX_WORKERS)
        self.max_retained = _validate_limit("max_retained", max_retained, maximum=_MAX_RETAINED)
        if start_workers is not None:
            autostart = start_workers
        if start is not None:
            autostart = start
        if not isinstance(autostart, bool):
            raise ValueError("autostart must be a boolean.")

        self._condition = Condition()
        self._pending: deque[_Job] = deque()
        self._jobs: dict[str, _Job] = {}
        self._threads: list[Thread] = []
        self._active = 0
        self._started = False
        self._closing = False
        self._thread_name_prefix = _safe_text(thread_name_prefix, fallback="rick-local-job") or "rick-local-job"
        self._event_sink = event_sink
        if autostart:
            self.start()

    @property
    def process_local(self) -> bool:
        return True

    @property
    def is_shutdown(self) -> bool:
        with self._condition:
            return self._closing

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending)

    @property
    def active_count(self) -> int:
        with self._condition:
            return self._active

    @property
    def worker_count(self) -> int:
        with self._condition:
            return len(self._threads)

    def _emit(self, event_name: str, **fields: object) -> None:
        """Emit bounded lifecycle metadata without retaining job arguments."""

        emit_safely(self._event_sink, event_name, fields)

    @staticmethod
    def _job_ref(job_id: str) -> str:
        return opaque_ref(job_id)

    def start(self) -> "LocalJobRunner":
        """Start the fixed worker set; safe to call repeatedly before shutdown."""

        with self._condition:
            if self._closing:
                raise RunnerClosed()
            if self._started:
                return self
            self._started = True
            threads = [
                Thread(
                    target=self._worker_loop,
                    name=f"{self._thread_name_prefix}-{index + 1}",
                    daemon=True,
                )
                for index in range(self.max_workers)
            ]
        # Publish the runner barrier before any worker can consume a queued
        # job. This makes the observable sequence deterministic:
        # enqueued -> runner.started -> job.started -> terminal.
        self._emit("worker.runner.started", workers=len(threads))
        with self._condition:
            if self._closing:
                return self
            self._threads.extend(threads)
            for thread in threads:
                thread.start()
        return self

    def submit(
        self,
        task: Callable[..., Any],
        *args: Any,
        job_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
        with_context: bool = False,
        **kwargs: Any,
    ) -> str:
        """Submit one task or raise ``JobRejected`` without executing it."""

        if not callable(task):
            raise TypeError("task must be callable")
        if not isinstance(with_context, bool):
            raise TypeError("with_context must be a boolean")
        selected_id = job_id or f"job-{uuid.uuid4().hex[:16]}"
        if not isinstance(selected_id, str) or not _JOB_ID_RE.fullmatch(selected_id):
            raise ValueError("job_id must be a bounded safe identifier")
        safe_metadata = _safe_metadata(metadata)

        with self._condition:
            if self._closing:
                raise RunnerClosed()
            if selected_id in self._jobs:
                raise JobRejected("duplicate_job_id")
            if len(self._pending) >= self.max_pending:
                raise JobRejected("queue_full")
            if len(self._jobs) >= self.max_retained and not self._evict_terminal_locked():
                raise JobRejected("history_full")
            job = _Job(
                job_id=selected_id,
                task=task,
                args=args,
                kwargs=dict(kwargs),
                metadata=safe_metadata,
                with_context=with_context,
            )
            self._jobs[selected_id] = job
            self._pending.append(job)
            self._condition.notify()
        self._emit(
            "worker.job.enqueued",
            job_ref=self._job_ref(selected_id),
            status=QUEUED,
        )
        return selected_id

    def try_submit(self, task: Callable[..., Any], *args: Any, **kwargs: Any) -> str | None:
        """Return a job ID, or ``None`` for a safe capacity/lifecycle rejection."""

        try:
            return self.submit(task, *args, **kwargs)
        except JobRejected:
            return None

    enqueue = submit

    def get_status(self, job_id: str) -> JobSnapshot | None:
        with self._condition:
            job = self._jobs.get(job_id)
            return self._snapshot_locked(job) if job is not None else None

    status = get_status

    def list_status(self) -> list[JobSnapshot]:
        with self._condition:
            return [self._snapshot_locked(job) for job in self._jobs.values()]

    def cancel(self, job_id: str) -> bool:
        """Cancel a queued job; running jobs receive only a cooperative request.

        Python threads cannot be safely interrupted.  Consequently a running
        job remains running and ``cancel`` returns ``False``; a task using
        ``JobContext`` may observe the request and raise ``JobCancelled`` at a
        safe point.  A published/completed artifact is never relabeled by a
        late cancellation request.
        """

        event_name: str | None = None
        event_status: str | None = None
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None or job.status in TERMINAL_STATES:
                return False
            if job.status == QUEUED:
                try:
                    self._pending.remove(job)
                except ValueError:
                    # A worker claimed it between the status check and remove.
                    if job.status != QUEUED:
                        return False
                    return False
                self._finish_locked(job, status=CANCELLED, stage=CANCELLED, progress=0.0)
                self._condition.notify_all()
                event_name = "worker.job.cancelled"
                event_status = job.status
                result = True
            else:
                job.cancel_requested = True
                job.cancel_event.set()
                self._condition.notify_all()
                event_name = "worker.job.cancel_requested"
                event_status = job.status
                result = False
        self._emit(
            event_name or "worker.job.cancel_requested",
            job_ref=self._job_ref(job_id),
            status=event_status or "unknown",
        )
        return result

    def update_progress(self, job_id: str, *, stage: str, progress: float) -> bool:
        """Update bounded non-terminal progress for a cooperative task."""

        safe_stage = _safe_text(stage)
        if safe_stage is None or not _finite_number(progress) or not 0.0 <= float(progress) <= 1.0:
            return False
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None or job.status in TERMINAL_STATES:
                return False
            job.stage = safe_stage
            job.progress = float(progress)
            job.progress_history.append((safe_stage, job.progress))
            return True

    def wait_for_terminal(self, job_id: str, timeout: float | None = None) -> JobSnapshot | None:
        """Wait for a known job's terminal snapshot without polling sleeps."""

        if timeout is not None and (not _finite_number(timeout) or float(timeout) < 0):
            raise ValueError("timeout must be non-negative or None")
        deadline = None if timeout is None else monotonic() + float(timeout)
        with self._condition:
            while True:
                job = self._jobs.get(job_id)
                if job is None:
                    return None
                if job.status in TERMINAL_STATES:
                    return self._snapshot_locked(job)
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    return self._snapshot_locked(job)
                self._condition.wait(remaining)

    def run_next(self) -> JobSnapshot | None:
        """Synchronously run one queued task; intended for deterministic tests."""

        job = self._claim_next()
        if job is None:
            return None
        self._execute(job)
        return self.get_status(job.job_id)

    def drain(self, limit: int | None = None) -> list[JobSnapshot]:
        """Synchronously run a finite pending batch for deterministic tests."""

        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
            raise ValueError("limit must be a non-negative integer or None")
        snapshots: list[JobSnapshot] = []
        while limit is None or len(snapshots) < limit:
            snapshot = self.run_next()
            if snapshot is None:
                break
            snapshots.append(snapshot)
        return snapshots

    def shutdown(
        self,
        wait: bool = True,
        *,
        cancel_pending: bool = True,
        timeout: float | None = None,
    ) -> None:
        """Stop accepting work and optionally wait for running tasks.

        By default queued tasks are terminally cancelled.  Running tasks are
        allowed to finish (or honor their cooperative context request), since
        forcibly interrupting a task could leave a published artifact partial.
        """

        if not isinstance(wait, bool) or not isinstance(cancel_pending, bool):
            raise TypeError("wait and cancel_pending must be booleans")
        if timeout is not None and (not _finite_number(timeout) or float(timeout) < 0):
            raise ValueError("timeout must be non-negative or None")
        cancelled_ids: list[str] = []
        with self._condition:
            if not self._closing:
                self._closing = True
                if cancel_pending or not self._started:
                    while self._pending:
                        job = self._pending.popleft()
                        self._finish_locked(job, status=CANCELLED, stage=CANCELLED, progress=0.0)
                        cancelled_ids.append(job.job_id)
                self._condition.notify_all()
            threads = list(self._threads)

        for job_id in cancelled_ids:
            self._emit(
                "worker.job.cancelled",
                job_ref=self._job_ref(job_id),
                status=CANCELLED,
                reason="shutdown",
            )

        if wait:
            deadline = None if timeout is None else monotonic() + float(timeout)
            for thread in threads:
                remaining = None if deadline is None else max(0.0, deadline - monotonic())
                thread.join(remaining)
            with self._condition:
                self._condition.notify_all()

    close = shutdown

    def __enter__(self) -> "LocalJobRunner":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.shutdown()

    def _worker_loop(self) -> None:
        while True:
            job = self._claim_next(wait=True)
            if job is None:
                return
            self._execute(job)

    def _claim_next(self, *, wait: bool = False) -> _Job | None:
        with self._condition:
            while not self._pending:
                if not wait or self._closing:
                    return None
                self._condition.wait()
            job = self._pending.popleft()
            if job.status != QUEUED:
                return self._claim_next(wait=wait)
            job.status = RUNNING
            job.stage = RUNNING
            job.progress = max(job.progress, 0.0)
            job.started_at = time()
            self._active += 1
            self._condition.notify_all()
        self._emit(
            "worker.job.started",
            job_ref=self._job_ref(job.job_id),
            status=job.status,
        )
        return job

    def _execute(self, job: _Job) -> None:
        try:
            if job.with_context:
                result = job.task(JobContext(self, job.job_id, job.cancel_event), *job.args, **job.kwargs)
            else:
                result = job.task(*job.args, **job.kwargs)
            if isinstance(result, JobOutcome):
                status: JobStatus = result.status
                stage = _safe_text(result.stage, fallback=COMPLETED) or COMPLETED
                progress = float(result.progress)
            else:
                status = COMPLETED
                stage = COMPLETED
                progress = 1.0
            with self._condition:
                self._finish_locked(job, status=status, stage=stage, progress=progress)
                self._condition.notify_all()
            self._emit_terminal(job)
        except JobCancelled:
            with self._condition:
                self._finish_locked(job, status=CANCELLED, stage=CANCELLED, progress=job.progress)
                self._condition.notify_all()
            self._emit_terminal(job)
        except Exception as exc:
            # The exception object and message are deliberately discarded.
            # Only a bounded, known code is retained for API observability.
            error_code = getattr(exc, "code", None)
            if not isinstance(error_code, str) or not _SAFE_KEY_RE.fullmatch(error_code):
                error_code = "job_failed"
            with self._condition:
                self._finish_locked(
                    job,
                    status=FAILED,
                    stage=FAILED,
                    progress=job.progress,
                    error_code=error_code,
                    safe_error_message="Job failed.",
                )
                self._condition.notify_all()
            self._emit_terminal(job)

    def _emit_terminal(self, job: _Job) -> None:
        fields: dict[str, object] = {
            "job_ref": self._job_ref(job.job_id),
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
        }
        if job.error_code is not None:
            fields["error_code"] = job.error_code
        self._emit("worker.job.terminal", **fields)

    def _finish_locked(
        self,
        job: _Job,
        *,
        status: JobStatus,
        stage: str,
        progress: float,
        error_code: str | None = None,
        safe_error_message: str | None = None,
    ) -> None:
        job.status = status
        job.stage = _safe_text(stage, fallback=FAILED if status == FAILED else COMPLETED) or COMPLETED
        job.progress = min(1.0, max(0.0, float(progress)))
        job.error_code = error_code
        job.safe_error_message = safe_error_message
        if status in TERMINAL_STATES:
            job.finished_at = time()
            if status in {COMPLETED, PUBLISHED}:
                job.progress = 1.0
        if self._active and job.started_at is not None and status in TERMINAL_STATES:
            # Queued cancellation has no started_at and therefore does not
            # decrement active_count; claimed jobs do.
            self._active -= 1
        job.task = _noop
        job.args = ()
        job.kwargs.clear()

    def _evict_terminal_locked(self) -> bool:
        for old_id, old_job in tuple(self._jobs.items()):
            if old_job.status in TERMINAL_STATES:
                del self._jobs[old_id]
                return True
        return False

    def _snapshot_locked(self, job: _Job) -> JobSnapshot:
        return JobSnapshot(
            contract_version=RUNNER_CONTRACT_VERSION,
            job_id=job.job_id,
            status=job.status,
            stage=job.stage,
            progress=job.progress,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_code=job.error_code,
            safe_error_message=job.safe_error_message,
            cancel_requested=job.cancel_requested,
            metadata=MappingProxyType(dict(job.metadata)),
        )


def _noop(*args: Any, **kwargs: Any) -> None:
    return None


# A commonly expected spelling for integrators that prefer the boundary name.
BoundedJobRunner = LocalJobRunner


__all__ = [
    "BoundedJobRunner",
    "CANCELLED",
    "COMPLETED",
    "FAILED",
    "JobCancelled",
    "JobContext",
    "JobOutcome",
    "JobRejected",
    "JobRunnerError",
    "JobSnapshot",
    "JobStatus",
    "LocalJobRunner",
    "PUBLISHED",
    "QUEUED",
    "RUNNING",
    "RunnerClosed",
    "RUNNER_CONTRACT_VERSION",
    "TERMINAL_STATES",
]
