"""The standalone API telemetry fallback must preserve bounded sink delivery."""

import builtins
import importlib.util
from pathlib import Path
import threading
import time


def _load_fallback(monkeypatch):
    original_import = builtins.__import__

    def without_observability_package(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "rick_observability":
            raise ImportError("forced fallback test")
        return original_import(name, globals, locals, fromlist, level)

    module_path = Path(__file__).resolve().parents[1] / "src/core/telemetry.py"
    module_name = f"api_telemetry_fallback_test_{id(monkeypatch)}"
    specification = importlib.util.spec_from_file_location(module_name, module_path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", without_observability_package)
        specification.loader.exec_module(module)
    assert module._IMPLEMENTATION == "api_fallback"
    return module


def test_fallback_timeout_none_does_not_call_sink_on_the_caller_thread(monkeypatch):
    telemetry = _load_fallback(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    result = []

    def blocked_sink(_event):
        entered.set()
        release.wait(2)

    def call_from_operational_thread():
        result.append(telemetry.emit_safely(blocked_sink, "sink.test", {}, timeout=None))
        finished.set()

    caller = threading.Thread(target=call_from_operational_thread)
    try:
        caller.start()
        assert entered.wait(1)
        assert finished.wait(0.75), "fallback blocked the telemetry caller on a sink"
        assert result == [False]
    finally:
        release.set()
        caller.join(1)
        telemetry.shutdown_sink_delivery(timeout=1)


def test_fallback_sink_exception_is_not_reported_as_delivery_success(monkeypatch):
    telemetry = _load_fallback(monkeypatch)

    def broken_sink(_event):
        raise RuntimeError("collector unavailable")

    try:
        assert telemetry.emit_safely(broken_sink, "sink.test", {}, timeout=1) is False
        snapshot = telemetry.sink_delivery_snapshot()
        counters = {item["name"]: item["total"] for item in snapshot["counters"]}
        assert counters["sink.delivery.failed"] == 1
        assert counters["sink.delivery.emitted"] == 0
    finally:
        telemetry.shutdown_sink_delivery(timeout=1)


def test_fallback_sink_attribute_lookup_is_inside_the_bounded_lane(monkeypatch):
    telemetry = _load_fallback(monkeypatch)
    lookup_started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    result = []
    received = []

    class BlockingEmitterLookup:
        @property
        def emit(self):
            lookup_started.set()
            release.wait(2)
            return received.append

    def call_from_operational_thread():
        result.append(telemetry.emit_safely(BlockingEmitterLookup(), "sink.test", {}, timeout=0.05))
        finished.set()

    caller = threading.Thread(target=call_from_operational_thread)
    try:
        began = time.monotonic()
        caller.start()
        assert lookup_started.wait(1)
        assert finished.wait(0.75), "fallback resolved an arbitrary sink descriptor on its caller"
        assert time.monotonic() - began < 0.75
        assert result == [False]
    finally:
        release.set()
        caller.join(1)
        assert telemetry.shutdown_sink_delivery(timeout=1)
    assert received[0]["event"] == "sink.test"


def test_fallback_overload_is_bounded_and_visible_in_api_metrics(monkeypatch):
    telemetry = _load_fallback(monkeypatch)
    delivery = telemetry._FallbackSinkDelivery(workers=1, capacity=2)
    monkeypatch.setattr(telemetry, "_fallback_delivery", delivery)
    entered = threading.Event()
    release = threading.Event()

    def blocked_sink(_event):
        entered.set()
        release.wait(2)

    try:
        assert not telemetry.emit_safely(blocked_sink, "sink.test", {}, timeout=0)
        assert entered.wait(1)
        for index in range(2):
            assert not telemetry.emit_safely(lambda _event: None, "sink.test", {"index": index}, timeout=0)
        for index in range(20):
            assert not telemetry.emit_safely(lambda _event: None, "sink.test", {"index": index}, timeout=0)

        snapshot = telemetry.sink_delivery_snapshot()
        assert (snapshot["workers"], snapshot["capacity"], snapshot["queued"], snapshot["active"]) == (1, 2, 2, 1)
        counters = {item["name"]: item["total"] for item in snapshot["counters"]}
        assert counters["sink.delivery.dropped"] == 20

        api_snapshot = telemetry.ApiTelemetry().snapshot()
        assert api_snapshot["sink_delivery"] == snapshot
        assert 'rick_api_telemetry_sink_delivery_total{outcome="dropped"} 20' in telemetry.ApiTelemetry().prometheus_text()

        began = time.monotonic()
        assert not delivery.shutdown(timeout=0.02)
        assert time.monotonic() - began < 0.5
        closed = telemetry.ApiTelemetry().snapshot()["sink_delivery"]
        assert closed["closed"] is True
        assert next(item["total"] for item in closed["counters"] if item["name"] == "sink.delivery.dropped") == 22
    finally:
        release.set()
        assert delivery.shutdown(timeout=1)
