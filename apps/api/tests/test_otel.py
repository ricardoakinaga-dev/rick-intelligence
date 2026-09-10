from __future__ import annotations

import asyncio
from contextlib import contextmanager

from core.otel import _HTTPSpanMiddleware, install_otel, record_safe_exception, stage_span


class _Telemetry:
    def __init__(self) -> None:
        self.value = None

    def set_export(self, **value):
        self.value = value


def test_otel_is_explicitly_no_data_when_exporter_is_disabled(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    telemetry = _Telemetry()

    runtime = install_otel(object(), telemetry)

    assert runtime.status == "NOT_CONFIGURED"
    assert runtime.destination is None
    assert telemetry.value == {"status": "NOT_CONFIGURED", "destination": None}


def test_otel_does_not_claim_delivery_when_sdk_is_unavailable(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    telemetry = _Telemetry()

    runtime = install_otel(object(), telemetry)

    assert runtime.status == "NOT_CONFIGURED"
    assert runtime.destination == "http://collector:4317"
    assert telemetry.value["status"] == "NOT_CONFIGURED"


class _Span:
    def __init__(self) -> None:
        self.attributes = {}

    def set_attribute(self, name, value):
        self.attributes[name] = value

    def record_exception(self, _error):
        return None


class _Tracer:
    def __init__(self) -> None:
        self.context = None
        self.span = _Span()
        self.kwargs = {}

    @contextmanager
    def start_as_current_span(self, _name, **kwargs):
        self.context = kwargs.get("context")
        self.kwargs = kwargs
        yield self.span


def test_http_middleware_extracts_bounded_w3c_context_and_ignores_other_headers():
    observed = {}

    async def app(scope, _receive, send):
        await send({"type": "http.response.start", "status": 204})

    def extract(carrier):
        observed.update(carrier)
        return "parent-context"

    tracer = _Tracer()
    middleware = _HTTPSpanMiddleware(app, tracer=tracer, extract_context=extract)
    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "GET",
                "headers": [
                    (b"traceparent", b"00-" + b"a" * 32 + b"-" + b"b" * 16 + b"-01"),
                    (b"authorization", b"secret-must-not-enter-carrier"),
                    (b"tracestate", b"vendor=value"),
                    (b"baggage", b"password=secret"),
                ],
            },
            None,
            lambda _message: asyncio.sleep(0),
        )
    )
    assert observed == {
        "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
        "tracestate": "vendor=value",
    }
    assert tracer.context == "parent-context"


def test_stage_span_disables_automatic_exception_payloads_and_keeps_only_safe_identity(monkeypatch):
    import core.otel as otel

    tracer = _Tracer()
    monkeypatch.setattr(otel, "_PROCESS_TRACER", tracer)
    error = RuntimeError("password=super-secret")
    with stage_span("provider.request", attributes={"provider.operation": "chat"}) as span:
        record_safe_exception(span, error)

    assert tracer.kwargs["record_exception"] is False
    assert tracer.kwargs["set_status_on_exception"] is False
    assert tracer.span.attributes == {
        "provider.operation": "chat",
        "error.type": "RuntimeError",
    }
    assert "super-secret" not in str(tracer.span.attributes)
