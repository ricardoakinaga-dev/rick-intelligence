"""Monitoring must remain diagnostic traffic without supplying business SLOs."""

import asyncio
from types import SimpleNamespace

import pytest

from core.telemetry import ApiTelemetry, MAX_HISTOGRAM_SAMPLES, MAX_TELEMETRY_EVENTS
from test_telemetry_fallback import _load_fallback


MONITORING_PATHS = (
    "/health/live", "/health/ready", "/metrics", "/api/v1/admin/health",
    "/api/v1/admin/metrics", "/api/v1/admin/metrics/prometheus",
)


@pytest.fixture(params=("package", "fallback"))
def telemetry(request, monkeypatch):
    if request.param == "fallback":
        return _load_fallback(monkeypatch).ApiTelemetry()
    return ApiTelemetry()


def record(telemetry, path, status=200, *, failed=False, duration_ms=1):
    telemetry.record_request(
        method="GET", path=path, status=status, failed=failed, duration_ms=duration_ms,
    )


def total(snapshot, name):
    return sum(item["total"] for item in snapshot["counters"] if item["name"] == name)


@pytest.mark.parametrize("suffix", ("", "/", "?token=fake-secret", "/?token=fake-secret"))
def test_probes_only_leave_business_slo_no_data(telemetry, suffix):
    for index, path in enumerate(MONITORING_PATHS):
        record(telemetry, path + suffix, 503 if index % 2 else 200, duration_ms=9_000)
    snapshot = telemetry.snapshot()
    assert snapshot["slo"]["status"] == "no_data"
    assert snapshot["slo"]["observations"] == snapshot["latency"]["count"] == 0
    assert snapshot["slo"]["error_rate"] is None
    assert snapshot["slo"]["latency_p95_ms"] is None
    assert total(snapshot, "api.http.requests") == 6
    assert total(snapshot, "api.http.responses") == 6
    assert total(snapshot, "api.http.errors") == 3
    assert total(snapshot, "api.http.business.requests") == 0
    assert total(snapshot, "api.http.business.errors") == 0
    assert len(snapshot["events"]) == 6
    assert "fake-secret" not in str(snapshot)
    assert "rick_api_http_latency_ms_count 0" in telemetry.prometheus_text()


def test_probes_neither_dilute_nor_evict_a_business_error(telemetry):
    record(telemetry, "/api/v1/chat", 503, duration_ms=37)
    before = telemetry.snapshot()
    for index in range(MAX_HISTOGRAM_SAMPLES + 1):
        record(telemetry, MONITORING_PATHS[index % len(MONITORING_PATHS)], duration_ms=0)
    snapshot = telemetry.snapshot()
    assert snapshot["slo"] == before["slo"]
    assert snapshot["latency"] == before["latency"]
    assert snapshot["slo"]["status"] == "breach"
    assert snapshot["slo"]["error_rate"] == 1
    assert total(snapshot, "api.http.requests") == MAX_HISTOGRAM_SAMPLES + 2
    assert total(snapshot, "api.http.business.requests") == 1
    assert total(snapshot, "api.http.business.errors") == 1
    assert len(snapshot["events"]) == MAX_TELEMETRY_EVENTS


def test_business_movement_has_monotonic_prometheus_counters_and_explicit_scope(telemetry):
    previous = 0
    for path, status, failed in (
        ("/api/v1/chat?token=fake-secret", 200, False),
        ("/api/v1/chat", 503, False),
        ("/api/v1/documents/private-document", 200, True),
        ("/api/v1/auth/login", 401, False),
    ):
        record(telemetry, path, status, failed=failed, duration_ms=12)
        snapshot = telemetry.snapshot()
        assert total(snapshot, "api.http.business.requests") == previous + 1
        previous += 1
        assert snapshot["slo"]["observations"] == snapshot["latency"]["count"] == previous
        if previous == 1:
            assert total(snapshot, "api.http.business.errors") == 0
            assert 'rick_api_http_business_errors_total{route="chat"} 0' in telemetry.prometheus_text()
    assert total(snapshot, "api.http.business.errors") == 2
    assert snapshot["slo"]["error_rate"] == 0.5
    assert snapshot["slo"]["sample_scope"] == "business_requests"
    assert snapshot["slo"]["excluded_route_count"] == len(MONITORING_PATHS)
    assert "excluded_routes" not in snapshot["slo"]
    assert snapshot["slo"]["latency_scope"] == "response_headers"
    assert snapshot["slo"]["window_capacity"] == 10_000
    assert total(snapshot, "api.http.auth_denied") == 1
    exposition = telemetry.prometheus_text()
    assert '# TYPE rick_api_http_business_requests_total counter' in exposition
    assert '# TYPE rick_api_http_business_errors_total counter' in exposition
    assert 'rick_api_http_business_requests_total{route="chat"} 2' in exposition
    assert 'rick_api_http_business_errors_total{route="chat"} 1' in exposition
    assert 'rick_api_http_business_errors_total{route="documents"} 1' in exposition
    assert "fake-secret" not in exposition
    assert "private-document" not in exposition


