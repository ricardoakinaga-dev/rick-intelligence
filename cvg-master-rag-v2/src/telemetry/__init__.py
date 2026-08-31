"""
Telemetry package — logging, metrics, tracing, and alerting.
"""

__all__ = ["get_telemetry", "TelemetryService"]


def __getattr__(name: str):
    if name in {"get_telemetry", "TelemetryService"}:
        from services.telemetry_service import get_telemetry, TelemetryService

        return {"get_telemetry": get_telemetry, "TelemetryService": TelemetryService}[name]
    raise AttributeError(name)
