"""Failure-first HTTP regressions for AUD12-A01 / PROD12-007.

These exercise the real PostgreSQL facade and canonical session lifecycle with
an in-memory backing and injected write failure. They do not prove live PG.
"""
from __future__ import annotations

import gc
import pytest

from apps.api.tests.support import login_as
from rick_identity import PostgresIdentityError
from services.postgres_identity import PostgresIdentityProvider


def _facade(backing):
    facade = PostgresIdentityProvider(lambda: None)
    facade._provider = backing._provider
    return facade


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
def test_failed_revocation_is_not_confirmed_and_can_be_retried(client, providers, monkeypatch, transport):
    login_as(client, "admin@example.com")
    token = client.cookies.get(providers.settings.session_cookie_name)
    assert token
    backing = providers.identity
    providers.identity = _facade(backing)
    client.app.state.providers.identity = providers.identity
    original_delete = backing._sessions.delete

    def unavailable(_token):
        raise PostgresIdentityError() from RuntimeError("synthetic-private-db-detail")

    monkeypatch.setattr(backing._sessions, "delete", unavailable)
    headers = {}
    if transport == "bearer":
        client.cookies.clear()
        headers = {"Authorization": f"Bearer {token}"}
    before = len(providers.audit_sink.events)
    failed = client.post("/api/v1/auth/logout", headers=headers)

    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "result_indeterminate"
    assert "signed_out" not in failed.text
    assert "synthetic-private-db-detail" not in failed.text
    assert token not in failed.text
    assert "set-cookie" not in failed.headers
    attempts = providers.audit_sink.events[before:]
    assert attempts == []
    assert providers.identity.validate_token(token).authenticated
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    monkeypatch.setattr(backing._sessions, "delete", original_delete)
    success = client.post("/api/v1/auth/logout", headers=headers)
    assert success.status_code == 200
    assert success.json() == {"status": "signed_out"}
    assert not providers.identity.validate_token(token).authenticated
    client.cookies.clear()
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert providers.audit_sink.events[-1]["action"] == "auth.logout"
    assert providers.audit_sink.events[-1]["status"] == "effect_applied"


def test_unavailable_audit_does_not_prevent_revocation(client, providers, monkeypatch):
    login_as(client, "admin@example.com")
    token = client.cookies.get(providers.settings.session_cookie_name)
    backing = providers.identity
    providers.identity = _facade(backing)
    client.app.state.providers.identity = providers.identity
    calls = []
    original = backing._sessions.delete

    def delete(value):
        calls.append(value)
        original(value)

    monkeypatch.setattr(backing._sessions, "delete", delete)
    monkeypatch.setattr(providers.audit_sink, "emit", lambda _event: False)
    failed = client.post("/api/v1/auth/logout")
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "result_indeterminate"
    # Revocation is the security effect; it must not wait for the audit sink.
    assert calls == [token]
    assert "set-cookie" in failed.headers
    assert not providers.identity.validate_token(token).authenticated


def test_effect_audit_failure_is_indeterminate_after_revocation(client, providers, monkeypatch):
    login_as(client, "admin@example.com")
    token = client.cookies.get(providers.settings.session_cookie_name)
    backing = providers.identity
    providers.identity = _facade(backing)
    client.app.state.providers.identity = providers.identity
    original_emit = providers.audit_sink.emit

    def fail_effect(event):
        if event.get("status") == "effect_applied":
            return False
        return original_emit(event)

    monkeypatch.setattr(providers.audit_sink, "emit", fail_effect)
    failed = client.post("/api/v1/auth/logout")
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "result_indeterminate"
    assert "set-cookie" in failed.headers
    assert not providers.identity.validate_token(token).authenticated
    assert not any(event.get("status") == "completed" for event in providers.audit_sink.events)

    monkeypatch.setattr(providers.audit_sink, "emit", original_emit)
    retried = client.post("/api/v1/auth/logout")
    assert retried.status_code == 200
    assert retried.json() == {"status": "signed_out"}
    # Cleanup cannot fabricate a terminal completion of the earlier failed write.
    assert not any(event.get("status") == "completed" for event in providers.audit_sink.events)


def test_logout_without_token_is_idempotent(client, providers):
    for _ in range(2):
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 200
        assert response.json() == {"status": "signed_out"}
    events = [event for event in providers.audit_sink.events if event["action"] == "auth.logout"]
    # Explicit human cleanup-only policy: no authenticated backend mutation,
    # hence no fabricated tenant-scoped requested/completed audit pair.
    assert events == []


@pytest.mark.parametrize("asynchronous_port", ["emit", "health"])
def test_unsupported_async_audit_never_manufactures_success(client, providers, monkeypatch, recwarn, asynchronous_port):
    login_as(client, "admin@example.com")
    token = client.cookies.get(providers.settings.session_cookie_name)
    events, revocations = [], []

    class Sink:
        def health_check(self):
            return True

        def emit(self, event):
            events.append(event)
            return True

    async def emit(event):
        events.append(event)
        return True

    async def health():
        return True

    sink = Sink()
    setattr(sink, "emit" if asynchronous_port == "emit" else "health_check", emit if asynchronous_port == "emit" else health)
    client.app.state.providers.audit_sink = sink
    identity = client.app.state.providers.identity
    original = identity.logout

    def logout(value):
        revocations.append(value)
        return original(value)

    monkeypatch.setattr(identity, "logout", logout)
    failed = client.post("/api/v1/auth/logout")
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "result_indeterminate"
    assert "set-cookie" in failed.headers
    assert not identity.validate_token(token).authenticated
    assert revocations == [token]
    gc.collect()
    assert not [warning for warning in recwarn if issubclass(warning.category, RuntimeWarning)]


