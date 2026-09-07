from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from app import create_app
from conftest import login_as, make_settings
from services.audit import InMemoryAuditSink


def test_in_memory_audit_sink_is_bounded_and_redacts_sensitive_fields():
    sink = InMemoryAuditSink(max_events=2)
    sink.emit({
        "action": "chat.query",
        "actor_user_id": "user-1",
        "prompt": "private source text",
        "authorization": "Bearer secret-token",
        "target_id": "https://example.test/callback?token=secret",
        "opaque": "synthetic secret and private document content",
        "nested": {"document_content": "private document"},
    })
    stored = sink.events[-1]
    for sequence in (1, 2):
        sink.emit({"action": "probe", "request_id": f"req-{sequence}"})

    assert len(sink.events) == 2
    assert sink.events[-1]["request_id"] == "req-2"
    assert "prompt" not in stored
    assert "authorization" not in stored
    assert stored["target_id"] == "https://example.test/callback"
    assert "opaque" not in stored
    assert "nested" not in stored
    assert "private source text" not in json.dumps(stored)
    assert "secret-token" not in json.dumps(stored)


def test_in_memory_audit_sink_strips_userinfo_for_non_http_urls():
    sink = InMemoryAuditSink()
    sink.emit({
        "action": "storage.probe",
        "target_id": "postgres://alice:secret@example.test/rick?password=secret#fragment",
    })

    assert sink.events == [{"action": "storage.probe", "target_id": "postgres://example.test/rick"}]
    assert "alice" not in json.dumps(sink.events)
    assert "secret" not in json.dumps(sink.events)


def test_admin_audit_reads_the_redacted_default_sink():
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    client.app.state.providers.audit_sink.emit({
        "action": "chat.query",
        "tenant_id": "default",
        "prompt": "must not reach the admin boundary",
        "document_content": "must not reach the admin boundary",
        "target_id": "https://example.test/audit?token=secret",
    })

    response = client.get("/api/v1/admin/audit")

    assert response.status_code == 200, response.text
    event = next(item for item in response.json()["items"] if item.get("action") == "chat.query")
    assert "prompt" not in event
    assert "document_content" not in event
    assert event["target_id"] == "https://example.test/audit"
    assert "must not reach the admin boundary" not in response.text
    assert "token=secret" not in response.text


