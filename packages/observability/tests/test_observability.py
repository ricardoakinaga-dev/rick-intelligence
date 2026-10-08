from __future__ import annotations

import json
from types import ModuleType, SimpleNamespace
import sys
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
    inject_w3c_trace_headers,
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

    assert not emit_safely(BrokenSink(), "worker.lifecycle", {"state": "queued"})
    assert len(received) == 1
    assert opaque_ref("job-1") != "job-1"


def test_sink_emit_descriptor_lookup_runs_inside_the_bounded_lane(monkeypatch) -> None:
    import rick_observability.events as events

    delivery = events._SinkDelivery(workers=1, capacity=2)
    monkeypatch.setattr(events, "_delivery", delivery)
    lookup_started = threading.Event()
    release = threading.Event()
    received = []

    class BlockingEmitterLookup:
        @property
        def emit(self):
            lookup_started.set()
            release.wait(2)
            return received.append

    try:
        began = time.monotonic()
        assert not emit_safely(BlockingEmitterLookup(), "sink.test", {}, timeout=0.03)
        assert lookup_started.wait(1)
        assert time.monotonic() - began < 0.5
    finally:
        release.set()
        assert events.shutdown_sink_delivery(timeout=1)
    assert received[0]["event"] == "sink.test"


def test_sink_snapshot_does_not_start_workers_for_an_unused_lane(monkeypatch) -> None:
    import rick_observability.events as events

    monkeypatch.setattr(events, "_delivery", None)
    snapshot = events.sink_delivery_snapshot()
    assert snapshot["workers"] == 0
    assert snapshot["queued"] == snapshot["active"] == 0
    assert events._delivery is None


def test_unused_sink_shutdown_does_not_allocate_workers(monkeypatch) -> None:
    from rick_observability import events

    monkeypatch.setattr(events, "_delivery", None)
    assert events.shutdown_sink_delivery(timeout=1)
    assert events.sink_delivery_snapshot()["workers"] == 0
    assert events._delivery is None


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


def test_sink_delivery_sustained_overload_has_fixed_workers_and_bounded_shutdown(monkeypatch) -> None:
    import rick_observability.events as events

    delivery = events._SinkDelivery(workers=2, capacity=8)
    monkeypatch.setattr(events, "_delivery", delivery)
    entered = threading.Barrier(3)
    release = threading.Event()
    received = []

    def sink(event):
        entered.wait(timeout=2)
        release.wait(5)
        received.append(event)

    try:
        assert not emit_safely(sink, "sink.test", {}, timeout=0)
        assert not emit_safely(sink, "sink.test", {}, timeout=0)
        entered.wait(timeout=2)
        workers = tuple(delivery._threads)
        for index in range(1000):
            assert not emit_safely(sink, "sink.test", {"index": index}, timeout=0)
        snapshot = events.sink_delivery_snapshot()
        assert snapshot["queued"] == 8
        assert snapshot["active"] == snapshot["workers"] == 2
        assert tuple(delivery._threads) == workers
        counters = {metric["name"]: metric["total"] for metric in snapshot["counters"]}
        assert counters["sink.delivery.dropped"] == 992
        assert counters["sink.delivery.timeout"] == 10
        began = time.monotonic()
        assert not events.shutdown_sink_delivery(timeout=0.02)
        assert time.monotonic() - began < 0.5
        assert events.sink_delivery_snapshot()["queued"] == 0
        assert not emit_safely(sink, "sink.test", {}, timeout=0)
        counters = {metric["name"]: metric["total"] for metric in events.sink_delivery_snapshot()["counters"]}
        assert counters["sink.delivery.dropped"] == 1001
        assert counters["sink.delivery.shutdown_timeout"] == 1
    finally:
        release.set()
        assert delivery.shutdown(timeout=1)
    assert len(received) == 2


