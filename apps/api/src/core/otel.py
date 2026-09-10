"""Optional OpenTelemetry runtime for the canonical API boundary.

The API remains importable in the hermetic test environment when the SDK is
not installed.  A production-shaped image installs the pinned SDK/exporter;
when OTEL is enabled, this module creates one process-owned tracer provider,
exports bounded HTTP spans over OTLP, and closes the exporter with the app.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


@dataclass(slots=True)
class OpenTelemetryRuntime:
    status: str
    destination: str | None
    provider: object | None = None

    def close(self) -> None:
        shutdown = getattr(self.provider, "shutdown", None)
        if callable(shutdown):
            shutdown()


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
            if name not in {"traceparent", "tracestate", "baggage"} or not value or len(value) > 4096:
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
        with self.tracer.start_as_current_span("HTTP " + method[:16], **span_kwargs) as span:
            span.set_attribute("http.request.method", method[:16])
            try:
                await self.app(scope, receive, observed_send)
                if status_code is not None:
                    span.set_attribute("http.response.status_code", status_code)
            except Exception as error:
                record = getattr(span, "record_exception", None)
                if callable(record):
                    record(error)
                raise


def install_otel(app: object, telemetry: object) -> OpenTelemetryRuntime:
    """Configure OTLP tracing when explicitly requested by the environment."""

    exporter_name = os.getenv("OTEL_TRACES_EXPORTER", "none").strip().lower()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if exporter_name not in {"otlp", "otlp_proto_grpc", "otlp_proto_http"} or not endpoint:
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
        trace.set_tracer_provider(provider)
        tracer = provider.get_tracer("rick.api", "1.0")
        add_middleware = getattr(app, "add_middleware", None)
        if not callable(add_middleware):
            raise RuntimeError("ASGI application does not expose middleware registration")
        add_middleware(_HTTPSpanMiddleware, tracer=tracer, extract_context=propagate.extract)
        runtime = OpenTelemetryRuntime("CONFIGURED", endpoint, provider)
    except Exception:
        # A missing SDK or a malformed exporter must be visible in telemetry;
        # it must never make the API claim that spans were delivered.
        runtime = OpenTelemetryRuntime("NOT_CONFIGURED", endpoint)
    _set_telemetry_export(telemetry, runtime)
    return runtime


def _set_telemetry_export(telemetry: object, runtime: OpenTelemetryRuntime) -> None:
    setter = getattr(telemetry, "set_export", None)
    if callable(setter):
        setter(status=runtime.status, destination=runtime.destination)


__all__ = ["OpenTelemetryRuntime", "install_otel"]
