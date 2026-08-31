import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api.main import app, admin_create_tenant
from models.schemas import EnterpriseSession, EnterpriseTenantCreate, LoginRequest
from services.admin_service import reset_admin_state
from telemetry.tracing import init_tracing


def enterprise_headers(
    client: TestClient,
    *,
    role: str = "admin",
    tenant_id: str = "default",
) -> dict[str, str]:
    email = {
        "admin": "admin@demo.local",
        "operator": "operator@demo.local",
        "viewer": "viewer@demo.local",
    }[role]
    response = client.post(
        "/auth/login",
        json={"email": email, "password": "demo1234", "tenant_id": tenant_id},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['session_token']}"}


@pytest.fixture(autouse=True)
def reset_state():
    reset_admin_state()
    init_tracing()
    yield
    reset_admin_state()
    init_tracing()


def _admin_session() -> EnterpriseSession:
    from api.main import login

    payload = login(LoginRequest(email="admin@demo.local", password="demo1234", tenant_id="default"))
    return EnterpriseSession(**payload)


def test_sensitive_admin_role_change_requires_approval_ticket():
    client = TestClient(app)
    headers = enterprise_headers(client, role="admin", tenant_id="default")

    denied = client.patch(
        "/admin/users/user-admin",
        json={"role": "operator"},
        headers=headers,
    )

    assert denied.status_code == 409, denied.text
    assert "role_change_requires_approval" in denied.text

    approved = client.patch(
        "/admin/users/user-admin",
        json={
            "role": "operator",
            "approve_sensitive_change": True,
            "approval_ticket": "CHG-1001",
        },
        headers=headers,
    )

    assert approved.status_code == 200, approved.text
    assert approved.json()["role"] == "operator"


def test_delete_tenant_with_documents_active_is_blocked(monkeypatch):
    monkeypatch.setattr(
        "services.document_registry.get_corpus_overview",
        lambda workspace_id: {"documents": 2 if workspace_id == "tenant-docs" else 0},
    )

    session = _admin_session()
    admin_create_tenant(
        EnterpriseTenantCreate(
            tenant_id="tenant-docs",
            name="Tenant Docs",
            workspace_id="tenant-docs",
            plan="starter",
            status="active",
        ),
        session,
    )

    client = TestClient(app)
    headers = enterprise_headers(client, role="admin", tenant_id="default")
    response = client.delete("/admin/tenants/tenant-docs", headers=headers)

    assert response.status_code == 409, response.text
    assert "tenant_has_documents" in response.text


def test_observability_slo_exposes_breaches(monkeypatch):
    class FakeTelemetry:
        def get_metrics(self, days=7, workspace_id=None):
            return {
                "workspace_id": workspace_id,
                "generated_at": "2026-04-19T12:00:00Z",
                "retrieval": {
                    "hit_rate_top1": 0.35,
                    "hit_rate_top5": 0.45,
                    "p50_latency_ms": 900.0,
                    "p99_latency_ms": 6200.0,
                    "avg_retrieval_latency_ms": 2100.0,
                },
                "ingestion": {"total_documents_processed": 10, "errors": 1},
                "answer": {"groundedness_rate": 0.7, "no_context_rate": 0.22},
                "evaluation": {"total_runs": 1},
            }

    monkeypatch.setattr("api.main.get_telemetry", lambda: FakeTelemetry())
    monkeypatch.setattr("api.main.get_client", lambda: type("Client", (), {"get_collections": lambda self: True})())

    client = TestClient(app)
    headers = enterprise_headers(client, role="operator", tenant_id="default")
    response = client.get("/observability/slo?workspace_id=default", headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["workspace_id"] == "default"
    assert payload["total_breaches"] >= 1
    assert any(item["status"] == "breach" for item in payload["items"])


def test_observability_traces_returns_recent_spans_and_headers():
    client = TestClient(app)
    headers = enterprise_headers(client, role="operator", tenant_id="default")

    health = client.get("/health?workspace_id=default", headers=headers)
    assert health.status_code == 200, health.text
    assert health.headers.get("X-Request-ID")
    assert health.headers.get("X-Trace-ID")

    traces = client.get("/observability/traces?workspace_id=default&limit=10", headers=headers)

    assert traces.status_code == 200, traces.text
    payload = traces.json()
    assert payload["workspace_id"] == "default"
    assert payload["total"] >= 1
    names = {item["name"] for item in payload["items"]}
    assert "health.check" in names or "HTTP GET /health" in names


def test_admin_can_read_slo_and_traces_for_foreign_workspace(monkeypatch):
    class FakeTelemetry:
        def get_metrics(self, days=7, workspace_id=None):
            return {
                "workspace_id": workspace_id,
                "generated_at": "2026-04-19T12:00:00Z",
                "retrieval": {
                    "hit_rate_top1": 0.8,
                    "hit_rate_top5": 1.0,
                    "p50_latency_ms": 50.0,
                    "p99_latency_ms": 70.0,
                    "avg_retrieval_latency_ms": 25.0,
                },
                "ingestion": {"total_documents_processed": 2, "errors": 0},
                "answer": {"groundedness_rate": 1.0, "no_context_rate": 0.0},
                "evaluation": {"total_runs": 1},
            }

    monkeypatch.setattr("api.main.get_telemetry", lambda: FakeTelemetry())
    monkeypatch.setattr("api.main.get_client", lambda: type("Client", (), {"get_collections": lambda self: True})())

    client = TestClient(app)
    headers = enterprise_headers(client, role="admin", tenant_id="default")

    client.get("/health?workspace_id=northwind", headers=headers)
    slo = client.get("/admin/slo?workspace_id=northwind", headers=headers)
    traces = client.get("/admin/traces?workspace_id=northwind&limit=10", headers=headers)

    assert slo.status_code == 200, slo.text
    assert traces.status_code == 200, traces.text
    assert slo.json()["workspace_id"] == "northwind"
    assert traces.json()["workspace_id"] == "northwind"


def test_viewer_cannot_gain_document_upload_permission():
    from api.main import _require_permission, login
    from fastapi import HTTPException
    from models.schemas import EnterpriseSession, LoginRequest

    payload = login(LoginRequest(email="viewer@demo.local", password="demo1234", tenant_id="default"))
    session = EnterpriseSession(**payload)

    with pytest.raises(HTTPException) as exc_info:
        _require_permission(session, "documents.upload", workspace_id="default")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "forbidden"


def test_admin_password_reset_token_can_rotate_credentials_and_revoke_old_sessions():
    from services.enterprise_service import admin_issue_password_reset, confirm_password_reset, get_session, login

    initial = login(email="operator@demo.local", password="demo1234", tenant_id="default")
    token = initial["session_token"]

    issued = admin_issue_password_reset("user-operator", requested_by="user-admin", expires_in_minutes=30)
    assert issued["token"]
    confirm_password_reset(issued["token"], "ComplexPass123!")

    current = get_session(token)
    assert current["authenticated"] is False
    refreshed = login(email="operator@demo.local", password="ComplexPass123!", tenant_id="default")
    assert refreshed["authenticated"] is True


def test_admin_rag_has_runtime_permission_without_user_governance():
    from api.main import _require_permission
    from fastapi import HTTPException
    from models.schemas import EnterpriseSession
    from services.enterprise_service import login

    payload = login(email="adminrag@demo.local", password="demo1234", tenant_id="default")
    session = EnterpriseSession(**payload)

    assert _require_permission(session, "runtime.manage", workspace_id="default").user.role == "admin_rag"

    with pytest.raises(HTTPException):
        _require_permission(session, "users.manage", workspace_id="default")
