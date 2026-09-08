"""Bounded PostgreSQL queue consumer for the external ingestion runtime.

The consumer owns claim/processing/ack/fail transitions, while the handler
owns document parsing and publication. It is deliberately synchronous and
does not create a database or Redis client; the composition root supplies both
the queue and the handler. A process supervisor can call ``run_forever`` in a
separate worker process.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from threading import Event, Thread
from time import monotonic, sleep
from collections.abc import Callable, Mapping
from typing import Any

try:
    from .postgres_queue import PostgresQueueLeaseError
except ImportError:  # executable worker package placed directly on sys.path
    from postgres_queue import PostgresQueueLeaseError


_SAFE_ERRORS = frozenset({
    "provider_timeout", "provider_unavailable", "storage_unavailable",
    "lock_unavailable", "validation_error", "ingestion_failed",
    "cancelled", "recovery_required",
})


@dataclass(frozen=True, slots=True)
class WorkerBatchResult:
    claimed: int = 0
    published: int = 0
    failed: int = 0
    cancelled: int = 0


class _LeaseLost(RuntimeError):
    code = "lock_unavailable"


class _WorkerTimeout(RuntimeError):
    code = "provider_timeout"


class PostgresIngestionWorker:
    """Consume durable jobs with owner-bound leases and bounded polling."""

    def __init__(
        self,
        queue: object,
        handler: Callable[[object], object],
        *,
        worker_id: str,
        poll_interval_seconds: float = 1.0,
        max_batch: int = 1,
        handler_timeout_seconds: float = 300.0,
        event_sink: object | None = None,
        sleep_fn: Callable[[float], object] = sleep,
    ) -> None:
        if queue is None or not callable(getattr(queue, "claim", None)):
            raise ValueError("queue is required")
        if not callable(handler):
            raise ValueError("handler is required")
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 128:
            raise ValueError("worker_id is invalid")
        if isinstance(poll_interval_seconds, bool) or not isinstance(poll_interval_seconds, (int, float)):
            raise ValueError("poll interval is invalid")
        if not 0.01 <= float(poll_interval_seconds) <= 300:
            raise ValueError("poll interval is out of range")
        if isinstance(max_batch, bool) or not isinstance(max_batch, int) or not 1 <= max_batch <= 100:
            raise ValueError("max_batch is out of range")
        if (
            isinstance(handler_timeout_seconds, bool)
            or not isinstance(handler_timeout_seconds, (int, float))
            or not 0.01 <= float(handler_timeout_seconds) <= 24 * 3600
        ):
            raise ValueError("handler timeout is out of range")
        if not callable(sleep_fn):
            raise ValueError("sleep function is invalid")
        self.queue = queue
        self.handler = handler
        self.worker_id = worker_id.strip()
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.max_batch = max_batch
        self.handler_timeout_seconds = float(handler_timeout_seconds)
        self.event_sink = event_sink
        self._sleep = sleep_fn
        self._stop = Event()
        self._closed = False

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def stop(self) -> None:
        self._stop.set()

    shutdown = stop

    def health_check(self) -> bool:
        return not self._closed and callable(getattr(self.queue, "claim", None))

    def _emit(self, name: str, **fields: object) -> None:
        sink = self.event_sink
        if sink is None:
            return
        emitter = getattr(sink, "emit", None)
        if not callable(emitter):
            emitter = sink if callable(sink) else None
        if not callable(emitter):
            return
        safe = {key: value for key, value in fields.items() if key in {"claimed", "published", "failed", "cancelled"}}
        try:
            emitter({"type": name, **safe})
        except Exception:
            return

    @staticmethod
    def _field(record: object, name: str, default: Any = None) -> Any:
        if isinstance(record, Mapping):
            return record.get(name, default)
        return getattr(record, name, default)

    @staticmethod
    def _error_code(error: object) -> str:
        code = getattr(error, "code", None)
        if isinstance(code, str) and code in _SAFE_ERRORS:
            return code
        return "ingestion_failed"

    def _prepare(self, record: object) -> object:
        mark = getattr(self.queue, "mark_processing", None)
        token = self._field(record, "lease_token")
        job_id = self._field(record, "job_id")
        if callable(mark) and isinstance(token, str) and isinstance(job_id, str):
            return mark(job_id, lease_token=token)
        return record

    def _cancel_claim(self, record: object) -> None:
        cancel = getattr(self.queue, "cancel", None)
        token = self._field(record, "lease_token")
        job_id = self._field(record, "job_id")
        if not callable(cancel) or not isinstance(job_id, str):
            return
        try:
            cancel(job_id, lease_token=token if isinstance(token, str) else None)
        except Exception:
            # A lease that cannot be cancelled is recovered by the queue's
            # expiry path; the worker does not disclose the adapter error.
            return

    @staticmethod
    def _document_id(result: object) -> str | None:
        value = result.get("document_id") if isinstance(result, Mapping) else getattr(result, "document_id", None)
        return value if isinstance(value, str) and value.strip() else None

    def _invoke_handler(self, prepared: object, lease_lost: Event) -> object:
        """Run one handler with a wall-clock bound independent of its runtime."""

        try:
            parameters = inspect.signature(self.handler).parameters.values()
            accepts_lease_signal = "lease_lost_check" in {parameter.name for parameter in parameters} or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
            )
        except (TypeError, ValueError):
            accepts_lease_signal = False

        completed = Event()
        result_box: dict[str, object] = {}

        def invoke() -> None:
            try:
                result_box["result"] = (
                    self.handler(prepared, lease_lost_check=lease_lost.is_set)
                    if accepts_lease_signal
                    else self.handler(prepared)
                )
            except BaseException as error:
                result_box["error"] = error
            finally:
                completed.set()

        Thread(target=invoke, name="rick-ingestion-handler", daemon=True).start()
        if not completed.wait(self.handler_timeout_seconds):
            raise _WorkerTimeout()
        error = result_box.get("error")
        if isinstance(error, BaseException):
            raise error
        result = result_box.get("result")
        if inspect.isawaitable(result):
            raise RuntimeError("async handler is not supported")
        return result

    def _run_record(self, record: object) -> str:
        if self._stop.is_set():
            self._cancel_claim(record)
            return "cancelled"
        prepared = record
        heartbeat_stop = Event()
        lease_lost = Event()
        heartbeat_thread: Thread | None = None
        job_id = self._field(record, "job_id")
        token = self._field(record, "lease_token")
        try:
            prepared = self._prepare(record)
            job_id = self._field(prepared, "job_id") or job_id
            token = self._field(prepared, "lease_token") or token
            heartbeat = getattr(self.queue, "heartbeat", None)
            lease_seconds = getattr(self.queue, "lease_seconds", None)
            if callable(heartbeat) and isinstance(job_id, str) and isinstance(token, str):
                interval = max(0.1, min(10.0, float(lease_seconds or 30.0) / 3.0))

                def keep_lease() -> None:
                    while not heartbeat_stop.wait(interval):
                        try:
                            heartbeat(job_id, lease_token=token)
                        except Exception:
                            lease_lost.set()
                            return

                heartbeat_thread = Thread(target=keep_lease, name="rick-ingestion-heartbeat", daemon=True)
                heartbeat_thread.start()
            result = self._invoke_handler(prepared, lease_lost)
            if lease_lost.is_set():
                raise _LeaseLost()
            document_id = self._document_id(result)
            bind = getattr(self.queue, "bind_document", None)
            if callable(bind) and document_id and isinstance(job_id, str) and isinstance(token, str):
                bind(job_id, document_id, lease_token=token)
            ack = getattr(self.queue, "ack", None)
            if not callable(ack) or not isinstance(job_id, str) or not isinstance(token, str):
                raise RuntimeError("queue acknowledgement is unavailable")
            ack(job_id, lease_token=token)
            return "published"
        except PostgresQueueLeaseError:
            # The durable queue owns lease recovery. Treat a lost lease as a
            # failed local attempt without trying to mutate a new owner.
            return "failed"
        except Exception as error:
            fail = getattr(self.queue, "fail", None)
            if callable(fail) and isinstance(job_id, str) and isinstance(token, str):
                try:
                    fail(job_id, lease_token=token, error=self._error_code(error))
                except Exception:
                    pass
            return "failed"
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1.0)

    def run_once(self) -> WorkerBatchResult:
        if self._closed:
            return WorkerBatchResult()
        try:
            records = tuple(self.queue.claim(worker_id=self.worker_id, limit=self.max_batch))
        except Exception:
            return WorkerBatchResult()
        result = WorkerBatchResult(claimed=len(records))
        published = failed = cancelled = 0
        for record in records:
            outcome = self._run_record(record)
            if outcome == "published":
                published += 1
            elif outcome == "cancelled":
                cancelled += 1
            else:
                failed += 1
        result = WorkerBatchResult(
            claimed=len(records), published=published, failed=failed, cancelled=cancelled
        )
        self._emit("worker.batch", claimed=result.claimed, published=result.published,
                   failed=result.failed, cancelled=result.cancelled)
        return result

    def run_forever(self, *, max_runtime_seconds: float | None = None) -> WorkerBatchResult:
        """Poll until ``stop`` or an optional bounded runtime expires."""

        if max_runtime_seconds is not None and (
            isinstance(max_runtime_seconds, bool)
            or not isinstance(max_runtime_seconds, (int, float))
            or not 0 < float(max_runtime_seconds) <= 24 * 3600
        ):
            raise ValueError("max runtime is out of range")
        deadline = None if max_runtime_seconds is None else monotonic() + float(max_runtime_seconds)
        totals = WorkerBatchResult()
        while not self._stop.is_set() and (deadline is None or monotonic() < deadline):
            batch = self.run_once()
            totals = WorkerBatchResult(
                claimed=totals.claimed + batch.claimed,
                published=totals.published + batch.published,
                failed=totals.failed + batch.failed,
                cancelled=totals.cancelled + batch.cancelled,
            )
            if batch.claimed == 0:
                remaining = self.poll_interval_seconds if deadline is None else max(0.0, deadline - monotonic())
                if remaining <= 0:
                    break
                self._sleep(min(self.poll_interval_seconds, remaining))
        return totals

    def close(self) -> None:
        self._closed = True
        self.stop()


__all__ = ["PostgresIngestionWorker", "WorkerBatchResult"]
