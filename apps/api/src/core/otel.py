"""Optional OpenTelemetry runtime for the canonical API boundary.

The API remains importable in the hermetic test environment when the SDK is
not installed.  A production-shaped image installs the pinned SDK/exporter;
when OTEL is enabled, this module creates one process-owned tracer provider,
exports bounded HTTP spans over OTLP, and closes the exporter with the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import os
import re
from typing import Any, Iterator, Mapping


_SAFE_SPAN_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$")
_SAFE_ATTRIBUTE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_MAX_PROPAGATION_VALUE = 4096

# The API and Worker each have one process-owned tracer.  Keeping the tracer
# here gives downstream service seams a dependency-light span port while the
# exporter remains optional in hermetic tests.
_PROCESS_TRACER: object | None = None
_PROCESS_PROVIDER: object | None = None


@dataclass(slots=True)
class OpenTelemetryRuntime:
    status: str
    destination: str | None
    provider: object | None = None
    tracer: object | None = None

    def close(self) -> None:
        global _PROCESS_TRACER, _PROCESS_PROVIDER
        shutdown = getattr(self.provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
        if self.provider is _PROCESS_PROVIDER:
            _PROCESS_TRACER = None
            _PROCESS_PROVIDER = None


def _safe_span_name(value: object) -> str:
    candidate = str(value).strip()[:128]
    return candidate if _SAFE_SPAN_NAME.fullmatch(candidate) else "rick.runtime"


def _safe_error_type(error: object) -> str:
    name = type(error).__name__
    return name if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", name) else "error"


def _safe_error_code(error: object) -> str | None:
    code = getattr(error, "code", None)
    if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_.:-]{0,63}", code):
        return code
    return None


def _bounded_carrier(value: Mapping[str, object] | None) -> dict[str, str]:
    """Keep propagation limited to W3C trace identity headers.

    Baggage is deliberately excluded: arbitrary baggage can contain tenant
    metadata or credentials and is not required to preserve the trace graph.
    The worker queue may persist this carrier, so the same bound applies at
    every process boundary.
    """

    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for name in ("traceparent", "tracestate"):
        raw = value.get(name)
        if isinstance(raw, str) and raw and len(raw) <= _MAX_PROPAGATION_VALUE:
            result[name] = raw
    return result


def current_trace_context() -> dict[str, str]:
    """Inject the current W3C context into a bounded, JSON-safe carrier."""

    try:
        from opentelemetry import propagate

        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        return _bounded_carrier(carrier)
    except Exception:
        return {}


def extract_trace_context(value: Mapping[str, object] | None) -> object | None:
    """Extract only the bounded W3C carrier received from another process."""

    carrier = _bounded_carrier(value)
    if not carrier:
        return None
    try:
        from opentelemetry import propagate

        return propagate.extract(carrier)
    except Exception:
        return None


@contextmanager
def attach_trace_context(value: Mapping[str, object] | None) -> Iterator[None]:
    """Attach a persisted W3C context for the duration of one worker call."""

    parent = extract_trace_context(value)
    if parent is None:
        yield
        return
    try:
        from opentelemetry import context as otel_context

        token = otel_context.attach(parent)
        try:
            yield
        finally:
            otel_context.detach(token)
    except Exception:
        # A malformed/unsupported carrier must not stop durable work. The
        # worker still emits a local root span when tracing is configured.
        yield


@contextmanager
def stage_span(
    name: str,
    *,
    parent_context: object | None = None,
    attributes: Mapping[str, object] | None = None,
) -> Iterator[object | None]:
    """Emit one bounded stage span without making tracing a hard dependency."""

    tracer = _PROCESS_TRACER
    if tracer is None:
        yield None
        return
    kwargs: dict[str, object] = {
        # Exceptions are recorded explicitly below with type/code only. The
        # SDK default would serialize exception messages and stack traces.
        "record_exception": False,
        "set_status_on_exception": False,
    }
    if parent_context is not None:
        kwargs["context"] = parent_context
    try:
        span_manager = tracer.start_as_current_span(_safe_span_name(name), **kwargs)
        span = span_manager.__enter__()
    except Exception:
        # Instrumentation must never change application behavior. A broken
        # exporter or test tracer simply disables this one span boundary.
        yield None
        return
    try:
        if isinstance(attributes, Mapping):
            for key, value in attributes.items():
                if not isinstance(key, str) or _SAFE_ATTRIBUTE.fullmatch(key) is None:
                    continue
                if isinstance(value, (str, bool, int, float)) and not isinstance(value, bytes):
                    try:
                        span.set_attribute(key, value)
                    except Exception:
                        continue
        yield span
    except BaseException as error:
        try:
            span_manager.__exit__(type(error), error, error.__traceback__)
        except Exception:
            pass
        raise
    else:
        try:
            span_manager.__exit__(None, None, None)
        except Exception:
            pass


def record_safe_exception(span: object | None, error: object) -> None:
    """Attach only non-sensitive exception identity to an active span."""

    if span is None:
        return
    try:
        span.set_attribute("error.type", _safe_error_type(error))
        code = _safe_error_code(error)
        if code is not None:
            span.set_attribute("error.code", code)
    except Exception:
        return


class _HTTPSpanMiddleware:
    """Small ASGI middleware that emits one bounded span per HTTP request."""

    def __init__(self, app: object, *, tracer: object, extract_context: object | None = None) -> None:
        self.app = app
        self.tracer = tracer
        self.extract_context = extract_context

    @staticmethod
    def _carrier(scope: dict[str, Any]) -> dict[str, str]:
        """Project only W3C propagation headers into a bounded carrier."""

        raw_headers = scope.get("headers")
        if not isinstance(raw_headers, (list, tuple)):
            return {}
        carrier: dict[str, str] = {}
        for item in raw_headers[:32]:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            raw_name, raw_value = item
            if not isinstance(raw_name, (bytes, bytearray)) or not isinstance(raw_value, (bytes, bytearray)):
                continue
            try:
                name = bytes(raw_name).decode("ascii").lower()
                value = bytes(raw_value).decode("ascii")
            except UnicodeDecodeError:
                continue
            if name not in {"traceparent", "tracestate"} or not value or len(value) > 4096:
                continue
            carrier[name] = value
        return carrier

    async def __call__(self, scope: dict[str, Any], receive: object, send: object) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method") if isinstance(scope.get("method"), str) else "OTHER"
        status_code: int | None = None

        async def observed_send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                raw_status = message.get("status")
                if type(raw_status) is int:
                    status_code = raw_status
            await send(message)

        parent_context = None
        extractor = self.extract_context
        if callable(extractor):
            try:
                parent_context = extractor(self._carrier(scope))
            except Exception:
                # A malformed propagation header must not break the request;
                # the span remains a new root with bounded attributes.
                parent_context = None
        span_kwargs = {} if parent_context is None else {"context": parent_context}
        # The middleware deliberately disables automatic exception recording;
        # otherwise SDK exporters may include request errors, headers or
        # stack text in the trace payload.  Only a bounded type/code is added.
        span_kwargs.update(record_exception=False, set_status_on_exception=False)
        with self.tracer.start_as_current_span("HTTP " + method[:16], **span_kwargs) as span:
            span.set_attribute("http.request.method", method[:16])
            try:
                await self.app(scope, receive, observed_send)
                if status_code is not None:
                    span.set_attribute("http.response.status_code", status_code)
            except Exception as error:
                record_safe_exception(span, error)
                raise


def install_otel(app: object, telemetry: object) -> OpenTelemetryRuntime:
    """Configure OTLP tracing when explicitly requested by the environment."""

    exporter_name = os.getenv("OTEL_TRACES_EXPORTER", "none").strip().lower()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    global _PROCESS_TRACER, _PROCESS_PROVIDER
    if exporter_name not in {"otlp", "otlp_proto_grpc", "otlp_proto_http"} or not endpoint:
        _PROCESS_TRACER = None
        _PROCESS_PROVIDER = None
        runtime = OpenTelemetryRuntime("NOT_CONFIGURED", None)
        _set_telemetry_export(telemetry, runtime)
        return runtime

    try:
        from opentelemetry import propagate, trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").strip().lower()
        if exporter_name == "otlp_proto_http" or protocol in {"http/protobuf", "http"}:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint)
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))
        service_name = os.getenv("OTEL_SERVICE_NAME", "rick-api").strip()[:128] or "rick-api"
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(exporter))
        # The SDK permits one provider per process. Reuse an existing provider
        # when a test or an app factory constructs more than one application.
        try:
            trace.set_tracer_provider(provider)
            active_provider = provider
        except Exception:
            active_provider = trace.get_tracer_provider()
            if active_provider is not provider:
                provider.shutdown()
        _PROCESS_PROVIDER = active_provider
        tracer = active_provider.get_tracer("rick.api", "1.0")
        add_middleware = getattr(app, "add_middleware", None)
        if not callable(add_middleware):
            raise RuntimeError("ASGI application does not expose middleware registration")
        add_middleware(_HTTPSpanMiddleware, tracer=tracer, extract_context=propagate.extract)
        _PROCESS_TRACER = tracer
        runtime = OpenTelemetryRuntime("CONFIGURED", endpoint, active_provider, tracer)
    except Exception:
        # A missing SDK or a malformed exporter must be visible in telemetry;
        # it must never make the API claim that spans were delivered.
        _PROCESS_TRACER = None
        _PROCESS_PROVIDER = None
        runtime = OpenTelemetryRuntime("NOT_CONFIGURED", endpoint)
    _set_telemetry_export(telemetry, runtime)
    return runtime


def _set_telemetry_export(telemetry: object, runtime: OpenTelemetryRuntime) -> None:
    setter = getattr(telemetry, "set_export", None)
    if callable(setter):
        setter(status=runtime.status, destination=runtime.destination)


def configure_process_otel(*, service_name: str) -> OpenTelemetryRuntime:
    """Configure a worker/non-ASGI process with the same bounded OTLP policy."""

    exporter_name = os.getenv("OTEL_TRACES_EXPORTER", "none").strip().lower()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if exporter_name not in {"otlp", "otlp_proto_grpc", "otlp_proto_http"} or not endpoint:
        return OpenTelemetryRuntime("NOT_CONFIGURED", None)
    global _PROCESS_TRACER, _PROCESS_PROVIDER
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").strip().lower()
        if exporter_name == "otlp_proto_http" or protocol in {"http/protobuf", "http"}:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint)
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))
        provider = TracerProvider(resource=Resource.create({"service.name": service_name[:128]}))
        provider.add_span_processor(BatchSpanProcessor(exporter))
        try:
            trace.set_tracer_provider(provider)
            active_provider = provider
        except Exception:
            active_provider = trace.get_tracer_provider()
            if active_provider is not provider:
                provider.shutdown()
        tracer = active_provider.get_tracer("rick.worker", "1.0")
        _PROCESS_PROVIDER = active_provider
        _PROCESS_TRACER = tracer
        return OpenTelemetryRuntime("CONFIGURED", endpoint, active_provider, tracer)
    except Exception:
        _PROCESS_TRACER = None
        _PROCESS_PROVIDER = None
        return OpenTelemetryRuntime("NOT_CONFIGURED", endpoint)


__all__ = [
    "OpenTelemetryRuntime", "attach_trace_context", "configure_process_otel",
    "current_trace_context", "extract_trace_context", "install_otel",
    "record_safe_exception", "stage_span",
]
