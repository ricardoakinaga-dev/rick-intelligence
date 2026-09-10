from __future__ import annotations

from core.otel import install_otel


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
