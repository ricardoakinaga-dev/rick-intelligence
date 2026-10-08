"""Auth/session + cookie-vs-bearer precedence + session edge cases."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import create_app
from conftest import login_as
from conftest import make_settings
from dependencies.services import Providers
from services.audit import InMemoryAuditSink
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider
from rick_identity import Pbkdf2Verifier
from core.rate_limit import InMemoryRateLimiter


@pytest.mark.parametrize("role", [None, "", "UNRECOGNIZED_ROLE"])
def test_live_authorization_refresh_rejects_missing_or_unknown_role(role):
    from services.authorization_service import refresh_context_from_user

    context = {
        "tenant_id": "tenant-a", "workspace_id": "workspace-a", "user_id": "user-a",
        "allowed_collection_ids": ["rag_phase0"], "permissions": ["chat.query"],
    }
    user = {
        "user_id": "user-a", "tenant_id": "tenant-a", "workspace_id": "workspace-a",
        "status": "active", "role": role, "authorized_collection_ids": ["rag_phase0"],
    }

    assert refresh_context_from_user(context, user) is None


def test_compatibility_service_revalidation_keeps_only_its_configured_scope():
    from services.authorization_service import make_authorization_revalidator

    refresh = make_authorization_revalidator(
        lambda *, context: context,
        compatibility_workspace_id="compat-workspace",
        compatibility_collection_ids=("collection-a",),
    )
    context = {
        "tenant_id": "default", "workspace_id": "compat-workspace",
        "user_id": "compat-service", "allowed_collection_ids": ["collection-a", "collection-b"],
        "permissions": ["chat.query", "sources.read"],
    }

    current = asyncio.run(refresh(context=context))
    assert current["allowed_collection_ids"] == ["collection-a"]
    assert current["permissions"] == ["chat.query", "sources.read"]
    assert asyncio.run(refresh(context={**context, "workspace_id": "foreign"})) is None
    assert asyncio.run(refresh(context={**context, "allowed_collection_ids": ["*"]})) is None


def test_live_platform_admin_workspace_refresh_uses_current_workspace_policy():
    from services.authorization_service import refresh_context_from_user

    context = {
        "tenant_id": "tenant-a", "workspace_id": "workspace-b", "user_id": "admin-a",
        "allowed_collection_ids": ["collection-a"], "permissions": ["chat.query"],
    }
    user = {
        "user_id": "admin-a", "tenant_id": "tenant-a", "workspace_id": "workspace-a",
        "status": "active", "role": "PLATFORM_ADMIN",
        "authorized_collection_ids": ["collection-a"],
    }

    refreshed = refresh_context_from_user(context, user)
    assert refreshed is not None
    assert refreshed["workspace_id"] == "workspace-b"
    assert refreshed["allowed_collection_ids"] == ["collection-a"]
    assert refresh_context_from_user(context, {**user, "role": "VETERINARIAN"}) is None
    assert refresh_context_from_user(context, {**user, "role": "KNOWLEDGE_MANAGER"}) is None


def test_in_memory_identity_refresh_uses_exact_workspace_and_fails_closed_without_it():
    members = [
        {
            "user_id": "user-a", "tenant_id": "tenant-a", "workspace_id": "workspace-a",
            "status": "active", "membership_status": "active", "role": "PLATFORM_ADMIN",
            "permission_overrides": {"add": [], "remove": []},
            "authorized_collection_ids": ["workspace-a-collection"],
        },
        {
            "user_id": "user-a", "tenant_id": "tenant-a", "workspace_id": "workspace-b",
            "status": "active", "membership_status": "active", "role": "VETERINARIAN",
            "permission_overrides": {"add": [], "remove": []},
            "authorized_collection_ids": ["workspace-b-collection"],
        },
    ]

    class WorkspaceUsers:
        def __init__(self):
            self.lookups = []

        def get_by_id_for_tenant(self, *_args):
            raise AssertionError("tenant-only membership lookup is not safe for refresh")

        def get_by_id_for_tenant_workspace(self, user_id, tenant_id, workspace_id):
            self.lookups.append((user_id, tenant_id, workspace_id))
            return next((
                member for member in members
                if (member["user_id"], member["tenant_id"], member["workspace_id"])
                == (user_id, tenant_id, workspace_id)
            ), None)

    identity = InMemoryIdentityProvider(mode="test")
    users = WorkspaceUsers()
    identity._users = users
    context = {
        "user_id": "user-a", "tenant_id": "tenant-a", "workspace_id": "workspace-b",
        "allowed_collection_ids": ["workspace-a-collection", "workspace-b-collection"],
        "permissions": ["chat.query", "cases.manage", "documents.read"],
    }

    refreshed = identity.refresh_authorization_context(context=context)

    assert refreshed is not None
    assert refreshed["allowed_collection_ids"] == ["workspace-b-collection"]
    assert "documents.read" not in refreshed["permissions"]
    assert users.lookups == [("user-a", "tenant-a", "workspace-b")]
    members[1]["membership_status"] = "disabled"
    assert identity.refresh_authorization_context(context=context) is None
    assert identity.refresh_authorization_context(
        context={key: value for key, value in context.items() if key != "workspace_id"}
    ) is None

    class MisScopedUsers:
        def get_by_id_for_tenant_workspace(self, *_args):
            return members[0]

    identity._users = MisScopedUsers()
    assert identity.refresh_authorization_context(context=context) is None

    class TenantOnlyUsers:
        def get_by_id_for_tenant(self, *_args):
            return members[0]

    identity._users = TenantOnlyUsers()
    assert identity.refresh_authorization_context(context=context) is None


class _IdentityWithoutLocalLoginLimiter:
    """External-provider-shaped identity surface for the route boundary test."""

    def __init__(self) -> None:
        self._inner = InMemoryIdentityProvider()

    def login(self, **kwargs):
        return self._inner.login(**kwargs)

    def validate_token(self, token):
        return self._inner.validate_token(token)


def test_demo_seed_uses_hash_with_non_plain_verifier():
    identity = InMemoryIdentityProvider(mode="test", verifier=Pbkdf2Verifier())
    admin = identity._users.get_by_id("admin")
    assert admin is not None
    assert "password_plain" not in admin
    assert admin["password_hash"] != "password123"
    assert identity.login(
        email="admin@example.com", password="password123", tenant_id="default",
        ip="127.0.0.1", user_agent="test",
    )


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
    body = lst.json()
    assert body["total"] == len(body["items"])
    assert all(set(item) == {"session_id", "user_id", "created_at", "revoked"} for item in body["items"])
    assert "session_token" not in str(body).lower()
    assert all(token not in lst.text for token in client.cookies.values())
    revoke = client.post("/api/v1/auth/sessions/revoke", json={"revoke_all": True})
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] >= 1


@pytest.mark.parametrize(
    "path",
    ["/api/v1/auth/recovery", "/api/v1/auth/request-password-reset"],
)
def test_password_reset_issuance_and_delivery_failures_keep_neutral_response(
    client, monkeypatch, caplog, path,
):
    class BrokenDelivery:
        def __init__(self):
            self.deliveries = []

        def deliver_password_reset(self, *, email, tenant_id, token):
            self.deliveries.append((email, tenant_id, token))
            raise RuntimeError("email=account@example.test token=secret-reset-token")

    delivery = BrokenDelivery()
    app_providers = client.app.state.providers
    app_providers.password_reset_delivery = delivery
    resolutions = {
        "account@example.test": "secret-reset-token",
        "ambiguous@example.test": None,
        "unknown@example.test": None,
    }

    def issue_password_reset(*, email, tenant_id):
        if email == "store-error@example.test":
            raise RuntimeError("email=store-error@example.test token=store-secret")
        return resolutions.get(email)

    monkeypatch.setattr(
        app_providers.identity,
        "issue_password_reset",
        issue_password_reset,
    )
    resolutions["store-error@example.test"] = None

    responses = [
        client.post(path, json={"email": email, "tenant_id": "tenant-a"})
        for email in (
            "account@example.test",
            "ambiguous@example.test",
            "unknown@example.test",
            "store-error@example.test",
        )
    ]

    assert [(response.status_code, response.json()) for response in responses] == [
        (200, {"status": "queued"}),
        (200, {"status": "queued"}),
        (200, {"status": "queued"}),
        (200, {"status": "queued"}),
    ]
    assert delivery.deliveries == [
        ("account@example.test", "tenant-a", "secret-reset-token"),
    ]
    assert "password reset delivery failed" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "account@example.test" not in caplog.text
    assert "secret-reset-token" not in caplog.text
    assert "password reset issuance failed" in caplog.text
    assert "store-error@example.test" not in caplog.text
    assert "store-secret" not in caplog.text
