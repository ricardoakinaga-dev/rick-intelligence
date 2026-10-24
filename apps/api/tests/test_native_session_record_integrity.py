"""Exercise actual canonical live session records, not mocked validation."""
from __future__ import annotations

import copy
import pytest
from apps.api.tests.support import login_as


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
@pytest.mark.parametrize("tenant", [None, "", "   "])
@pytest.mark.parametrize("path,method", [("/api/v1/auth/logout", "post"), ("/api/v1/auth/me", "get")])
def test_corrupt_live_native_record_is_unknown_not_absent(client, providers, transport, tenant, path, method):
    login_as(client, "admin@example.com")
    token = client.cookies.get(providers.settings.session_cookie_name)
    identity = client.app.state.providers.identity
    sessions = identity._sessions._sessions
    original = copy.deepcopy(sessions[token])
    sessions[token]["tenant_id"] = tenant
    headers = {}
    if transport == "bearer":
        client.cookies.clear()
        headers["Authorization"] = f"Bearer {token}"
    try:
        result = getattr(client, method)(path, headers=headers)
        assert result.status_code == 503
        assert "signed_out" not in result.text and "set-cookie" not in result.headers
        assert sessions[token].get("revoked_at") is None
    finally:
        sessions[token] = original
    assert identity.validate_token(token).authenticated
    assert client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert not identity.validate_token(token).authenticated


def test_native_postgres_corrupt_snapshot_is_not_a_missing_row():
    from apps.api.tests.test_postgres_audit import Connection
    from rick_identity import PostgresIdentityError, PostgresSessionStore
    connection = Connection([("FROM rick_sessions", [{"authorization_snapshot": "{malformed"}])])
    store = PostgresSessionStore(lambda: connection)
    with pytest.raises(PostgresIdentityError) as error:
        store.get("synthetic-opaque-token")
    assert error.value.code == "identity_unavailable"
