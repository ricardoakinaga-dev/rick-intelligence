from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest

from core.otel import _HTTPSpanMiddleware, attach_trace_context, install_otel, record_safe_exception, stage_span


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, asyncio.CancelledError, KeyboardInterrupt])
@pytest.mark.parametrize("detach_fails", [False, True])
def test_trace_context_preserves_original_body_error(monkeypatch, error_type, detach_fails):
    import core.otel as otel
    from opentelemetry import context

    calls = []
    monkeypatch.setattr(otel, "extract_trace_context", lambda _value: "parent")
    monkeypatch.setattr(context, "attach", lambda parent: calls.append(("attach", parent)) or "token")
    def detach(token):
        calls.append(("detach", token))
        if detach_fails:
            raise RuntimeError("SDK cleanup failed")
    monkeypatch.setattr(context, "detach", detach)
    original = error_type("business failure")
    with pytest.raises(error_type) as captured:
        with attach_trace_context({"traceparent": "synthetic"}):
            raise original
    assert captured.value is original
    assert calls == [("attach", "parent"), ("detach", "token")]


def test_trace_context_attach_failure_yields_exactly_once_and_preserves_body(monkeypatch):
    import core.otel as otel
    from opentelemetry import context

    monkeypatch.setattr(otel, "extract_trace_context", lambda _value: "parent")
    def fail(_parent):
        raise RuntimeError("attach failed")
    monkeypatch.setattr(context, "attach", fail)
    entered = []
    with attach_trace_context({"traceparent": "synthetic"}):
        entered.append(True)
    assert entered == [True]
    error = ValueError("body")
    with pytest.raises(ValueError) as captured:
        with attach_trace_context({"traceparent": "synthetic"}):
            raise error
    assert captured.value is error


def test_trace_context_detach_failure_cannot_change_success(monkeypatch):
    import core.otel as otel
    from opentelemetry import context

    monkeypatch.setattr(otel, "extract_trace_context", lambda _value: "parent")
    monkeypatch.setattr(context, "attach", lambda _parent: "token")
    def fail(_token):
        raise RuntimeError("detach failed")
    monkeypatch.setattr(context, "detach", fail)
    entered = []
    with attach_trace_context({"traceparent": "synthetic"}):
        entered.append(True)
    assert entered == [True]


def test_trace_context_missing_parent_preserves_success_and_body_error(monkeypatch):
    import core.otel as otel
    monkeypatch.setattr(otel, "extract_trace_context", lambda _value: None)
    with attach_trace_context(None):
        pass
    error = ValueError("body")
    with pytest.raises(ValueError) as captured:
        with attach_trace_context(None):
            raise error
    assert captured.value is error


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


@pytest.mark.parametrize("use_http", [False, True])
def test_optional_exporter_port_uses_protocol_specific_constructor(monkeypatch, use_http):
    from types import SimpleNamespace
    import core.otel as otel

    observed = []
    exporter = object()

    def factory(**kwargs):
        observed.append(kwargs)
        return exporter

    def load(name):
        expected_protocol = "http" if use_http else "grpc"
        assert name == f"opentelemetry.exporter.otlp.proto.{expected_protocol}.trace_exporter"
        return SimpleNamespace(OTLPSpanExporter=factory)

    monkeypatch.setattr(otel, "import_module", load)
    assert otel._otlp_exporter(endpoint="http://collector.invalid:4318", use_http=use_http) is exporter
    expected = {"endpoint": "http://collector.invalid:4318"}
    if not use_http:
        expected["insecure"] = True
    assert observed == [expected]


@pytest.mark.parametrize("use_http", [False, True])
def test_missing_optional_exporter_does_not_claim_configuration(monkeypatch, use_http):
    import core.otel as otel

    def unavailable(_name):
        raise ModuleNotFoundError("synthetic missing optional exporter")

    monkeypatch.setattr(otel, "import_module", unavailable)
    with pytest.raises(ModuleNotFoundError):
        otel._otlp_exporter(endpoint="http://collector.invalid:4318", use_http=use_http)
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp_proto_http" if use_http else "otlp_proto_grpc")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid:4318")
    runtime = otel.configure_process_otel(service_name="synthetic")
    assert runtime.status == "NOT_CONFIGURED"
    assert runtime.destination == "http://collector.invalid:4318"
    assert runtime.provider is None
    assert runtime.tracer is None
