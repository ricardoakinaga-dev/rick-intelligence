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


@pytest.mark.parametrize("operation", ["create", "update", "deactivate", "reset"])
@pytest.mark.parametrize("failure", ["health_false", "health_raise", "emit_false", "emit_raise", None])
@pytest.mark.parametrize("after_persist", [False, True])
def test_admin_mutations_audit_order_and_partial_failure(client, monkeypatch, operation, failure, after_persist):
    from copy import deepcopy

    login_as(client, "admin@example.com")
    providers = client.app.state.providers
    identity = providers.identity
    before = deepcopy(identity._users.get_by_id("vet"))
    calls = []
    events = []
    mutated = False
    method_name = {"create": "create_user", "update": "update_user", "deactivate": "deactivate_user", "reset": "reset_password"}[operation]
    original = getattr(identity, method_name)

    def mutate(**kwargs):
        nonlocal mutated
        calls.append("mutation")
        value = original(**kwargs)
        mutated = True
        return value

    class Sink:
        def health_check(self):
            if mutated == after_persist:
                if failure == "health_raise":
                    raise RuntimeError("private sink failure")
                if failure == "health_false":
                    return False
            return True

        def emit(self, event):
            calls.append("audit")
            events.append(dict(event))
            if mutated == after_persist:
                if failure == "emit_raise":
                    raise RuntimeError("private sink failure")
                if failure == "emit_false":
                    return False
            return True

    monkeypatch.setattr(identity, method_name, mutate)
    providers.audit_sink = Sink()
    path = "/api/v1/admin/users"
    if operation == "create":
        response = client.post(path, json={"email": "audit-new@example.com", "role": "VETERINARIAN", "tenant_id": "default", "password": "private-new-password"})
    elif operation == "update":
        response = client.patch(f"{path}/vet", json={"email": "audit-updated@example.com"})
    elif operation == "deactivate":
        response = client.post(f"{path}/vet/deactivate")
    else:
        response = client.post(f"{path}/vet/reset-password", json={"password": "private-new-password"})

    # These mutations share the mandatory owner transaction. Completion failure
    # rolls back the credential mutation instead of acknowledging a partial effect.
    if failure:
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "provider_unavailable"
        assert identity._users.get_by_id("vet") == before
        assert identity._users.get_by_email("audit-new@example.com") is None
        if not after_persist:
            assert "mutation" not in calls
        else:
            assert calls[:2] == ["audit", "mutation"]
    else:
        assert response.status_code == (201 if operation == "create" else 200), response.text
        assert (identity._users.get_by_email("audit-new@example.com") is not None if operation == "create" else identity._users.get_by_id("vet") != before)
        assert calls == ["audit", "mutation", "audit"]
        assert events[0]["status"] == "in_progress"
        assert events[-1]["status"] == "completed"
        assert events[-1].get("target_id") == (None if operation == "create" else "vet")
    assert all(event["actor_user_id"] == "admin" and event["tenant_id"] == "default" for event in events)
    assert "private-new-password" not in json.dumps(events) + response.text
    assert "private sink failure" not in response.text