def test_native_tenant_audit_failure_retry_is_confirmed_cleanup_not_another_revocation(client, providers, monkeypatch):
    from apps.api.tests.test_postgres_audit import Connection
    from services.postgres_audit import PostgresAuditSink

    login_as(client, "admin@example.com")
    token = client.cookies.get(providers.settings.session_cookie_name)
    connections = []

    def factory():
        number = len(connections) + 1
        steps = [("INSERT INTO rick_audit_events", [])] if number == 2 else [("SELECT 1", [{"alive": 1}])]
        connection = Connection(steps)
        connections.append(connection)
        return connection

    class Sink(PostgresAuditSink):
        def emit(self, event):
            written = super().emit(event)
            if event["status"] == "effect_applied":
                return False  # actual revoke already succeeded; audit remains unconfirmed
            return written

    sink = Sink(factory)
    client.app.state.providers.audit_sink = sink
    identity = client.app.state.providers.identity
    revocations = []
    original = identity.logout

    def revoke(value):
        revocations.append(value)
        return original(value)

    monkeypatch.setattr(identity, "logout", revoke)
    failed = client.post("/api/v1/auth/logout")
    assert failed.status_code == 503 and "set-cookie" in failed.headers
    assert not identity.validate_token(token).authenticated
    assert len(revocations) == 1
    assert connections[1].commits == 1
    # This is the real native tenant validator/SQL writer, not a permissive sink.
    params = connections[1].cursor_instance.queries[0][1]
    assert params[1] == "default" and '"effect_applied"' in params[-1]
    prior_connections = len(connections)
    retry = client.post("/api/v1/auth/logout")
    assert retry.status_code == 200
    assert retry.json() == {"status": "signed_out"}
    assert "set-cookie" in retry.headers
    assert len(revocations) == 1  # no new backend mutation and no invented audit completion
    assert len(connections) == prior_connections


def test_native_audit_anonymous_cleanup_has_no_fabricated_tenant_or_revocation(client, monkeypatch):
    from services.postgres_audit import PostgresAuditSink
    identity = client.app.state.providers.identity

    def forbidden(*args, **kwargs):
        raise AssertionError("confirmed anonymous cleanup must not mutate identity or invent audit tenant")

    monkeypatch.setattr(identity, "logout", forbidden)
    client.app.state.providers.audit_sink = PostgresAuditSink(forbidden)
    assert client.post("/api/v1/auth/logout").status_code == 200


def test_malformed_authenticated_scope_cannot_be_relabelled_confirmed_signed_out(client, monkeypatch):
    from models import SessionSnapshot
    identity = client.app.state.providers.identity
    client.cookies.set(client.app.state.providers.settings.session_cookie_name, "synthetic-opaque-token")
    monkeypatch.setattr(identity, "validate_token", lambda token: SessionSnapshot(authenticated=True, tenant_id=None))
    result = client.post("/api/v1/auth/logout")
    assert result.status_code == 503
    assert "set-cookie" not in result.headers


def test_cleanup_revalidation_unavailable_is_not_confirmed(client, monkeypatch):
    from core.errors import ApiError
    from models import SessionSnapshot
    identity = client.app.state.providers.identity
    client.cookies.set(client.app.state.providers.settings.session_cookie_name, "synthetic-opaque-token")
    calls = []

    def validate(token):
        calls.append(token)
        if len(calls) == 1:
            return SessionSnapshot(authenticated=False, tenant_id=None)
        raise ApiError("provider_unavailable")

    monkeypatch.setattr(identity, "validate_token", validate)
    result = client.post("/api/v1/auth/logout")
    assert result.status_code == 503
    assert "set-cookie" not in result.headers
    assert len(calls) == 2


class _OperationRecorder:
    def __init__(self):
        self.begun = []
        self.effects = []
        self.acked = []

    def begin(self, **kwargs):
        self.begun.append(kwargs)

    def mark_effect(self, operation_id, **kwargs):
        self.effects.append((operation_id, kwargs))
        return True

    def acknowledge(self, operation_id):
        self.acked.append(operation_id)
        return True

    def fail(self, operation_id, code):
        return True


def test_logout_writes_durable_operation_and_acknowledges(client, providers):
    from apps.api.tests.support import login_as
    login_as(client, "admin@example.com")
    operations = _OperationRecorder()
    providers.audit_operations = client.app.state.providers.audit_operations = operations
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "signed_out"}
    assert operations.begun and operations.begun[0]["action"] == "auth.logout"
    assert operations.effects and operations.acked
    assert operations.acked[0] == operations.effects[0][0]


def test_logout_effect_projection_failure_keeps_operation_open(client, providers, monkeypatch):
    from apps.api.tests.support import login_as
    login_as(client, "admin@example.com")
    operations = _OperationRecorder()
    providers.audit_operations = client.app.state.providers.audit_operations = operations
    monkeypatch.setattr(providers.audit_sink, "emit", lambda _event: False)
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "result_indeterminate"
    assert operations.effects and operations.acked == []
