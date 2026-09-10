"""Safe, dependency-light observability primitives."""

from rick_observability.metrics import CounterRegistry, Histogram, MetricSnapshot
from rick_observability.redaction import redact, safe_event, safe_text
from rick_observability.slo import AlertRule, SloDecision, evaluate_slo
from rick_observability.tracing import CorrelationContext, inject_w3c_trace_headers, should_sample
from rick_observability.events import BoundedEventBuffer, emit_safely, opaque_ref

__all__ = [
    "AlertRule", "BoundedEventBuffer", "CorrelationContext", "CounterRegistry",
    "Histogram", "MetricSnapshot", "SloDecision", "emit_safely", "evaluate_slo",
    "inject_w3c_trace_headers", "opaque_ref", "redact", "safe_event", "safe_text", "should_sample",
]