def test_admin_identity_and_audit_views_are_tenant_scoped():
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    identity = client.app.state.providers.identity
    identity._users.seed({
        "user_id": "admin-tenant-b",
        "email": "admin-tenant-b@example.com",
        "role": "PLATFORM_ADMIN",
        "tenant_id": "tenant-b",
        "workspace_id": "default",
        "status": "active",
        "permission_overrides": {"add": [], "remove": []},
        "authorized_collection_ids": [],
        "password_plain": "password123",
        "password_version": 1,
        "role_version": 1,
    })

    login_as(client, "admin@example.com")
    foreign = TestClient(client.app, raise_server_exceptions=False)
    foreign_login = foreign.post(
        "/api/v1/auth/login",
        json={"email": "admin-tenant-b@example.com", "password": "password123", "tenant_id": "tenant-b"},
    )
    assert foreign_login.status_code == 200, foreign_login.text
    users = client.get("/api/v1/admin/users")
    assert users.status_code == 200, users.text
    assert all(item.get("tenant_id", "default") == "default" for item in users.json()["items"])
    assert "admin-tenant-b@example.com" not in users.text

    cross_tenant_create = client.post(
        "/api/v1/admin/users",
        json={
            "email": "created-tenant-b@example.com",
            "role": "VETERINARIAN",
            "tenant_id": "tenant-b",
            "password": "password123",
        },
    )
    assert cross_tenant_create.status_code == 403, cross_tenant_create.text
    assert identity._users.get_by_email("created-tenant-b@example.com") is None

    same_tenant_create = client.post(
        "/api/v1/admin/users",
        json={
            "email": "created-default@example.com",
            "role": "VETERINARIAN",
            "tenant_id": "default",
            "password": "password123",
        },
    )
    assert same_tenant_create.status_code == 201, same_tenant_create.text
    assert "password" not in same_tenant_create.text.lower()

    cross_tenant_revoke = client.post(
        "/api/v1/admin/sessions/revoke",
        json={"user_id": "admin-tenant-b"},
    )
    assert cross_tenant_revoke.status_code == 403, cross_tenant_revoke.text
    identity._users.seed({
        "user_id": "tenantless-user",
        "email": "tenantless@example.com",
        "role": "VETERINARIAN",
        "workspace_id": "default",
        "status": "active",
    })
    tenantless_revoke = client.post(
        "/api/v1/admin/sessions/revoke",
        json={"user_id": "tenantless-user"},
    )
    assert tenantless_revoke.status_code == 403, tenantless_revoke.text
    cross_tenant_session_revoke = client.post(
        "/api/v1/admin/sessions/revoke",
        json={"session_id": foreign_login.json()["session_id"]},
    )
    assert cross_tenant_session_revoke.status_code == 403, cross_tenant_session_revoke.text
    assert foreign.get("/api/v1/auth/me").status_code == 200

    sink = client.app.state.providers.audit_sink
    sink.emit({"action": "tenant-b.secret-action", "tenant_id": "tenant-b", "target_id": "tenant-b-only"})
    sink.emit({"action": "default.visible-action", "tenant_id": "default", "target_id": "default-only"})
    audit = client.get("/api/v1/admin/audit")
    assert audit.status_code == 200, audit.text
    actions = {item.get("action") for item in audit.json()["items"]}
    assert "default.visible-action" in actions
    assert "tenant-b.secret-action" not in actions


def test_session_list_is_tenant_scoped_and_publicly_allowlisted():
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    user_id = client.get("/api/v1/auth/me").json()["user_id"]
    identity = client.app.state.providers.identity
    identity.list_sessions = lambda _user_id: [
        {
            "session_id": "safe-session",
            "user_id": user_id,
            "tenant_id": "default",
            "created_at": 1,
            "revoked": False,
        },
        {
            "session_id": "foreign-session",
            "user_id": "foreign-user",
            "tenant_id": "tenant-b",
            "session_token": "foreign-secret",
            "created_at": 2,
            "revoked": False,
        },
        {
            "session_id": "secret-session",
            "user_id": user_id,
            "tenant_id": "default",
            "session_token": "do-not-return",
            "private_url": "https://alice:secret@example.test/session",
            "created_at": 3,
            "revoked": False,
        },
    ]

    response = client.get("/api/v1/auth/sessions")

    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {"session_id": "safe-session", "user_id": user_id, "created_at": 1, "revoked": False},
        {"session_id": "secret-session", "user_id": user_id, "created_at": 3, "revoked": False},
    ]
    assert "session_token" not in response.text
    assert "alice:secret" not in response.text


def test_local_factory_uses_restartable_audit_sink(tmp_path: Path):
    database = tmp_path / "audit" / "events.sqlite3"
    first = TestClient(
        create_app(make_settings(audit_sqlite_path=str(database))),
        raise_server_exceptions=False,
    )
    login_as(first, "km@example.com")
    assert first.app.state.providers.audit_sink.events[-1]["action"] == "auth.login"
    first.app.state.providers.audit_sink.close()

    second = TestClient(
        create_app(make_settings(audit_sqlite_path=str(database))),
        raise_server_exceptions=False,
    )
    assert second.app.state.providers.audit_sink.events[-1]["action"] == "auth.login"
    second.app.state.providers.audit_sink.close()


def test_production_rejects_local_audit_path():
    with pytest.raises(ValueError, match="external audit store"):
        make_settings(
            environment="production",
            identity_mode="production",
            session_cookie_secure=True,
            chat_backend_mode="legacy",
            audit_sqlite_path="/var/lib/rick/audit.sqlite3",
        ).validate()