@pytest.mark.parametrize("path", (
    "/health/live/business", "/health/lively", "/health/readyz", "/metrics-extra",
    "/metrics/business", "/api/v1/admin/healthcheck", "/api/v1/admin/health/business",
    "/api/v1/admin/metrics-extra", "/api/v1/admin/metrics/business",
    "/api/v1/admin/metrics/prometheus-extra", "/api/v1/admin/metrics/prometheus/business",
    "/api/v1/admin/users", "/HEALTH/LIVE", "/v1/models", "/v1/chat/completions",
))
def test_exclusion_is_exact_instead_of_a_route_family_or_prefix(telemetry, path):
    record(telemetry, path + "/?query=fake-secret", 500, duration_ms=42)
    snapshot = telemetry.snapshot()
    assert snapshot["slo"]["observations"] == snapshot["latency"]["count"] == 1
    assert snapshot["latency"]["p95"] == 42
    assert snapshot["slo"]["status"] == "breach"
    assert total(snapshot, "api.http.business.requests") == 1
    assert total(snapshot, "api.http.business.errors") == 1


def test_business_window_evicts_old_errors_but_counters_keep_growing(telemetry):
    record(telemetry, "/api/v1/chat", 500, duration_ms=9_000)
    for _ in range(MAX_HISTOGRAM_SAMPLES):
        record(telemetry, "/api/v1/chat", duration_ms=2)
    snapshot = telemetry.snapshot()
    assert snapshot["slo"]["observations"] == snapshot["latency"]["count"] == 10_000
    assert snapshot["slo"]["error_rate"] == 0
    assert snapshot["slo"]["status"] == "healthy"
    assert snapshot["latency"]["max"] == 2
    assert total(snapshot, "api.http.business.requests") == 10_001
    assert total(snapshot, "api.http.business.errors") == 1
    assert 'rick_api_http_business_requests_total{route="chat"} 10001' in telemetry.prometheus_text()
    assert 'rick_api_http_business_errors_total{route="chat"} 1' in telemetry.prometheus_text()


