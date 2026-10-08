"""Bounded, redacted event sinks for local process boundaries."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import inspect
import math
from threading import Condition, Event, Lock, RLock, Thread
import time
from typing import Any

from rick_observability.redaction import safe_event, safe_text


MAX_EVENT_BUFFER = 100_000
DEFAULT_EMIT_TIMEOUT_SECONDS = 0.25
MAX_SINK_QUEUE = 1_024
MAX_SINK_WORKERS = 8
SHUTDOWN_TIMEOUT_SECONDS = 2.0
DELIVERY_COUNTERS = (
    "sink.delivery.emitted", "sink.delivery.failed", "sink.delivery.dropped",
    "sink.delivery.timeout", "sink.delivery.shutdown_timeout",
)


def opaque_ref(value: object) -> str:
    """Return a stable short reference without retaining an opaque identifier."""

    candidate = safe_text(value, limit=256) or "invalid"
    return hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:16]


_MISSING = object()


def _may_have_emitter(sink: object) -> bool:
    """Inspect sink shape without executing a descriptor on the caller."""

    try:
        if inspect.getattr_static(sink, "emit", _MISSING) is not _MISSING:
            return True
        if inspect.getattr_static(type(sink), "__getattr__", _MISSING) is not _MISSING:
            return True
        return inspect.getattr_static(
            type(sink), "__getattribute__", object.__getattribute__
        ) is not object.__getattribute__
    except Exception:
        return False


class BoundedEventBuffer:
    """Thread-safe ring for already-local event observation.

    The buffer retains only normalized ``{"event", "fields"}`` records.  Both
    ingestion and snapshots cross a deep-copy boundary so a caller or sink
    cannot mutate retained history.  It is intentionally not a publisher.
    """

    __slots__ = ("_capacity", "_events", "_lock")

    def __init__(self, max_events: int = 256) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= MAX_EVENT_BUFFER:
            raise ValueError(f"max_events must be an integer between 1 and {MAX_EVENT_BUFFER}")
        self._capacity = max_events
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._lock = RLock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._events)

    def emit(self, event: Mapping[str, object], *, event_name: str | None = None) -> None:
        """Retain one safe event or one raw field mapping.

        ``emit_safely`` passes a normalized event.  Direct callers may pass a
        field mapping with ``event_name``; either form is redacted again at
        this boundary.
        """

        if not isinstance(event, Mapping):
            raise TypeError("event must be a mapping")
        normalized_name: object = event_name or "event"
        fields: Mapping[str, object] = event
        if event_name is None:
            candidate_name = event.get("event")
            candidate_fields = event.get("fields")
            if isinstance(candidate_name, str) and isinstance(candidate_fields, Mapping):
                normalized_name = candidate_name
                fields = candidate_fields
        retained = safe_event(fields, event_name=str(normalized_name))
        with self._lock:
            self._events.append(deepcopy(retained))

    def snapshot(self) -> list[dict[str, Any]]:
        """Return an independent copy of the retained event ring."""

        with self._lock:
            return deepcopy(list(self._events))

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def emit_safely(
    sink: object | None,
    event_name: str,
    fields: Mapping[str, object],
    *,
    timeout: float | None = DEFAULT_EMIT_TIMEOUT_SECONDS,
) -> bool:
    """Send one redacted event through the bounded shared delivery lane.

    A caller-owned sink is outside the state transaction. Delivery runs on a
    fixed worker pool draining a finite queue, so a blocked collector cannot
    pin a worker or grow memory: a full lane drops the event, and a timeout
    still returns while the worker holds the slot. The return value is only a
    delivery observation; event delivery never raises into the caller.
    """

    if sink is None:
        return True
    try:
        event = safe_event(fields, event_name=event_name)
        callable_sink = callable(sink)
        has_emitter = _may_have_emitter(sink)
        if not callable_sink and not has_emitter:
            return False

        def deliver() -> None:
            payload = deepcopy(event)
            emitter = getattr(sink, "emit", None) if has_emitter else None
            if callable(emitter):
                emitter(payload)
            elif callable_sink:
                sink(payload)
            else:
                raise TypeError("event sink must be callable or expose emit(event)")

        if timeout is None:
            # ``None`` used to bypass the bounded lane and invoke an arbitrary
            # sink synchronously on the caller thread.  Keep it as a
            # compatibility spelling for the normal bounded timeout instead;
            # operational callers never gain an unbounded delivery mode.
            bounded_timeout = DEFAULT_EMIT_TIMEOUT_SECONDS
        else:
            try:
                bounded_timeout = float(timeout)
            except (TypeError, ValueError):
                bounded_timeout = 0.0
        if not math.isfinite(bounded_timeout) or bounded_timeout < 0:
            bounded_timeout = 0.0
        return _get_delivery().offer(deliver, bounded_timeout)
    except Exception:
        # Telemetry is deliberately best-effort.  Queue/runner state remains
        # authoritative even when an injected local sink is broken.
        return False


class _SinkDelivery:
    """Fixed workers over a finite deque; observable drop/timeout counters."""

    def __init__(self, workers: int = 2, capacity: int = MAX_SINK_QUEUE) -> None:
        if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= MAX_SINK_WORKERS:
            raise ValueError("workers must be an integer between 1 and 8")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= MAX_SINK_QUEUE:
            raise ValueError("capacity must be between 1 and 1024")
        self._capacity = capacity
        self._counters: Counter[str] = Counter()
        self._lock = RLock()
        self._condition = Condition()
        self._closed = False
        self._queue: deque[Any] = deque()
        self._active = 0
        self._threads = tuple(
            Thread(target=self._work, name=f"rick-observability-sink-{index}", daemon=True)
            for index in range(workers)
        )
        for thread in self._threads:
            thread.start()

    def count(self, name: str) -> None:
        with self._lock:
            self._counters[name] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "workers": len(self._threads),
                "capacity": self._capacity,
                "queued": len(self._queue),
                "active": self._active,
                "closed": self._closed,
                "counters": [
                    {"name": name, "total": float(self._counters.get(name, 0))}
                    for name in DELIVERY_COUNTERS
                ],
            }

    def offer(self, deliver: Any, timeout: float) -> bool:
        completed = Event()
        state = [False]
        with self._condition:
            if self._closed:
                self._counter("sink.delivery.dropped")
                return False
            if len(self._queue) >= self._capacity:
                self._counter("sink.delivery.dropped")
                return False
            self._queue.append((deliver, completed, state))
            self._condition.notify()
        if not completed.wait(max(0.0, timeout)):
            self._counter("sink.delivery.timeout")
            return False
        return state[0]

    def shutdown(self, *, timeout: float = SHUTDOWN_TIMEOUT_SECONDS) -> bool:
        try:
            bounded_timeout = float(timeout)
        except (TypeError, ValueError):
            bounded_timeout = 0.0
        if not math.isfinite(bounded_timeout) or bounded_timeout < 0:
            bounded_timeout = 0.0
        began = time.monotonic()
        with self._condition:
            self._closed = True
            self._condition.notify_all()
            while (self._queue or self._active) and (time.monotonic() - began) < bounded_timeout:
                self._condition.wait(timeout=max(0.0, bounded_timeout - (time.monotonic() - began)))
            while self._queue:
                _, completed, _state = self._queue.popleft()
                completed.set()
                self._counter("sink.delivery.dropped")
        for thread in self._threads:
            remaining = bounded_timeout - (time.monotonic() - began)
            if remaining <= 0:
                break
            thread.join(remaining)
        drained = all(not thread.is_alive() for thread in self._threads)
        if not drained:
            self._counter("sink.delivery.shutdown_timeout")
        return drained

    def _work(self) -> None:
        while True:
            with self._condition:
                while not self._closed and not self._queue:
                    self._condition.wait()
                if not self._queue:
                    return
                deliver, completed, state = self._queue.popleft()
                self._active += 1
            try:
                deliver()
                state[0] = True
                self._counter("sink.delivery.emitted")
            except Exception:
                self._counter("sink.delivery.failed")
            finally:
                completed.set()
                with self._condition:
                    self._active -= 1
                    self._condition.notify_all()

    def _counter(self, name: str) -> None:
        with self._lock:
            self._counters[name] += 1


_delivery: _SinkDelivery | None = None
_delivery_lock = Lock()


def _get_delivery() -> _SinkDelivery:
    global _delivery
    with _delivery_lock:
        if _delivery is None:
            _delivery = _SinkDelivery()
        return _delivery


def sink_delivery_snapshot() -> dict[str, Any]:
    """Return lane size, worker, and drop/timeout counters without starting it."""

    with _delivery_lock:
        delivery = _delivery
    if delivery is not None:
        return delivery.snapshot()
    return {
        "workers": 0,
        "capacity": MAX_SINK_QUEUE,
        "queued": 0,
        "active": 0,
        "closed": False,
        "counters": [{"name": name, "total": 0.0} for name in DELIVERY_COUNTERS],
    }


def shutdown_sink_delivery(timeout: float = SHUTDOWN_TIMEOUT_SECONDS) -> bool:
    """Flush an existing lane without allocating threads when it was unused.

    Call after stopping event producers. A previously unused lane is a no-op;
    this function does not prohibit another producer from initializing it later.
    """

    with _delivery_lock:
        delivery = _delivery
    return True if delivery is None else delivery.shutdown(timeout=timeout)


__all__ = [
    "BoundedEventBuffer", "DEFAULT_EMIT_TIMEOUT_SECONDS", "MAX_EVENT_BUFFER",
    "emit_safely", "opaque_ref", "shutdown_sink_delivery", "sink_delivery_snapshot",
]
