from __future__ import annotations

import json
import threading
import time

import pytest

from rick_observability import (
    AlertRule,
    BoundedEventBuffer,
    CorrelationContext,
    CounterRegistry,
    Histogram,
    emit_safely,
    evaluate_slo,
    opaque_ref,
    safe_event,
    should_sample,
)
from rick_observability.redaction import MAX_EVENT_BYTES, MAX_EVENT_NODES, redact


def _walk_nodes(value):
    yield value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_nodes(key)
            yield from _walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_nodes(child)


def test_event_buffer_is_bounded_redacted_and_snapshot_immutable() -> None:
    buffer = BoundedEventBuffer(max_events=2)
    first = {"safe": {"value": "one"}, "token": "private"}
    buffer.emit(first, event_name="worker.lifecycle")
    first["safe"]["value"] = "mutated"
    buffer.emit({"safe": {"value": "two"}}, event_name="worker.lifecycle")
    buffer.emit({"safe": {"value": "three"}}, event_name="worker.lifecycle")

    retained = buffer.snapshot()
    assert buffer.capacity == 2
    assert buffer.size == 2
    assert [item["fields"]["safe"]["value"] for item in retained] == ["two", "three"]
    assert "private" not in repr(retained)
    retained[0]["fields"]["safe"]["value"] = "outside-mutation"
    assert buffer.snapshot()[0]["fields"]["safe"]["value"] == "two"


def test_emit_safely_redacts_before_callback_and_ignores_sink_failures() -> None:
    received: list[dict[str, object]] = []
    emit_safely(received.append, "worker.lifecycle", {"secret": "hidden", "state": "queued"})
    assert received[0]["event"] == "worker.lifecycle"
    assert received[0]["fields"]["secret"] == "[redacted]"
    assert received[0]["fields"]["state"] == "queued"

    class BrokenSink:
        def emit(self, _event: object) -> None:
            raise RuntimeError("sink failure")

    emit_safely(BrokenSink(), "worker.lifecycle", {"state": "queued"})
    assert len(received) == 1
    assert opaque_ref("job-1") != "job-1"


def test_emit_safely_does_not_wait_forever_for_a_blocked_sink() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingSink:
        def emit(self, _event: object) -> None:
            entered.set()
            release.wait(2)

    began = time.monotonic()
    delivered = emit_safely(BlockingSink(), "worker.lifecycle", {"state": "queued"}, timeout=0.03)
    elapsed = time.monotonic() - began
    assert delivered is False
    assert entered.wait(1)
    assert elapsed < 0.5
    release.set()


def test_redaction_removes_sensitive_fields_and_url_queries() -> None:
    event = safe_event({
        "authorization": "Bearer secret-token",
        "prompt": "private clinical text",
        "url": "https://user:password@example.test/path?token=secret",
        "request_id": "req-1",
    }, event_name="chat.request")
    serialized = repr(event)
    assert "secret-token" not in serialized
    assert "private clinical text" not in serialized
    assert "password" not in serialized
    assert "?token" not in serialized
    assert event["fields"]["request_id"] == "req-1"


def test_event_names_are_bounded_and_cannot_carry_query_credentials() -> None:
    event = safe_event({}, event_name="worker?token=secret")
    assert event["event"] == "event"
    assert "secret" not in repr(event)


def test_redaction_has_a_global_node_and_byte_budget() -> None:
    payload = {
        "items": ({"value": "x" * 1000} for _ in range(100_000)),
        "secret": "must-not-appear",
    }

    redacted = redact(payload)
    encoded = json.dumps(redacted, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    assert len(encoded) <= MAX_EVENT_BYTES
    assert "must-not-appear" not in encoded.decode("utf-8")
    assert sum(1 for _ in _walk_nodes(redacted)) <= MAX_EVENT_NODES


def test_safe_event_budget_counts_json_escaping_and_numeric_scalars() -> None:
    event = safe_event({
        "quoted": '"' * 4_000,
        "large_int": 2**53 - 1,
        "large_float": 1.0e308,
    }, event_name="worker.queue.failed")
    encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    assert len(encoded) <= MAX_EVENT_BYTES
    assert sum(1 for _ in _walk_nodes(event)) <= MAX_EVENT_NODES
    assert event["event"] == "worker.queue.failed"


def test_redaction_removes_credentials_and_queries_from_non_http_urls() -> None:
    event = safe_event({
        "url": "redis://user:password@vector.example:6379/0?token=secret#fragment",
    })
    assert event["fields"]["url"] == "redis://vector.example:6379/0"
    assert "user" not in repr(event)
    assert "password" not in repr(event)
    assert "secret" not in repr(event)
    assert "fragment" not in repr(event)

    relative = safe_event({"url": "//user:password@vector.example/path?token=secret#fragment"})
    assert relative["fields"]["url"] == "//vector.example/path"

    embedded = safe_event({
        "message": "prefix https://user:password@vector.example/path?token=secret#fragment suffix",
    })
    assert embedded["fields"]["message"] == "prefix https://vector.example/path suffix"
    assert "password" not in repr(embedded)
    assert "secret" not in repr(embedded)


def test_metrics_are_bounded_and_deterministic() -> None:
    histogram = Histogram("api.latency", max_samples=2)
    histogram.observe(10)
    histogram.observe(20)
    histogram.observe(30)
    assert histogram.snapshot()["count"] == 2
    assert histogram.snapshot()["p95"] == 30.0

    registry = CounterRegistry(max_metrics=1)
    assert registry.increment("api.requests", labels={"route": "chat"}) == 1.0
    with pytest.raises(ValueError):
        registry.increment("api.errors")


def test_sampling_correlation_and_slo_states() -> None:
    assert should_sample("trace-1", 0) is False
    assert should_sample("trace-1", 1) is True
    assert should_sample("trace-1", 0.5) == should_sample("trace-1", 0.5)
    assert CorrelationContext("req-1", "corr-1").as_dict()["request_id"] == "req-1"
    assert evaluate_slo(total=0, errors=0, latency_p95=None, max_error_rate=.01).status == "no_data"
    assert evaluate_slo(total=100, errors=3, latency_p95=20, max_error_rate=.01).status == "breach"
    assert AlertRule("chat", .05, 500).evaluate(total=100, errors=1, latency_p95=100).status == "healthy"
