"""Bounded, redacted event sinks for local process boundaries."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import math
from threading import Event, RLock, Thread
from typing import Any

from rick_observability.redaction import safe_event, safe_text


MAX_EVENT_BUFFER = 100_000
DEFAULT_EMIT_TIMEOUT_SECONDS = 0.25


def opaque_ref(value: object) -> str:
    """Return a stable short reference without retaining an opaque identifier."""

    candidate = safe_text(value, limit=256) or "invalid"
    return hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:16]


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
    """Send one redacted event with a bounded callback wait.

    A caller-owned sink is outside the state transaction. The delivery runs in
    a daemon thread when a timeout is configured, so a blocked collector cannot
    pin a worker or lifecycle shutdown forever. The return value is only a
    delivery observation; event delivery never raises into the caller.
    """

    if sink is None:
        return True
    try:
        event = safe_event(fields, event_name=event_name)
        emitter = getattr(sink, "emit", None)
        if not callable(emitter) and not callable(sink):
            return False

        def deliver() -> None:
            try:
                payload = deepcopy(event)
                if callable(emitter):
                    emitter(payload)
                else:
                    sink(payload)
            except Exception:
                return

        if timeout is None:
            deliver()
            return True
        try:
            bounded_timeout = float(timeout)
        except (TypeError, ValueError):
            bounded_timeout = 0.0
        if not math.isfinite(bounded_timeout) or bounded_timeout < 0:
            bounded_timeout = 0.0
        completed = Event()

        def bounded_deliver() -> None:
            try:
                deliver()
            finally:
                completed.set()

        Thread(
            target=bounded_deliver,
            name="rick-observability-sink",
            daemon=True,
        ).start()
        completed.wait(bounded_timeout)
        return completed.is_set()
    except Exception:
        # Telemetry is deliberately best-effort.  Queue/runner state remains
        # authoritative even when an injected local sink is broken.
        return False


__all__ = [
    "BoundedEventBuffer", "DEFAULT_EMIT_TIMEOUT_SECONDS", "MAX_EVENT_BUFFER",
    "emit_safely", "opaque_ref",
]
