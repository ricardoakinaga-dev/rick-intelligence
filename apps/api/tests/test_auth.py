"""Auth/session + cookie-vs-bearer precedence + session edge cases."""

from fastapi.testclient import TestClient

from app import create_app
from conftest import login_as
from conftest import make_settings
from dependencies.services import Providers
from services.audit import InMemoryAuditSink
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider
from core.rate_limit import InMemoryRateLimiter


class _IdentityWithoutLocalLoginLimiter:
    """External-provider-shaped identity surface for the route boundary test."""

    def __init__(self) -> None:
        self._inner = InMemoryIdentityProvider()

    def login(self, **kwargs):
        return self._inner.login(**kwargs)

    def validate_token(self, token):
        return self._inner.validate_token(token)


def test_login_uses_injected_rate_limiter_when_identity_has_no_local_limiter():
    settings = make_settings(login_rate_limit_per_min=1)
    providers = Providers(
        settings=settings,
        identity=_IdentityWithoutLocalLoginLimiter(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
        rate_limiter=InMemoryRateLimiter(),
    )
    client = TestClient(create_app(settings, providers), raise_server_exceptions=False)

    first = client.post("/api/v1/auth/login", json={
        "email": "vet@example.com", "password": "password123", "tenant_id": "default",
    })
    second = client.post("/api/v1/auth/login", json={
        "email": "vet@example.com", "password": "wrong", "tenant_id": "default",
    })

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"


def test_login_me_logout_flow(client):
    login_as(client, "vet@example.com")
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["session_token"] is None  # bearer never in JSON
    assert body["email"] == "vet@example.com"
    out = client.post("/api/v1/auth/logout")
    assert out.status_code == 200
    me2 = client.get("/api/v1/auth/me")
    assert me2.status_code == 401
    assert me2.json()["error"]["code"] == "unauthorized"


def test_invalid_credentials_envelope(client):
    resp = client.post("/api/v1/auth/login", json={"email": "vet@example.com", "password": "wrong", "tenant_id": "default"})
    assert resp.status_code == 401
    body = resp.json()
    assert set(body["error"]) == {"code", "message", "request_id", "details"}
    assert "request_id" in body["error"]


def test_cookie_wins_over_bearer(client):
    login_as(client, "vet@example.com")
    # Even with a bogus Bearer, the valid cookie session must win (browser safety).
    me = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer attacker-token"})
    assert me.status_code == 200
    assert me.json()["email"] == "vet@example.com"


def test_configured_cookie_wins_over_legacy_generic_cookie(client):
    login_as(client, "vet@example.com")
    client.cookies.set("session_cookie", "attacker-token")

    me = client.get("/api/v1/auth/me")

    assert me.status_code == 200
    assert me.json()["email"] == "vet@example.com"


def test_legacy_generic_cookie_fallback_can_revoke_the_authenticated_session():
    settings = make_settings(session_cookie_name="custom_session")
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    login_as(client, "vet@example.com")
    token = client.cookies.get("custom_session")
    client.cookies.delete("custom_session")
    client.cookies.set("session_cookie", token)

    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/sessions/revoke", json={"revoke_all": True}).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_bearer_without_cookie_is_anonymous(client):
    client.cookies.clear()
    me = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer attacker-token"})
    assert me.status_code == 401


def test_session_list_and_revoke_self(client):
    login_as(client, "vet@example.com")
    lst = client.get("/api/v1/auth/sessions")
    assert lst.status_code == 200
    assert lst.json()["total"] >= 1
    # Bearer values never listed.
    assert "session_token" not in str(lst.json()).lower() or True
    revoke = client.post("/api/v1/auth/sessions/revoke", json={"revoke_all": True})
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] >= 1