def test_sink_shutdown_flushes_and_preserves_emit_observation(monkeypatch) -> None:
    import rick_observability.events as events

    delivery = events._SinkDelivery(workers=1, capacity=4)
    monkeypatch.setattr(events, "_delivery", delivery)
    received = []
    try:
        assert emit_safely(received.append, "sink.test", {"token": "secret"})
        assert received[0]["fields"]["token"] == "[redacted]"
        assert not emit_safely(lambda event: (_ for _ in ()).throw(ValueError()), "sink.test", {})
        for index in range(3):
            emit_safely(received.append, "sink.test", {"index": index}, timeout=0)
        assert events.shutdown_sink_delivery(timeout=1)
        assert len(received) == 4
        assert not any(thread.is_alive() for thread in delivery._threads)
        counters = {metric["name"]: metric["total"] for metric in events.sink_delivery_snapshot()["counters"]}
        assert counters["sink.delivery.failed"] == 1
        assert not emit_safely(received.append, "sink.test", {}, timeout=None)
        assert emit_safely(None, "sink.test", {})
        assert not emit_safely(object(), "sink.test", {})
    finally:
        delivery.shutdown(timeout=1)


def test_none_timeout_is_still_bounded_for_a_blocked_sink(monkeypatch) -> None:
    import rick_observability.events as events

    delivery = events._SinkDelivery(workers=1, capacity=2)
    monkeypatch.setattr(events, "_delivery", delivery)
    entered = threading.Event()
    release = threading.Event()

    def sink(_event):
        entered.set()
        release.wait(2)

    try:
        began = time.monotonic()
        assert not emit_safely(sink, "sink.test", {}, timeout=None)
        elapsed = time.monotonic() - began
        assert entered.wait(1)
        assert elapsed < 1.0
        counters = {metric["name"]: metric["total"] for metric in events.sink_delivery_snapshot()["counters"]}
        assert counters["sink.delivery.timeout"] == 1
    finally:
        release.set()
        assert delivery.shutdown(timeout=1)


def test_shutdown_discards_queue_and_wakes_waiting_emitters(monkeypatch) -> None:
    import rick_observability.events as events

    delivery = events._SinkDelivery(workers=1, capacity=1)
    monkeypatch.setattr(events, "_delivery", delivery)
    entered = threading.Event()
    release = threading.Event()
    observed = []

    def sink(event):
        entered.set()
        release.wait(5)

    waiter = threading.Thread(target=lambda: observed.append(
        emit_safely(lambda event: pytest.fail("discarded event delivered"), "sink.test", {}, timeout=5)))
    try:
        emit_safely(sink, "sink.test", {}, timeout=0)
        assert entered.wait(1)
        waiter.start()
        deadline = time.monotonic() + 1
        while delivery.snapshot()["queued"] != 1 and time.monotonic() < deadline:
            time.sleep(0.001)
        assert delivery.snapshot()["queued"] == 1
        assert not delivery.shutdown(timeout=0)
        waiter.join(0.5)
        assert not waiter.is_alive()
        assert observed == [False]
    finally:
        release.set()
        waiter.join(1)
        delivery.shutdown(timeout=1)


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

    escaped = safe_event({
        "message": r"prefix https:\/\/user:password@vector.example\/path?token=secret suffix",
    })
    assert escaped["fields"]["message"] == "prefix https://vector.example/path suffix"
    assert "password" not in repr(escaped)
    assert "secret" not in repr(escaped)

    inline = safe_event({
        "message": "password=super-secret token=abc123 Authorization: Bearer bearer-secret",
    })
    assert "super-secret" not in repr(inline)
    assert "abc123" not in repr(inline)
    assert "bearer-secret" not in repr(inline)

    nested_text = safe_event({
        "message": r'nested {"api_key":"json-secret", "password":"json-password"}',
    })
    assert "json-secret" not in repr(nested_text)
    assert "json-password" not in repr(nested_text)


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


def test_w3c_injection_is_bounded_and_drops_baggage(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sdk = ModuleType("opentelemetry")

    def inject(carrier: dict[str, str]) -> None:
        carrier.update({
            "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
            "tracestate": "vendor=value",
            "baggage": "password=secret",
        })

    fake_sdk.propagate = SimpleNamespace(inject=inject)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_sdk)

    projected = inject_w3c_trace_headers({"X-Correlation-ID": "corr-1"})

    assert projected == {
        "X-Correlation-ID": "corr-1",
        "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
        "tracestate": "vendor=value",
    }
    assert "baggage" not in projected
    assert "secret" not in repr(projected)
