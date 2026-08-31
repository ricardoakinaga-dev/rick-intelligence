"""
Tracing Service — OpenTelemetry-based distributed tracing with span hierarchy.

Provides:
- Span creation and management
- Trace propagation via ContextVars
- Parent-child span relationships
- Trace context for cross-module correlation

Requires: opentelemetry-api, opentelemetry-sdk (optional, graceful fallback)
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Optional
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4
from datetime import datetime, timezone

# ── Try importing OpenTelemetry (graceful fallback) ──────────────────────────

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.trace import Span, Status, StatusCode
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = None  # type: ignore


# ── Trace Context ─────────────────────────────────────────────────────────────

class SpanKind(Enum):
    """Kind of span - describes the nature of the operation."""
    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class SpanStatus(Enum):
    """Status of a span."""
    OK = "ok"
    ERROR = "error"
    UNSET = "unset"


# ── Span Data Structures ───────────────────────────────────────────────────────

@dataclass
class SpanData:
    """In-memory span representation for fallback mode."""
    name: str
    trace_id: str
    span_id: str
    parent_id: Optional[str] = None
    kind: SpanKind = SpanKind.INTERNAL
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    status: SpanStatus = SpanStatus.UNSET
    attributes: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    workspace_id: Optional[str] = None

    def set_attribute(self, key: str, value) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[dict] = None) -> None:
        self.events.append({"name": name, "attributes": attributes or {}})

    def set_status(self, status: SpanStatus, message: str = "") -> None:
        self.status = status

    def end(self) -> None:
        if self.end_time is None:
            self.end_time = time.time()

    @property
    def duration_ms(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000
        return None


# ── Trace Context Variables ────────────────────────────────────────────────────

_current_span: ContextVar[Optional[SpanData]] = ContextVar("current_span", default=None)
_span_stack: ContextVar[list[SpanData]] = ContextVar("span_stack", default=[])


# ── Tracer Implementation ─────────────────────────────────────────────────────

class SimpleTracer:
    """
    Simple in-memory tracer that provides OpenTelemetry-like interface.
    Used when OpenTelemetry SDK is not installed.

    Features:
    - Span creation with parent-child relationships
    - Trace context propagation via ContextVars
    - Configurable sampling
    - Span exporters (console, file)
    """

    def __init__(self, service_name: str = "rag-enterprise", sampling_rate: float = 1.0):
        self.service_name = service_name
        self.sampling_rate = sampling_rate
        self._spans: list[SpanData] = []
        self._trace_id_counter = 0

    def _generate_trace_id(self) -> str:
        """Generate a deterministic trace ID."""
        self._trace_id_counter += 1
        return f"{self._trace_id_counter:032x}"

    def _generate_span_id(self) -> str:
        """Generate a span ID."""
        return uuid4().hex[:16]

    def start_span(
        self,
        name: str,
        parent: Optional[SpanData] = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[dict] = None,
        workspace_id: Optional[str] = None,
    ) -> SpanData:
        """
        Start a new span, establishing parent-child relationship.

        Args:
            name: Name of the span (e.g., "search_hybrid", "query_rag")
            parent: Parent span (if any) for establishing hierarchy
            kind: Type of operation being traced
            attributes: Initial attributes to attach
            workspace_id: Workspace context for the span

        Returns:
            SpanData object representing the active span
        """
        # Get parent from context if not explicitly provided
        if parent is None:
            parent = _current_span.get()

        trace_id = parent.trace_id if parent else self._generate_trace_id()
        span_id = self._generate_span_id()
        parent_id = parent.span_id if parent else None

        span = SpanData(
            name=name,
            trace_id=trace_id,
            span_id=span_id,
            parent_id=parent_id,
            kind=kind,
            start_time=time.time(),
            attributes=attributes or {},
            workspace_id=workspace_id,
        )

        # Push to context
        _current_span.set(span)
        stack = list(_span_stack.get())
        stack.append(span)
        _span_stack.set(stack)
        self._spans.append(span)

        return span

    def end_span(self, span: SpanData, status: SpanStatus = SpanStatus.OK) -> None:
        """
        End a span and restore parent context.

        Args:
            span: The span to end
            status: Final status of the span
        """
        span.set_status(status)
        span.end()

        # Restore parent context
        stack = list(_span_stack.get())
        if stack and stack[-1] == span:
            stack.pop()
        _span_stack.set(stack)

        # Find and restore parent span
        if span.parent_id:
            for s in reversed(stack):
                if s.span_id == span.parent_id:
                    _current_span.set(s)
                    break
        else:
            _current_span.set(None)

    def get_current_span(self) -> Optional[SpanData]:
        """Get the currently active span."""
        return _current_span.get()

    def get_trace_id(self) -> str:
        """Get current trace ID or generate new one."""
        span = _current_span.get()
        if span:
            return span.trace_id
        return self._generate_trace_id()

    def get_all_spans(self) -> list[SpanData]:
        """Return all recorded spans (for debugging/export)."""
        return self._spans.copy()

    def clear(self) -> None:
        """Clear all recorded spans (for testing)."""
        self._spans.clear()
        _current_span.set(None)
        _span_stack.set([])

    def list_spans(
        self,
        *,
        limit: int = 50,
        workspace_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> list[SpanData]:
        """Return recent spans filtered by workspace or trace identifier."""
        items = list(self._spans)
        if workspace_id is not None:
            items = [span for span in items if span.workspace_id == workspace_id]
        if trace_id is not None:
            items = [span for span in items if span.trace_id == trace_id]
        items.sort(key=lambda span: span.end_time or span.start_time or 0.0, reverse=True)
        return items[:limit]


# ── Span Decorator ─────────────────────────────────────────────────────────────

def traced(
    span_name: Optional[str] = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Optional[dict] = None,
):
    """
    Decorator to automatically trace a function.

    Usage:
        @traced(span_name="search_hybrid", kind=SpanKind.INTERNAL)
        def search_hybrid(request):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            name = span_name or f"{func.__module__}.{func.__name__}"
            tracer = get_tracer()
            span = tracer.start_span(name, kind=kind, attributes=attributes)

            # Add function arguments as attributes (safely)
            safe_args = {f"arg_{i}": str(a)[:50] for i, a in enumerate(args[:3])}
            for k, v in list(kwargs.items())[:5]:
                safe_args[k] = str(v)[:50]
            for key, val in safe_args.items():
                span.set_attribute(key, val)

            try:
                result = func(*args, **kwargs)
                tracer.end_span(span, SpanStatus.OK)
                return result
            except Exception as e:
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(e)[:200])
                tracer.end_span(span, SpanStatus.ERROR)
                raise

        return wrapper
    return decorator


