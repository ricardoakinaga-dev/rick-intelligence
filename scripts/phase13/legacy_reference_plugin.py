"""Pytest plugin: run the retired legacy reference on its SimpleTracer fallback.

The legacy component predates the locked OpenTelemetry stack. With OTel
importable, its own telemetry module returns an OTel tracer whose
``start_span`` rejects the ``workspace_id`` argument the legacy API passes, so
the same legacy code passes only when OTel is absent — an environment accident.
The legacy lanes exercise the retired code as it ran, therefore they pin the
fallback explicitly instead of depending on what happens to be installed.
"""

from __future__ import annotations


def pytest_configure(config) -> None:  # noqa: ARG001 - pytest hook signature
    import telemetry.tracing as tracing

    tracing.OTEL_AVAILABLE = False
    tracing._tracer = None
