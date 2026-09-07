"""Bounded API telemetry composition.

The observability package intentionally provides primitives rather than a
network exporter.  This module is the application seam that records the
request signals and exposes a redacted snapshot to the protected admin
surface.  Route labels are a finite taxonomy; raw paths, query strings and
identities never enter the metric registry.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
import math
import re
from threading import Event, RLock, Thread
from typing import Any, Mapping

try:  # The monorepo runtime exposes this package through PYTHONPATH.
    from rick_observability import (
        AlertRule,
        CounterRegistry,
        Histogram,
        emit_safely,
        opaque_ref,
        safe_event,
    )

    _IMPLEMENTATION = "rick_observability"
except ImportError:  # Keep a minimal, bounded local runtime for packaged API images.
    _IMPLEMENTATION = "api_fallback"

    class _FallbackSnapshot:
        def __init__(self, name: str, labels: Mapping[str, str], count: int, total: float) -> None:
            self.name = name
            self.labels = tuple(sorted(labels.items()))
            self.count = count
            self.total = total

        def as_dict(self) -> dict[str, object]:
            return {
                "name": self.name,
                "labels": dict(self.labels),
                "count": self.count,
                "total": round(self.total, 6),
            }

    class CounterRegistry:
        def __init__(self, *, max_metrics: int = 256) -> None:
            self.max_metrics = max_metrics
            self._values: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[int, float]] = {}
            self._lock = RLock()

        def increment(self, name: str, *, value: float = 1.0, labels: Mapping[str, str] | None = None) -> float:
            key = (name, tuple(sorted((labels or {}).items())))
            with self._lock:
                if key not in self._values and len(self._values) >= self.max_metrics:
                    raise ValueError("metric registry is full")
                count, total = self._values.get(key, (0, 0.0))
                self._values[key] = (count + 1, total + float(value))
                return total + float(value)

        def snapshot(self) -> tuple[_FallbackSnapshot, ...]:
            with self._lock:
                return tuple(
                    _FallbackSnapshot(name, dict(labels), count, total)
                    for (name, labels), (count, total) in sorted(self._values.items())
                )

    class Histogram:
        def __init__(self, name: str, *, max_samples: int = 10_000) -> None:
            self.name = name
            self.max_samples = max_samples
            self._values: deque[float] = deque(maxlen=max_samples)
            self._lock = RLock()

        def observe(self, value: float) -> None:
            with self._lock:
                self._values.append(float(value))

        def snapshot(self) -> dict[str, object]:
            with self._lock:
                values = sorted(self._values)
            if not values:
                return {"name": self.name, "labels": {}, "count": 0, "p50": None, "p95": None, "max": None}
            p50 = values[max(0, (len(values) + 1) // 2 - 1)]
            p95 = values[max(0, (len(values) * 95 + 99) // 100 - 1)]
            return {
                "name": self.name,
                "labels": {},
                "count": len(values),
                "p50": round(p50, 6),
                "p95": round(p95, 6),
                "max": round(values[-1], 6),
            }

    class AlertRule:
        def __init__(self, name: str, max_error_rate: float, max_latency_p95: float | None = None) -> None:
            self.name = name
            self.max_error_rate = max_error_rate
            self.max_latency_p95 = max_latency_p95

        def evaluate(self, *, total: int, errors: int, latency_p95: float | None):
            if total == 0:
                return type("SloDecision", (), {
                    "status": "no_data", "reason": "no observations",
                    "error_rate": None, "latency_p95": latency_p95,
                })()
            error_rate = errors / total
            if error_rate > self.max_error_rate:
                status, reason = "breach", "error rate exceeded budget"
            elif self.max_latency_p95 is not None and (latency_p95 is None or latency_p95 > self.max_latency_p95):
                status, reason = "breach", "latency p95 exceeded budget"
            else:
                status, reason = "healthy", "within configured budget"
            return type("SloDecision", (), {
                "status": status, "reason": reason,
                "error_rate": error_rate, "latency_p95": latency_p95,
            })()

    _FALLBACK_EVENT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,95}$")
    _FALLBACK_WORKER_ERROR = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
    _FALLBACK_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
    _FALLBACK_URL = re.compile(r"(?<![A-Za-z0-9+.-])(?:[A-Za-z][A-Za-z0-9+.-]*://|//)[^\s<>{}\"']+")
    _FALLBACK_OPAQUE_REF = re.compile(r"^[0-9a-f]{16}$")
    _FALLBACK_EVENT_FIELDS = (
        "request_id", "correlation_id", "route", "method", "status_class", "outcome", "reason",
        "job_ref", "worker_ref", "request_ref", "correlation_ref", "status", "stage", "error_code",
        "error", "workers", "recovered", "duration_ms", "progress", "attempt", "attempts", "count",
        "changed", "message",
    )

    def _fallback_safe_text(value: object, *, limit: int = 128) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = _FALLBACK_CONTROL.sub(" ", value).strip()
        if not cleaned:
            return None
        if "://" in cleaned or cleaned.startswith("//"):
            cleaned = _FALLBACK_URL.sub("[redacted-url]", cleaned)
        return cleaned[:limit]

    def safe_event(event: Mapping[str, object], *, event_name: str = "event") -> dict[str, object]:
        """Fallback redaction for a packaged image without the package wheel."""

        normalized_name = event_name if isinstance(event_name, str) else "event"
        if _FALLBACK_EVENT_NAME.fullmatch(normalized_name) is None:
            normalized_name = "event"
        worker_schema = globals().get("_WORKER_EVENT_SCHEMAS", {}).get(normalized_name)
        allowed_fields = worker_schema or _FALLBACK_EVENT_FIELDS
        worker_event = worker_schema is not None
        status_schema = globals().get("_WORKER_EVENT_STATUS", {}).get(normalized_name, frozenset())
        stage_schema = globals().get("_WORKER_EVENT_STAGE", {}).get(normalized_name, frozenset())
        fields: dict[str, object] = {}
        for key in allowed_fields:
            value = event.get(key)
            if value is not None:
                if key in {"job_ref", "worker_ref", "request_ref", "correlation_ref"}:
                    if isinstance(value, str) and _FALLBACK_OPAQUE_REF.fullmatch(value):
                        fields[key] = value
                    else:
                        fields[key] = opaque_ref(value)
                    continue
                if key in {"status", "stage"} and worker_event:
                    schema = status_schema if key == "status" else stage_schema
                    if isinstance(value, str) and value in schema:
                        fields[key] = value
                    continue
                if key == "error":
                    if isinstance(value, str) and _FALLBACK_WORKER_ERROR.fullmatch(value):
                        fields[key] = value
                    continue
                if key == "error_code":
                    if isinstance(value, str) and _FALLBACK_WORKER_ERROR.fullmatch(value):
                        fields[key] = value
                    continue
                if key in {"workers", "recovered"}:
                    try:
                        if isinstance(value, bool):
                            raise ValueError
                        fields[key] = max(0, min(int(value), 1_000))
                    except (TypeError, ValueError):
                        continue
                    continue
                if key in {"duration_ms", "progress"}:
                    try:
                        if isinstance(value, bool) or not math.isfinite(float(value)):
                            raise ValueError
                        upper = 86_400_000.0 if key == "duration_ms" else 1.0
                        fields[key] = round(max(0.0, min(float(value), upper)), 6)
                    except (TypeError, ValueError):
                        continue
                    continue
                if key in {"attempt", "attempts", "count"}:
                    try:
                        if isinstance(value, bool):
                            raise ValueError
                        fields[key] = max(0, min(int(value), 100_000))
                    except (TypeError, ValueError):
                        continue
                    continue
                if key == "changed":
                    if isinstance(value, bool):
                        fields[key] = value
                    continue
                text_value = _fallback_safe_text(value)
                if text_value is not None:
                    fields[key] = text_value
        return {"event": normalized_name, "fields": fields}

    def opaque_ref(value: object) -> str:
        candidate = _fallback_safe_text(value, limit=256) or "invalid"
        return hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:16]

    def emit_safely(
        sink: object | None,
        event_name: str,
        fields: Mapping[str, object],
        *,
        timeout: float | None = 0.25,
    ) -> bool:
        """Deliver a redacted event without allowing telemetry to affect state."""

        if sink is None:
            return True
        try:
            event = safe_event(fields, event_name=event_name)
            emitter = getattr(sink, "emit", None)
            if not callable(emitter) and not callable(sink):
                return False
            if timeout is None:
                if callable(emitter):
                    emitter(deepcopy(event))
                else:
                    sink(deepcopy(event))
                return True
            try:
                bounded_timeout = float(timeout)
            except (TypeError, ValueError):
                bounded_timeout = 0.0
            if not math.isfinite(bounded_timeout) or bounded_timeout < 0:
                bounded_timeout = 0.0
            completed = Event()

            def deliver() -> None:
                try:
                    if callable(emitter):
                        emitter(deepcopy(event))
                    else:
                        sink(deepcopy(event))
                except Exception:
                    return
                finally:
                    completed.set()

            Thread(target=deliver, name="rick-api-telemetry-sink", daemon=True).start()
            completed.wait(bounded_timeout)
            return completed.is_set()
        except Exception:
            return False


MAX_ROUTE_FAMILIES = 16
MAX_HISTOGRAM_SAMPLES = 10_000
MAX_TELEMETRY_EVENTS = 256
_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_WORKER_EVENT_FIELDS = frozenset({
    "job_ref", "worker_ref", "request_ref", "correlation_ref", "status", "stage",
    "progress", "attempt", "attempts", "error_code", "changed", "count", "error",
    "workers", "recovered", "reason",
})
_WORKER_REF_FIELDS = frozenset({"job_ref", "worker_ref", "request_ref", "correlation_ref"})
_WORKER_STATES = frozenset({
    "queued", "validating", "parsing", "chunking", "embedding", "indexing",
    "verifying", "published", "failed", "cancelled", "running", "completed",
    "leased", "acked", "dead",
})
_OPAQUE_REF = re.compile(r"^[0-9a-f]{16}$")
_SAFE_WORKER_ERROR = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_WORKER_EVENT_NAMES = frozenset({
    "worker.runner.started",
    "worker.job.enqueued",
    "worker.job.cancelled",
    "worker.job.cancel_requested",
    "worker.job.started",
    "worker.job.terminal",
    "worker.queue.recovered",
    "worker.queue.idempotent_replay",
    "worker.queue.enqueued",
    "worker.queue.claimed",
    "worker.queue.heartbeat",
    "worker.queue.failed",
    "worker.queue.acked",
    "worker.queue.dead",
    "worker.queue.cancelled",
    "worker.queue.cancel_ignored",
    "worker.ingestion.enqueued",
    "worker.ingestion.started",
    "worker.ingestion.published",
    "worker.ingestion.failed",
    "worker.ingestion.cancelled",
    "worker.ingestion.finished",
})

# Every accepted worker event has its own operational vocabulary. A global
# allowlist alone would let a valid event name carry semantically unrelated
# fields (for example ``workers`` on a queue acknowledgement).
_WORKER_EVENT_SCHEMAS: dict[str, tuple[str, ...]] = {
    "worker.runner.started": ("workers",),
    "worker.job.enqueued": ("job_ref", "status"),
    "worker.job.cancelled": ("job_ref", "status", "reason"),
    "worker.job.cancel_requested": ("job_ref", "status"),
    "worker.job.started": ("job_ref", "status"),
    "worker.job.terminal": ("job_ref", "status", "stage", "progress", "error_code"),
    "worker.queue.recovered": ("recovered",),
    "worker.queue.idempotent_replay": ("job_ref", "status", "attempts"),
    "worker.queue.enqueued": ("job_ref", "status", "attempts"),
    "worker.queue.claimed": ("job_ref", "status", "attempts", "worker_ref"),
    "worker.queue.heartbeat": ("job_ref", "status", "attempts"),
    "worker.queue.failed": ("job_ref", "status", "attempts", "error", "recovered"),
    "worker.queue.acked": ("job_ref", "status", "attempts"),
    "worker.queue.dead": ("job_ref", "status", "attempts"),
    "worker.queue.cancelled": ("job_ref", "status", "attempts", "changed"),
    "worker.queue.cancel_ignored": ("job_ref", "status", "attempts", "changed"),
    "worker.ingestion.enqueued": (
        "job_ref", "request_ref", "correlation_ref", "status", "stage", "progress", "attempt",
    ),
    "worker.ingestion.started": (
        "job_ref", "worker_ref", "request_ref", "correlation_ref", "status", "stage", "progress", "attempt",
    ),
    "worker.ingestion.published": (
        "job_ref", "worker_ref", "request_ref", "correlation_ref", "status", "stage", "progress", "attempt", "error_code",
    ),
    "worker.ingestion.failed": (
        "job_ref", "worker_ref", "request_ref", "correlation_ref", "status", "stage", "progress", "attempt", "error_code",
    ),
    "worker.ingestion.cancelled": (
        "job_ref", "worker_ref", "request_ref", "correlation_ref", "status", "stage", "progress", "attempt", "error_code",
    ),
    "worker.ingestion.finished": (
        "job_ref", "worker_ref", "request_ref", "correlation_ref", "status", "stage", "progress", "attempt", "error_code",
    ),
}

_WORKER_EVENT_STATUS: dict[str, frozenset[str]] = {
    "worker.runner.started": frozenset(),
    "worker.job.enqueued": frozenset({"queued"}),
    "worker.job.cancelled": frozenset({"cancelled"}),
    "worker.job.cancel_requested": frozenset({"queued", "running"}),
    "worker.job.started": frozenset({"running"}),
    "worker.job.terminal": frozenset({"completed", "published", "failed", "cancelled"}),
    "worker.queue.recovered": frozenset(),
    "worker.queue.idempotent_replay": frozenset({"queued", "leased", "acked", "dead", "cancelled"}),
    "worker.queue.enqueued": frozenset({"queued"}),
    "worker.queue.claimed": frozenset({"leased"}),
    "worker.queue.heartbeat": frozenset({"leased"}),
    "worker.queue.failed": frozenset({"queued", "dead"}),
    "worker.queue.acked": frozenset({"acked"}),
    "worker.queue.dead": frozenset({"dead"}),
    "worker.queue.cancelled": frozenset({"cancelled"}),
    "worker.queue.cancel_ignored": frozenset({"queued", "leased", "acked", "dead", "cancelled"}),
    "worker.ingestion.enqueued": frozenset({"queued"}),
    "worker.ingestion.started": frozenset({"validating", "parsing", "chunking", "embedding", "indexing", "verifying"}),
    "worker.ingestion.published": frozenset({"published"}),
    "worker.ingestion.failed": frozenset({"failed"}),
    "worker.ingestion.cancelled": frozenset({"cancelled"}),
    "worker.ingestion.finished": frozenset({"queued", "validating", "parsing", "chunking", "embedding", "indexing", "verifying", "published", "failed", "cancelled"}),
}

_WORKER_EVENT_STAGE: dict[str, frozenset[str]] = {
    **_WORKER_EVENT_STATUS,
    "worker.job.terminal": frozenset({"completed", "published", "failed", "cancelled", "running"}),
}


def route_family(path: str) -> str:
    """Map a request path into a finite, low-cardinality family."""

    if path == "/health/live":
        return "health.live"
    if path == "/health/ready":
        return "health.ready"
    if path == "/v1/models":
        return "compat.models"
    if path == "/v1/chat/completions":
        return "compat.chat"
    known = (
        ("/api/v1/auth/", "auth"),
        ("/api/v1/chat", "chat"),
        ("/api/v1/search", "search"),
        ("/api/v1/history", "history"),
        ("/api/v1/sources", "sources"),
        ("/api/v1/collections", "collections"),
        ("/api/v1/documents", "documents"),
        ("/api/v1/ingestion/", "ingestion"),
        ("/api/v1/admin/", "admin"),
        ("/api/v1/session", "session"),
    )
    for prefix, family in known:
        if path.startswith(prefix):
            return family
    return "other"


class ApiTelemetry:
    """Per-application bounded metrics and explicit SLO evaluation."""

    def __init__(self) -> None:
        self._counters = CounterRegistry(max_metrics=256)
        self._latency = Histogram("api.http.latency_ms", max_samples=MAX_HISTOGRAM_SAMPLES)
        self._recent_errors: deque[bool] = deque(maxlen=MAX_HISTOGRAM_SAMPLES)
        self._events: deque[dict[str, object]] = deque(maxlen=MAX_TELEMETRY_EVENTS)
        self._slo = AlertRule("api.http", max_error_rate=0.05, max_latency_p95=2_000.0)
        self._lock = RLock()

    @staticmethod
    def _method(method: str) -> str:
        return method if method in _HTTP_METHODS else "OTHER"

    @staticmethod
    def _worker_event_fields(event_name: str, raw_fields: Mapping[str, object]) -> dict[str, object]:
        fields: dict[str, object] = {}
        allowed_fields = _WORKER_EVENT_SCHEMAS.get(event_name, tuple(_WORKER_EVENT_FIELDS))
        allowed_status = _WORKER_EVENT_STATUS.get(event_name, _WORKER_STATES)
        allowed_stage = _WORKER_EVENT_STAGE.get(event_name, _WORKER_STATES)
        for key in allowed_fields:
            if key not in raw_fields:
                continue
            value = raw_fields[key]
            if key in _WORKER_REF_FIELDS:
                if isinstance(value, str) and _OPAQUE_REF.fullmatch(value):
                    fields[key] = value
                else:
                    # The sink is a second defensive boundary: a caller that
                    # accidentally supplies a raw identifier still cannot
                    # expose it through the admin snapshot.
                    fields[key] = opaque_ref(value)
            elif key in {"status", "stage"}:
                allowed = allowed_status if key == "status" else allowed_stage
                if isinstance(value, str) and value in allowed:
                    fields[key] = value
            elif key == "error_code":
                if isinstance(value, str) and re.fullmatch(r"[a-z0-9_.-]{1,64}", value):
                    fields[key] = value
            elif key == "progress":
                try:
                    observed = float(value)
                    if observed == observed and abs(observed) != float("inf"):
                        fields[key] = round(max(0.0, min(observed, 1.0)), 6)
                except (TypeError, ValueError):
                    continue
            elif key in {"attempt", "attempts", "count"}:
                try:
                    fields[key] = max(0, min(int(value), 100_000))
                except (TypeError, ValueError):
                    continue
            elif key in {"workers", "recovered"}:
                try:
                    fields[key] = max(0, min(int(value), 1_000))
                except (TypeError, ValueError):
                    continue
            elif key == "error":
                if isinstance(value, str) and _SAFE_WORKER_ERROR.fullmatch(value):
                    fields[key] = value
            elif key == "changed" and isinstance(value, bool):
                fields[key] = value
            elif key == "reason":
                if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_.:-]{0,63}", value):
                    fields[key] = value
        return fields

    def emit(self, event: Mapping[str, object]) -> None:
        """Accept only the bounded worker event contract from local services."""

        if not isinstance(event, Mapping):
            return
        event_name = event.get("event")
        raw_fields = event.get("fields")
        if (
            not isinstance(event_name, str)
            or event_name not in _WORKER_EVENT_NAMES
            or not isinstance(raw_fields, Mapping)
        ):
            return
        fields = self._worker_event_fields(event_name, raw_fields)
        normalized = safe_event(fields, event_name=event_name)
        with self._lock:
            self._events.append(deepcopy(normalized))

    def record_abandonment(self, *, path: str, reason: str,
                           request_id: str | None = None,
                           correlation_id: str | None = None) -> None:
        if reason not in {"disconnect", "cancellation"}:
            raise ValueError("unknown request abandonment reason")
        with self._lock:
            family = route_family(path)
            self._counters.increment(f"api.http.{reason}s", labels={"route": family})
            self._events.append(safe_event({
                "request_id": request_id,
                "correlation_id": correlation_id,
                "route": family,
                "outcome": "transport_abandoned",
                "reason": reason,
            }, event_name="api.http.abandonment"))

    def record_request(self, *, method: str, path: str, status: int, duration_ms: float,
                       failed: bool = False, request_id: str | None = None,
                       correlation_id: str | None = None) -> None:
        family = route_family(path)
        # Keep request/error counters keyed only by the finite route taxonomy;
        # response classes are tracked separately. This bounds the registry
        # even if a client sends many different HTTP methods.
        route_labels = {"route": family}
        status_labels = {"status": f"{status // 100}xx" if isinstance(status, int) else "unknown"}
        observed_duration = max(0.0, float(duration_ms))
        service_failed = failed or status >= 500
        with self._lock:
            self._counters.increment("api.http.requests", labels=route_labels)
            self._counters.increment("api.http.responses", labels=status_labels)
            if service_failed:
                self._counters.increment("api.http.errors", labels=route_labels)
            if status in (401, 403):
                self._counters.increment("api.http.auth_denied", labels=route_labels)
            self._latency.observe(observed_duration)
            self._recent_errors.append(service_failed)
            self._events.append(safe_event({
                "request_id": request_id,
                "correlation_id": correlation_id,
                "route": family,
                "method": self._method(method),
                "status_class": status_labels["status"],
                "outcome": "error" if service_failed else "response",
                "duration_ms": observed_duration,
            }, event_name="api.http.request"))

    @staticmethod
    def _total(snapshots: tuple[Any, ...], name: str) -> int:
        return int(sum(float(snapshot.total) for snapshot in snapshots if snapshot.name == name))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            snapshots = self._counters.snapshot()
            latency = self._latency.snapshot()
            total = len(self._recent_errors)
            errors = sum(self._recent_errors)
            events = tuple(deepcopy(event) for event in self._events)
        decision = self._slo.evaluate(
            total=total,
            errors=errors,
            latency_p95=latency.get("p95") if isinstance(latency, dict) else None,
        )
        return {
            "implementation": _IMPLEMENTATION,
            "export": {"status": "NOT_CONFIGURED", "destination": None},
            "slo": {
                "name": self._slo.name,
                "window": "last_requests",
                "window_capacity": MAX_HISTOGRAM_SAMPLES,
                "observations": total,
                "latency_scope": "response_headers",
                "status": decision.status,
                "reason": decision.reason,
                "error_rate": decision.error_rate,
                "latency_p95_ms": decision.latency_p95,
                "max_error_rate": self._slo.max_error_rate,
                "max_latency_p95_ms": self._slo.max_latency_p95,
            },
            "latency": latency,
            "counters": [snapshot.as_dict() for snapshot in snapshots],
            "events": list(events),
            "event_capacity": MAX_TELEMETRY_EVENTS,
        }