@pytest.mark.parametrize("operation", ["create", "update", "deactivate", "reset"])
@pytest.mark.parametrize("failure", ["emit_false", "emit_raise", "health_false", "health_raise"])
def test_manual_review_admin_event_survives_app_restart(tmp_path, monkeypatch, operation, failure):
    from copy import deepcopy
    from core.errors import ApiError
    from services.audit_operations import OperationLedger
    settings = make_settings(audit_sqlite_path=str(tmp_path / 'audit' / 'events.sqlite3'))
    first = TestClient(create_app(settings), raise_server_exceptions=False)
    login_as(first, 'admin@example.com')
    before = deepcopy(first.app.state.providers.identity._users.get_by_id('vet'))
    sink = first.app.state.providers.audit_sink
    append_outcome = OperationLedger.append_outcome
    def fail_completion(self, connection, record):
        if record['status'] == 'completed':
            if failure.endswith('raise'):
                raise RuntimeError('private mandatory completion failure')
            raise ApiError('provider_unavailable')
        return append_outcome(self, connection, record)
    monkeypatch.setattr(OperationLedger, 'append_outcome', fail_completion)
    def execute(client):
        kwargs = dict(headers={'Idempotency-Key':'restart-' + operation})
        path = '/api/v1/admin/users'
        if operation == 'create':
            return client.post(path, json=dict(email='pending@example.com', role='VETERINARIAN', tenant_id='default', password='private-new-password'), **kwargs)
        if operation == 'update':
            return client.patch(path + '/vet', json={'email':'pending@example.com'}, **kwargs)
        if operation == 'deactivate':
            return client.post(path + '/vet/deactivate', **kwargs)
        return client.post(path + '/vet/reset-password', json={'password':'private-new-password'}, **kwargs)
    response = execute(first)
    assert response.status_code == 503, response.text
    assert first.app.state.providers.identity._users.get_by_id('vet') == before
    assert first.app.state.providers.identity._users.get_by_email('pending@example.com') is None
    action = {'create':'admin.user_created','update':'admin.user_updated','deactivate':'admin.user_deactivated','reset':'admin.user_access_reset'}[operation]
    failed = [event for event in sink.list(tenant_id='default') if event.get('action')==action and event.get('status')=='failed']
    assert len(failed)==1 and failed[0]['actor_user_id']=='admin'
    assert failed[0].get('target_id') == (None if operation=='create' else 'vet')
    assert not any(event.get('action')==action and event.get('status')=='completed' for event in sink.list(tenant_id='default'))
    sink.close()
    second = TestClient(create_app(settings), raise_server_exceptions=False)
    try:
        login_as(second, 'admin@example.com')
        listed = second.get('/api/v1/admin/audit')
        assert listed.status_code==200 and failed[0] in listed.json()['items']
        status = second.get('/api/v1/audit/operations/' + failed[0]['correlation_id'])
        assert status.status_code==200 and status.json()['audit_status']=='failed'
        assert status.json()['execution']['phase']=='rolled_back'
        replay = execute(second)
        assert replay.status_code==503 and replay.json()['error']['code']=='provider_unavailable'
        assert second.app.state.providers.identity._users.get_by_id('vet') == before
        assert second.app.state.providers.identity._users.get_by_email('pending@example.com') is None
        assert second.app.state.providers.audit_sink.list(tenant_id='foreign')==[]
        assert 'private' not in listed.text
    finally:
        second.app.state.providers.audit_sink.close()


