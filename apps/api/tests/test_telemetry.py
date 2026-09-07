"""Telemetry must observe early rejections and consistent SLO windows."""

from fastapi.testclient import TestClient

from app import create_app
from conftest import make_settings
from core.telemetry import ApiTelemetry, MAX_HISTOGRAM_SAMPLES, MAX_TELEMETRY_EVENTS


def test_recent_errors_are_not_diluted_by_expired_successes():
    telemetry = ApiTelemetry()
    assert telemetry.snapshot()["slo"]["status"] == "no_data"
    for _ in range(MAX_HISTOGRAM_SAMPLES):
        telemetry.record_request(method="GET", path="/health/live", status=200, duration_ms=1)
    for _ in range(600):
        telemetry.record_request(method="GET", path="/health/ready", status=503, duration_ms=2)
    snapshot = telemetry.snapshot()
    assert snapshot["slo"]["observations"] == snapshot["latency"]["count"] == MAX_HISTOGRAM_SAMPLES
    assert snapshot["slo"]["error_rate"] == 0.06
    assert snapshot["slo"]["status"] == "breach"


def test_body_limit_rejection_is_counted_without_recording_content():
    app = create_app(make_settings(max_json_bytes=100))
    client = TestClient(app)
    response = client.post("/api/v1/chat?token=private", content="secret" * 100)
    assert response.status_code == 413
    snapshot = app.state.telemetry.snapshot()
    assert snapshot["slo"]["observations"] == 1
    assert any(item["labels"] == {"status": "4xx"} for item in snapshot["counters"])
    assert "private" not in str(snapshot)
    assert "secret" not in str(snapshot)


def test_request_events_are_bounded_correlated_and_path_safe():
    telemetry = ApiTelemetry()
    telemetry.record_request(
        method="POST", path="/api/v1/chat?token=private", status=200,
        duration_ms=12.5, request_id="req-1", correlation_id="corr-1",
    )
    first = telemetry.snapshot()
    assert len(first["events"]) == 1
    assert first["events"][0]["event"] == "api.http.request"
    assert first["events"][0]["fields"] == {
        "request_id": "req-1",
        "correlation_id": "corr-1",
        "route": "chat",
        "method": "POST",
        "status_class": "2xx",
        "outcome": "response",
        "duration_ms": 12.5,
    }
    assert "?token=private" not in str(first)
    first["events"][0]["fields"]["request_id"] = "tampered"
    first["events"].clear()
    assert telemetry.snapshot()["events"][0]["fields"]["request_id"] == "req-1"

    for index in range(MAX_TELEMETRY_EVENTS + 5):
        telemetry.record_request(
            method="TRACE", path="/api/v1/chat", status=500,
            duration_ms=index, request_id=f"req-{index}", correlation_id=f"corr-{index}",
        )
    snapshot = telemetry.snapshot()
    assert snapshot["event_capacity"] == MAX_TELEMETRY_EVENTS
    assert len(snapshot["events"]) == MAX_TELEMETRY_EVENTS
    assert snapshot["events"][-1]["fields"]["method"] == "OTHER"
    assert snapshot["events"][-1]["fields"]["outcome"] == "error"


def test_worker_events_use_an_allowlisted_opaque_contract_and_are_immutable():
    telemetry = ApiTelemetry()
    raw = {
        "event": "worker.ingestion.published",
        "fields": {
            "job_ref": "raw-job-id",
            "worker_ref": "thread-name",
            "request_ref": "raw-request-id",
            "correlation_ref": "raw-correlation-id",
            "status": "published",
            "stage": "published",
            "progress": 2,
            "attempt": 999,
            "tenant_id": "tenant-secret",
            "source_path": "/private/source.txt",
            "error": "private exception text",
        },
    }
    telemetry.emit(raw)
    raw["fields"]["status"] = "failed"

    snapshot = telemetry.snapshot()
    assert len(snapshot["events"]) == 1
    event = snapshot["events"][0]
    assert event["event"] == "worker.ingestion.published"
    assert event["fields"]["status"] == "published"
    assert event["fields"]["progress"] == 1.0
    assert event["fields"]["attempt"] == 999
    assert len(event["fields"]["job_ref"]) == 16
    assert event["fields"]["job_ref"] != "raw-job-id"
    assert set(event["fields"]) <= {
        "job_ref", "worker_ref", "request_ref", "correlation_ref", "status",
        "stage", "progress", "attempt", "attempts", "error_code", "changed", "count",
    }
    assert "tenant-secret" not in str(snapshot)
    assert "/private/source.txt" not in str(snapshot)
    assert "private exception text" not in str(snapshot)


def test_worker_event_sink_rejects_malformed_names_without_mutating_metrics():
    telemetry = ApiTelemetry()
    telemetry.emit({"event": "api.http.request", "fields": {"status": "secret"}})
    telemetry.emit({"event": "worker.ingestion?token=secret", "fields": {"status": "published"}})
    telemetry.emit({"event": "worker.arbitrary.internal", "fields": {"status": "published"}})
    assert telemetry.snapshot()["events"] == []


def test_worker_queue_and_runner_events_keep_bounded_operational_fields():
    telemetry = ApiTelemetry()

    telemetry.emit({
        "event": "worker.runner.started",
        "fields": {"workers": 64},
    })
    telemetry.emit({
        "event": "worker.queue.failed",
        "fields": {
            "job_ref": "0123456789abcdef",
            "status": "dead",
            "attempts": 4,
            "error": "provider_timeout",
            "recovered": 7,
        },
    })

    events = telemetry.snapshot()["events"]
    assert events[0]["fields"] == {"workers": 64}
    assert events[1]["fields"] == {
        "job_ref": "0123456789abcdef",
        "status": "dead",
        "attempts": 4,
        "error": "provider_timeout",
        "recovered": 7,
    }


def test_worker_event_schema_rejects_cross_event_fields_and_invalid_states():
    telemetry = ApiTelemetry()
    telemetry.emit({
        "event": "worker.queue.acked",
        "fields": {
            "job_ref": "0123456789abcdef",
            "status": "published",
            "stage": "embedding",
            "workers": 64,
            "attempts": 2,
        },
    })
    assert telemetry.snapshot()["events"] == [{
        "event": "worker.queue.acked",
        "fields": {"job_ref": "0123456789abcdef", "attempts": 2},
    }]
