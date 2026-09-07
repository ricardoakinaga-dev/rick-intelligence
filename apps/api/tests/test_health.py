"""Health semantics: live vs ready, truthful degraded/not_ready, admin detail gated."""

from fastapi.testclient import TestClient

from app import create_app
from conftest import login_as, make_settings
from core.lifecycle import DependencyState
from dependencies.services import Providers
from services.audit import InMemoryAuditSink
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider


def test_live_and_ready_ok(client):
    assert client.get("/health/live").json()["status"] == "live"
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_not_ready_when_required_down():
    def bad():
        return DependencyState(name="qdrant", ok=False, required=True)

    providers = Providers(settings=make_settings(), identity=InMemoryIdentityProvider(),
                          chat_backend=StubChatBackend(), health_checks={"qdrant": bad},
                          audit_sink=InMemoryAuditSink())
    c = TestClient(create_app(providers.settings, providers), raise_server_exceptions=False)
    resp = c.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


def test_degraded_when_optional_down():
    def bad():
        return DependencyState(name="provider", ok=False, required=False)

    providers = Providers(settings=make_settings(), identity=InMemoryIdentityProvider(),
                          chat_backend=StubChatBackend(), health_checks={"provider": bad},
                          audit_sink=InMemoryAuditSink())
    c = TestClient(create_app(providers.settings, providers), raise_server_exceptions=False)
    resp = c.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"


def test_admin_health_requires_permission(client):
    assert client.get("/api/v1/admin/health").status_code == 401
    login_as(client, "vet@example.com")
    assert client.get("/api/v1/admin/health").status_code == 403
    login_as(client, "admin@example.com")
    resp = client.get("/api/v1/admin/health")
    assert resp.status_code == 200
    assert "checks" in resp.json()


def test_admin_metrics_are_bounded_and_redacted(client):
    assert client.get("/api/v1/admin/metrics").status_code == 401
    login_as(client, "admin@example.com")
    response = client.get("/api/v1/admin/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["implementation"] in {"rick_observability", "api_fallback"}
    assert body["export"] == {"status": "NOT_CONFIGURED", "destination": None}
    assert body["slo"]["status"] in {"healthy", "no_data", "breach"}
    assert body["latency"]["count"] >= 1
    assert body["event_capacity"] == 256
    assert len(body["events"]) <= body["event_capacity"]
    assert all(event["event"] in {"api.http.request", "api.http.abandonment"} for event in body["events"])
    assert all(event["fields"].get("request_id") for event in body["events"])
    assert all(event["fields"].get("correlation_id") for event in body["events"])
    assert all("route" not in str(counter.get("labels", {})).split("?")[-1] or "/api/" not in str(counter) for counter in body["counters"])
    assert "/api/v1/admin/metrics" not in response.text
    assert "authorization" not in response.text.lower()
