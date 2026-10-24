"""Native facade session-read outages are not confirmed anonymous sessions."""
from __future__ import annotations

import pytest

from apps.api.tests.support import login_as
from rick_identity import PostgresIdentityError
from services.postgres_identity import PostgresIdentityProvider


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
@pytest.mark.parametrize("path,method", [("/api/v1/auth/logout", "post"), ("/api/v1/auth/me", "get")])
def test_native_session_read_failure_is_unavailable_not_signed_out(client, providers, monkeypatch, transport, path, method):
    login_as(client, "admin@example.com")
    token = client.cookies.get(providers.settings.session_cookie_name)
    backing = providers.identity
    facade = PostgresIdentityProvider(lambda: None)
    facade._provider = backing._provider
    client.app.state.providers.identity = facade
    original_get = backing._sessions.get
    revocations = []
    original_logout = facade.logout

    def unavailable(*args, **kwargs):
        error = PostgresIdentityError("identity_unavailable")
        error.args = ("synthetic-private-dsn",)
        raise error

    def logout(value):
        revocations.append(value)
        return original_logout(value)

    monkeypatch.setattr(backing._sessions, "get", unavailable)
    monkeypatch.setattr(facade, "logout", logout)
    headers = {}
    if transport == "bearer":
        client.cookies.clear()
        headers["Authorization"] = f"Bearer {token}"
    failed = getattr(client, method)(path, headers=headers)
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "provider_unavailable"
    assert "set-cookie" not in failed.headers
    assert "signed_out" not in failed.text
    assert "synthetic-private-dsn" not in failed.text and token not in failed.text
    assert revocations == []
    if transport == "cookie":
        assert client.cookies.get(providers.settings.session_cookie_name) == token
    monkeypatch.setattr(backing._sessions, "get", original_get)
    assert facade.validate_token(token).authenticated
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert not facade.validate_token(token).authenticated


@pytest.mark.parametrize("tenant", [None, "", "   "])
def test_native_malformed_authenticated_scope_is_not_confirmed_absence(client, providers, monkeypatch, tenant):
    client.cookies.set(providers.settings.session_cookie_name, "synthetic-opaque-token")
    facade = PostgresIdentityProvider(lambda: None)
    facade._provider = providers.identity._provider
    monkeypatch.setattr(facade._provider, "validate_session", lambda token: {"authenticated": True, "tenant_id": tenant})
    client.app.state.providers.identity = facade
    result = client.post("/api/v1/auth/logout")
    assert result.status_code == 503
    assert "set-cookie" not in result.headers
    assert "signed_out" not in result.text


@pytest.mark.parametrize("adapter", ["memory", "raw"])
@pytest.mark.parametrize("tenant", [None, "", "   "])
@pytest.mark.parametrize("path,method", [("/api/v1/auth/logout", "post"), ("/api/v1/auth/me", "get")])
def test_all_authenticated_malformed_scopes_are_unavailable(client, providers, monkeypatch, adapter, tenant, path, method):
    from models import SessionSnapshot
    login_as(client, "admin@example.com")
    token = client.cookies.get(providers.settings.session_cookie_name)
    identity = client.app.state.providers.identity
    if adapter == "memory":
        monkeypatch.setattr(identity._provider, "validate_session", lambda value: {"authenticated": True, "tenant_id": tenant})
    else:
        monkeypatch.setattr(identity, "validate_token", lambda value: SessionSnapshot(authenticated=True, tenant_id=tenant))
    result = getattr(client, method)(path)
    assert result.status_code == 503
    assert "set-cookie" not in result.headers and "signed_out" not in result.text
    assert client.cookies.get(providers.settings.session_cookie_name) == token