@pytest.mark.parametrize("failure", ["false", "raise"])
def test_pending_registration_failure_is_not_reported_as_registered(tmp_path, monkeypatch, failure):
    client = TestClient(create_app(make_settings(
        audit_sqlite_path=str(tmp_path / "audit" / "events.sqlite3"),
    )), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    sink = client.app.state.providers.audit_sink
    from services.audit_operations import OperationLedger
    from core.errors import ApiError
    append_outcome = OperationLedger.append_outcome
    def fail_completion(self, connection, record):
        if record['status'] == 'completed':
            if failure == 'raise':
                raise RuntimeError('private storage failure')
            raise ApiError('provider_unavailable')
        return append_outcome(self, connection, record)
    monkeypatch.setattr(OperationLedger, 'append_outcome', fail_completion)

    try:
        response = client.patch("/api/v1/admin/users/vet", json={"email": "applied@example.com"})
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "provider_unavailable"
        assert client.app.state.providers.identity._users.get_by_id("vet")["email"] == "vet@example.com"
        assert "private" not in response.text
    finally:
        sink.close()


@pytest.mark.parametrize("operation", ["create", "update", "deactivate", "reset"])
def test_production_safe_identity_requires_atomic_admin_audit(monkeypatch, operation):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    providers = client.app.state.providers
    identity = providers.identity
    before_user = identity._users.get_by_id("vet")
    before_events = list(providers.audit_sink.events)
    monkeypatch.setattr(identity, "production_safe", True, raising=False)

    if operation == "create":
        response = client.post("/api/v1/admin/users", json={
            "email": "must-not-create@example.com", "role": "VETERINARIAN",
            "tenant_id": "default", "password": "private-password",
        })
        assert identity._users.get_by_email("must-not-create@example.com") is None
    elif operation == "update":
        response = client.patch("/api/v1/admin/users/vet", json={"email": "must-not-update@example.com"})
        assert identity._users.get_by_id("vet") == before_user
    elif operation == "deactivate":
        response = client.post("/api/v1/admin/users/vet/deactivate")
        assert identity._users.get_by_id("vet") == before_user
    else:
        response = client.post("/api/v1/admin/users/vet/reset-password", json={"password": "private-password"})
        assert identity._users.get_by_id("vet") == before_user

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert providers.audit_sink.events == before_events
    close = getattr(providers.audit_sink, "close", None)
    if callable(close):
        close()


@pytest.mark.parametrize("operation", ["create", "update", "deactivate", "reset"])
def test_durable_identity_without_atomic_admin_audit_fails_before_mutation(monkeypatch, operation):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    providers = client.app.state.providers
    identity = providers.identity
    before_user = identity._users.get_by_id("vet")
    before_events = list(providers.audit_sink.events)
    monkeypatch.setattr(identity, "production_safe", False, raising=False)
    monkeypatch.setattr(identity, "durable_admin_mutations", True, raising=False)

    if operation == "create":
        response = client.post("/api/v1/admin/users", json={
            "email": "must-not-create-durable@example.com", "role": "VETERINARIAN",
            "tenant_id": "default", "password": "private-password",
        })
        assert identity._users.get_by_email("must-not-create-durable@example.com") is None
    elif operation == "update":
        response = client.patch("/api/v1/admin/users/vet", json={"email": "must-not-update@example.com"})
        assert identity._users.get_by_id("vet") == before_user
    elif operation == "deactivate":
        response = client.post("/api/v1/admin/users/vet/deactivate")
        assert identity._users.get_by_id("vet") == before_user
    else:
        response = client.post("/api/v1/admin/users/vet/reset-password", json={"password": "private-password"})
        assert identity._users.get_by_id("vet") == before_user

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert providers.audit_sink.events == before_events
    close = getattr(providers.audit_sink, "close", None)
    if callable(close):
        close()


@pytest.mark.parametrize("operation", ["create", "update", "deactivate", "reset"])
def test_partial_atomic_identity_fails_before_non_atomic_fallback(monkeypatch, operation):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    providers = client.app.state.providers
    identity = providers.identity
    before_user = identity._users.get_by_id("vet")
    before_events = list(providers.audit_sink.events)
    monkeypatch.setattr(identity, "supports_atomic_admin_audit", True, raising=False)
    monkeypatch.setattr(identity, "durable_admin_mutations", True, raising=False)

    if operation == "create":
        response = client.post("/api/v1/admin/users", json={
            "email": "must-not-create-partial@example.com", "role": "VETERINARIAN",
            "tenant_id": "default", "password": "private-password",
        })
        assert identity._users.get_by_email("must-not-create-partial@example.com") is None
    elif operation == "update":
        response = client.patch("/api/v1/admin/users/vet", json={"email": "must-not-update-partial@example.com"})
        assert identity._users.get_by_id("vet") == before_user
    elif operation == "deactivate":
        response = client.post("/api/v1/admin/users/vet/deactivate")
        assert identity._users.get_by_id("vet") == before_user
    else:
        response = client.post("/api/v1/admin/users/vet/reset-password", json={"password": "private-password"})
        assert identity._users.get_by_id("vet") == before_user

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert providers.audit_sink.events == before_events
    close = getattr(providers.audit_sink, "close", None)
    if callable(close):
        close()


def test_production_mode_cannot_use_the_volatile_admin_audit_fallback(monkeypatch):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    providers = client.app.state.providers
    identity = providers.identity
    before_user = identity._users.get_by_id("vet")
    before_events = list(providers.audit_sink.events)
    monkeypatch.setattr(identity, "mode", "production", raising=False)
    monkeypatch.setattr(identity, "production_safe", False, raising=False)
    monkeypatch.setattr(identity, "durable_admin_mutations", False, raising=False)

    response = client.patch("/api/v1/admin/users/vet", json={"email": "must-not-update@example.com"})

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert identity._users.get_by_id("vet") == before_user
    assert providers.audit_sink.events == before_events
    close = getattr(providers.audit_sink, "close", None)
    if callable(close):
        close()


@pytest.mark.parametrize(("identity_mode", "environment"), [
    ("staging", "local"),
    ("dev", "staging"),
    ("dev", "production"),
])
def test_volatile_admin_fallback_is_restricted_to_dev_or_test_runtime(
    monkeypatch, identity_mode, environment,
):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    providers = client.app.state.providers
    identity = providers.identity
    before_user = identity._users.get_by_id("vet")
    before_events = list(providers.audit_sink.events)
    monkeypatch.setattr(identity, "mode", identity_mode, raising=False)
    object.__setattr__(providers.settings, "environment", environment)

    response = client.patch("/api/v1/admin/users/vet", json={"email": "must-not-update-outside-dev@example.com"})

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert identity._users.get_by_id("vet") == before_user
    assert providers.audit_sink.events == before_events
    close = getattr(providers.audit_sink, "close", None)
    if callable(close):
        close()


@pytest.mark.parametrize("operation", ["create", "update", "deactivate", "reset"])
def test_volatile_admin_fallback_requires_explicit_production_safety_declaration(
    monkeypatch, operation,
):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    providers = client.app.state.providers
    identity = providers.identity
    before_user = identity._users.get_by_id("vet")
    before_events = list(providers.audit_sink.events)
    monkeypatch.setattr(identity, "mode", "dev", raising=False)
    monkeypatch.setattr(identity, "durable_admin_mutations", False, raising=False)
    monkeypatch.delattr(identity, "production_safe", raising=False)

    if operation == "create":
        response = client.post("/api/v1/admin/users", json={
            "email": "must-not-create-undeclared@example.com", "role": "VETERINARIAN",
            "tenant_id": "default", "password": "private-password",
        })
        assert identity._users.get_by_email("must-not-create-undeclared@example.com") is None
    elif operation == "update":
        response = client.patch(
            "/api/v1/admin/users/vet",
            json={"email": "must-not-update-undeclared@example.com"},
        )
        assert identity._users.get_by_id("vet") == before_user
    elif operation == "deactivate":
        response = client.post("/api/v1/admin/users/vet/deactivate")
        assert identity._users.get_by_id("vet") == before_user
    else:
        response = client.post(
            "/api/v1/admin/users/vet/reset-password",
            json={"password": "private-password"},
        )
        assert identity._users.get_by_id("vet") == before_user

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert providers.audit_sink.events == before_events
    close = getattr(providers.audit_sink, "close", None)
    if callable(close):
        close()


def test_admin_create_route_replays_native_owner_mutation_once(monkeypatch):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    identity = client.app.state.providers.identity
    original = identity.create_user
    calls = []
    def create(**values):
        calls.append(values)
        return original(**values)
    monkeypatch.setattr(identity, 'create_user', create)
    payload = dict(email='atomic-create@example.com', role='VETERINARIAN', tenant_id='default', password='private-password')
    first = client.post('/api/v1/admin/users', json=payload, headers={'Idempotency-Key':'native-create'})
    replay = client.post('/api/v1/admin/users', json=payload, headers={'Idempotency-Key':'native-create'})
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert len(calls) == 1
    assert identity._users.get_by_email(payload['email'])['user_id'] == first.json()['user']['user_id']
    assert 'password' not in first.text
    events = [event for event in client.app.state.providers.audit_sink.events if event.get('action')=='admin.user_created']
    assert [event['status'] for event in events] == ['in_progress', 'completed']
    client.close()


def test_unresolved_admin_audit_markers_are_not_evicted_by_audit_retention(tmp_path):
    from services.sqlite_audit import SQLiteAuditSink

    path = tmp_path / "audit" / "events.sqlite3"
    legacy_pending = {"action": "admin.user_updated", "tenant_id": "default", "status": "pending_completion"}
    manual_review = {"action": "admin.user_deactivated", "tenant_id": "default", "status": "manual_review_required"}
    with SQLiteAuditSink(path, max_events=1) as sink:
        assert sink.append(legacy_pending)
        assert sink.append(manual_review)
        assert sink.append({"action": "probe", "tenant_id": "default"})
    with SQLiteAuditSink(path, max_events=1) as sink:
        assert legacy_pending in sink.list(tenant_id="default")
        assert manual_review in sink.list(tenant_id="default")


@pytest.mark.parametrize("sink", [None, object()])
def test_emit_required_rejects_missing_sink_or_emitter(sink):
    from core.errors import ApiError
    from services.audit import emit_required

    with pytest.raises(ApiError) as exc:
        emit_required(sink, {"action": "test"})
    assert exc.value.code == "provider_unavailable"


def test_emit_required_accepts_legacy_none_acknowledgement():
    from services.audit import emit_required

    events = []

    class Sink:
        def emit(self, event):
            events.append(event)

    emit_required(Sink(), {"action": "test"})
    assert events == [{"action": "test"}]


def test_production_rejects_local_audit_path():
    with pytest.raises(ValueError, match="external audit store"):
        make_settings(
            environment="production",
            identity_mode="production",
            session_cookie_secure=True,
            chat_backend_mode="legacy",
            audit_sqlite_path="/var/lib/rick/audit.sqlite3",
        ).validate()