# ── Global Tracer Instance ─────────────────────────────────────────────────────

_tracer: Optional[SimpleTracer] = None


def get_tracer(service_name: str = "rag-enterprise") -> SimpleTracer:
    """
    Get the global tracer instance (singleton).

    If OpenTelemetry SDK is available, returns an OTel-based tracer.
    Otherwise, returns the SimpleTracer fallback.
    """
    global _tracer
    if _tracer is None:
        if OTEL_AVAILABLE:
            # Initialize OTel tracer
            provider = TracerProvider()
            processor = BatchSpanProcessor(ConsoleSpanExporter())
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            _tracer = trace.get_tracer(service_name)
        else:
            # Use simple in-memory tracer
            _tracer = SimpleTracer(service_name=service_name)
    return _tracer  # type: ignore


def init_tracing(service_name: str = "rag-enterprise", sampling_rate: float = 1.0) -> SimpleTracer:
    """
    Initialize the tracing system with the given service name.

    Call this once at application startup.
    """
    global _tracer
    _tracer = SimpleTracer(service_name=service_name, sampling_rate=sampling_rate)
    return _tracer


# ── Span Helpers ───────────────────────────────────────────────────────────────

def start_span(
    name: str,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Optional[dict] = None,
    workspace_id: Optional[str] = None,
) -> SpanData:
    """Start a new span using the global tracer."""
    return get_tracer().start_span(name, kind=kind, attributes=attributes, workspace_id=workspace_id)