def test_business_latency_still_measures_response_headers(telemetry, monkeypatch):
    import core.middleware as middleware

    clock = {"now": 10.0}
    monkeypatch.setattr(middleware, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    async def application(scope, receive, send):
        clock["now"] = 10.025
        await send({"type": "http.response.start", "status": 200, "headers": []})
        clock["now"] = 16.0
        await send({"type": "http.response.body", "body": b"ok"})

    messages = []

    async def send(message):
        messages.append(message)

    observer = middleware.MetricsMiddleware(application, telemetry=telemetry)
    asyncio.run(observer.handle(
        {"type": "http", "method": "GET", "path": "/api/v1/chat", "state": {}},
        None, send,
    ))
    snapshot = telemetry.snapshot()
    assert len(messages) == 2
    assert snapshot["slo"]["latency_scope"] == "response_headers"
    assert snapshot["latency"]["count"] == 1
    assert snapshot["latency"]["p95"] == pytest.approx(25)
    assert snapshot["slo"]["status"] == "healthy"


def test_route_cardinality_is_bounded_despite_arbitrary_paths_and_identities(telemetry):
    for index in range(600):
        for prefix in ("/api/v1/documents/", "/unknown/"):
            telemetry.record_request(
                method=f"METHOD-{index}", path=f"{prefix}private-{index}?tenant=private",
                status=500, duration_ms=1, request_id=f"req-{index}", correlation_id=f"corr-{index}",
            )
    snapshot = telemetry.snapshot()
    assert len(snapshot["counters"]) == 9
    assert len(snapshot["events"]) == MAX_TELEMETRY_EVENTS
    for item in snapshot["counters"]:
        if item["name"] != "api.http.responses":
            assert item["labels"] in ({"route": "documents"}, {"route": "other"})
    assert total(snapshot, "api.http.business.requests") == 1_200
    assert total(snapshot, "api.http.business.errors") == 1_200
    assert "private" not in str(snapshot)
    assert "req-" not in telemetry.prometheus_text()
    assert "corr-" not in telemetry.prometheus_text()


@pytest.mark.parametrize("destination, origin", (
    ("http://fake-user:fake-password@collector:4317/private-path?key=fake-query#fake-fragment", "http://collector:4317"),
    ("https://fake-user:fake-password@COLLECTOR.example:443/v1/traces", "https://collector.example:443"),
    ("http://collector:4317", "http://collector:4317"),
    ("https://collector.example/", "https://collector.example"),
    ("HTTP://localhost:80/path", "http://localhost:80"),
    ("http://127.0.0.1:4318/v1/traces", "http://127.0.0.1:4318"),
    ("http://[::1]:4318/v1/traces?key=fake-query", "http://[::1]:4318"),
    (None, None), (123, None), ("", None), ("collector:4317", None),
    ("//collector:4317/path", None), ("ftp://collector/path", None),
    ("https:///path", None), ("http://", None), ("http://user@", None),
    ("http://collector:bad/path", None), ("http://collector:65536/path", None),
    ("http://collector:/path", None), ("http://[not-an-ip]/path", None),
    ("http://[::1]extra/path", None), ("http://256.256.256.256/path", None),
    ("http://collector..example/path", None), ("http://-collector/path", None),
    ("http://collector../path", None),
    ("http://collector%2fsecret/path", None), ("http://collector\\secret/path", None),
    (" http://collector/path", None), ("http://collector\n/path", None),
    ("http://collector/path\r", None), ("http://collector/path\tsecret", None),
    ("http://collector/path\x00", None), ("http://collector/path\x7f", None),
    ("http://collector/path\x85", None),
    ("http://collector/path\u202e", None),
    ("http://" + "a" * 64 + ".example/path", None),
    ("https://collector/" + "x" * 513, None),
))
def test_export_destination_contains_only_a_valid_bounded_http_origin(telemetry, destination, origin):
    telemetry.set_export(status="CONFIGURED", destination=destination)
    snapshot = telemetry.snapshot()
    assert snapshot["export"] == {"status": "CONFIGURED", "destination": origin}
    assert snapshot["slo"]["status"] == "no_data"
    assert not snapshot["events"]
    assert not snapshot["counters"]
    assert "fake-user" not in str(snapshot)
    assert "fake-password" not in str(snapshot)
    assert "private-path" not in str(snapshot)
    assert "fake-query" not in str(snapshot)
    assert "fake-fragment" not in str(snapshot)
    if origin is not None:
        assert len(origin) <= 512


def test_export_status_reports_configuration_and_never_receipt(telemetry):
    for status, expected in (
        ("CONFIGURED", "CONFIGURED"), ("NOT_CONFIGURED", "NOT_CONFIGURED"),
        ("DELIVERED", "NOT_CONFIGURED"),
    ):
        telemetry.set_export(status=status, destination="https://collector/path?fake-secret")
        assert telemetry.snapshot()["export"] == {"status": expected, "destination": "https://collector"}
    telemetry.set_export(status="NOT_CONFIGURED", destination=None)
    assert telemetry.snapshot()["export"] == {"status": "NOT_CONFIGURED", "destination": None}


def test_asgi_probes_and_scrapes_leave_no_data_then_observe_business(client, app):
    for _ in range(3):
        for path in MONITORING_PATHS:
            response = client.get(path, follow_redirects=False)
            assert response.status_code in (200, 401, 403, 503)
    snapshot = app.state.telemetry.snapshot()
    assert snapshot["slo"]["status"] == "no_data"
    assert snapshot["slo"]["observations"] == snapshot["latency"]["count"] == 0
    assert total(snapshot, "api.http.requests") == 18
    assert total(snapshot, "api.http.business.requests") == 0
    response = client.post(
        "/api/v1/chat?token=fake-secret",
        content="x" * (app.state.providers.settings.max_json_bytes + 1),
    )
    assert response.status_code == 413
    snapshot = app.state.telemetry.snapshot()
    assert snapshot["slo"]["observations"] == snapshot["latency"]["count"] == 1
    assert total(snapshot, "api.http.business.requests") == 1
    assert "fake-secret" not in str(snapshot)