def end_span(span: SpanData, status: SpanStatus = SpanStatus.OK) -> None:
    """End a span using the global tracer."""
    get_tracer().end_span(span, status)


def current_span() -> Optional[SpanData]:
    """Get the current active span."""
    return get_tracer().get_current_span()


def get_trace_id() -> str:
    """Get the current trace ID."""
    return get_tracer().get_trace_id()


def record_exception(span: SpanData, exception: Exception, attributes: Optional[dict] = None) -> None:
    """
    Record an exception in the given span.

    Args:
        span: The span to record the exception in
        exception: The exception that was raised
        attributes: Additional attributes to record
    """
    span.set_attribute("error", True)
    span.set_attribute("error.type", type(exception).__name__)
    span.set_attribute("error.message", str(exception)[:500])
    if attributes:
        for k, v in attributes.items():
            span.set_attribute(k, v)
    span.add_event("exception", {"type": type(exception).__name__, "message": str(exception)[:200]})


@contextmanager
def traced_span(
    name: str,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Optional[dict] = None,
    workspace_id: Optional[str] = None,
):
    """Context manager for tracing a logical operation."""
    span = start_span(name, kind=kind, attributes=attributes, workspace_id=workspace_id)
    try:
        yield span
    except Exception as exc:
        record_exception(span, exc)
        end_span(span, SpanStatus.ERROR)
        raise
    else:
        end_span(span, SpanStatus.OK)


def serialize_span(span: SpanData) -> dict:
    """Convert an in-memory span into a JSON-serializable payload."""
    started_at = (
        datetime.fromtimestamp(span.start_time, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if span.start_time
        else None
    )
    ended_at = (
        datetime.fromtimestamp(span.end_time, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if span.end_time
        else None
    )
    return {
        "name": span.name,
        "trace_id": span.trace_id,
        "span_id": span.span_id,
        "parent_id": span.parent_id,
        "kind": span.kind.value,
        "status": span.status.value,
        "workspace_id": span.workspace_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": round(span.duration_ms, 2) if span.duration_ms is not None else None,
        "attributes": span.attributes,
        "events": span.events,
    }


def list_recent_spans(
    *,
    limit: int = 50,
    workspace_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> list[dict]:
    """Return recent serialized spans from the global tracer."""
    tracer = get_tracer()
    if hasattr(tracer, "list_spans"):
        spans = tracer.list_spans(limit=limit, workspace_id=workspace_id, trace_id=trace_id)  # type: ignore[attr-defined]
    else:
        spans = []
    return [serialize_span(span) for span in spans]


# ── Exporters ─────────────────────────────────────────────────────────────────

class ConsoleSpanExporter:
    """Export spans to console (for debugging)."""

    def export(self, spans: list[SpanData]) -> None:
        for span in spans:
            duration = span.duration_ms
            status = span.status.value
            parent = span.parent_id or "none"
            print(
                f"[TRACE] {span.name} | "
                f"trace_id={span.trace_id[:16]}... | "
                f"span_id={span.span_id} | "
                f"parent={parent} | "
                f"duration={duration:.2f}ms | "
                f"status={status}"
            )
            if span.attributes:
                print(f"       attributes: {span.attributes}")
            if span.events:
                for event in span.events:
                    print(f"       event: {event}")


def export_spans_to_console() -> None:
    """Export all recorded spans to console."""
    exporter = ConsoleSpanExporter()
    exporter.export(get_tracer().get_all_spans())
