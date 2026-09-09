"""Focused CSRF/origin and root-chat rate-limit coverage."""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from app import create_app
from conftest import login_as, make_settings
from dependencies.services import Providers
from models import SessionSnapshot
from services.audit import InMemoryAuditSink
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider


def _client(**overrides) -> TestClient:
    settings = make_settings(**overrides)
    providers = Providers(
        settings=settings,
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
    )
    return TestClient(create_app(settings, providers), raise_server_exceptions=False)


class _ProductionIdentity:
    production_safe = True

    def validate_token(self, token):
        if token not in {"cookie-token", "bearer-token"}:
            return SessionSnapshot(authenticated=False, session_state="anonymous")
        return SessionSnapshot(
            authenticated=True,
            session_state="active",
            user_id="security-test-user",
            email="security@example.com",
            role="VETERINARIAN",
            canonical_role="VETERINARIAN",
            permissions=["chat.query"],
            workspace_id="default",
            tenant_id="default",
            session_id="security-session",
            allowed_collection_ids=["rag_phase0"],
        )

    def logout(self, token):
        return None


class _ProductionDependency:
    def readiness_check(self):
        return True

    def health_check(self):
        return True


class _ProductionRateLimiter(_ProductionDependency):
    production_safe = True
    backend_kind = "redis"

    async def allow(self, *args, **kwargs):
        return True


class _ProductionLease(_ProductionDependency):
    production_safe = True
    backend_kind = "redis"

    async def acquire_owned(self, *args, **kwargs):
        return True

    async def renew_owned(self, *args, **kwargs):
        return True

    async def release_owned(self, *args, **kwargs):
        return True


def _production_client(**overrides) -> TestClient:
    values = {
        "environment": "production",
        "identity_mode": "production",
        "chat_backend_mode": "legacy",
        "use_legacy_adapters": True,
        "session_cookie_secure": True,
        "cors_allowed_origins": ("https://app.example",),
    }
    values.update(overrides)
    settings = make_settings(**values)
    providers = Providers(
        settings=settings,
        identity=_ProductionIdentity(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
        chat_history=_ProductionDependency(),
        knowledge=_ProductionDependency(),
        vector_store=_ProductionDependency(),
        retrieval=_ProductionDependency(),
        ingestion=_ProductionDependency(),
        worker=_ProductionDependency(),
        job_journal=_ProductionDependency(),
        queue=_ProductionDependency(),
        object_store=_ProductionDependency(),
        rate_limiter=_ProductionRateLimiter(),
        lease=_ProductionLease(),
    )
    return TestClient(create_app(settings, providers), base_url="https://testserver", raise_server_exceptions=False)


def test_local_cookie_mutation_without_origin_keeps_existing_test_clients_compatible():
    client = _client()
    login_as(client, "vet@example.com")

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"status": "signed_out"}


def test_disallowed_origin_is_rejected_even_for_local_cookie_clients():
    client = _client()
    login_as(client, "vet@example.com")

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_production_cookie_mutation_requires_allowed_origin_or_configured_token():
    client = _production_client()
    client.cookies.set("rick_session", "cookie-token")

    denied = client.post("/api/v1/auth/logout")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"
    assert set(denied.json()["error"]) == {"code", "message", "request_id", "details"}

    allowed = client.post("/api/v1/auth/logout", headers={"Origin": "https://app.example"})
    assert allowed.status_code == 200


def test_production_bearer_mutation_and_get_health_are_not_cookie_csrf_blocked():
    client = _production_client()

    health = client.get("/health/live")
    assert health.status_code == 200

    logout = client.post("/api/v1/auth/logout", headers={"Authorization": "Bearer bearer-token"})
    assert logout.status_code == 200


def test_production_csrf_token_can_authorize_without_origin():
    client = _production_client(csrf_token="configured-csrf-token")
    client.cookies.set("rick_session", "cookie-token")

    response = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": "configured-csrf-token"},
    )

    assert response.status_code == 200


def test_production_referer_origin_is_checked_when_origin_is_absent():
    client = _production_client()
    client.cookies.set("rick_session", "cookie-token")

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Referer": "https://app.example/account/settings"},
    )

    assert response.status_code == 200


def test_production_legacy_generic_cookie_still_requires_csrf_proof():
    client = _production_client(session_cookie_name="custom_session")
    client.cookies.set("session_cookie", "cookie-token")

    denied = client.post("/api/v1/auth/logout")
    assert denied.status_code == 403

    allowed = client.post("/api/v1/auth/logout", headers={"Origin": "https://app.example"})
    assert allowed.status_code == 200


def test_compat_api_key_route_is_not_reclassified_as_cookie_auth():
    client = _production_client(compat_api_key="compat-secret")
    client.cookies.set("rick_session", "cookie-token")

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer compat-secret"},
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200, response.text


def test_root_chat_uses_configured_limit_and_safe_429_envelope():
    client = _client(chat_rate_limit_per_min=1)
    login_as(client, "vet@example.com")

    first = client.post("/api/v1/chat", json={"message": "hello"})
    second = client.post("/api/v1/chat", json={"message": "hello again"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"
    assert second.json()["error"]["code"] == "rate_limited"
    assert "hello" not in second.text


def test_chat_rate_limit_configuration_must_be_positive():
    settings = make_settings(chat_rate_limit_per_min=0)

    try:
        settings.validate()
    except ValueError as exc:
        assert "CHAT_RATE_LIMIT_PER_MIN" in str(exc)
    else:
        raise AssertionError("zero chat rate limit must fail closed")


def test_recovery_entry_points_share_a_bounded_neutral_rate_limit():
    settings = make_settings(recovery_rate_limit_per_min=2)
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    payload = {"email": "unknown@example.com", "tenant_id": "default"}

    first = client.post("/api/v1/auth/recovery", json=payload)
    second = client.post("/api/v1/auth/request-password-reset", json=payload)
    third = client.post("/api/v1/auth/recovery", json=payload)

    assert first.status_code == 200 and first.json() == {"status": "queued"}
    assert second.status_code == 200 and second.json() == {"status": "queued"}
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "60"
    assert third.json()["error"]["code"] == "rate_limited"
    assert "unknown@example.com" not in third.text


def test_recovery_uses_injected_delivery_port_without_returning_the_token():
    calls = []

    class Delivery:
        def deliver_password_reset(self, *, email, tenant_id, token):
            calls.append({"email": email, "tenant_id": tenant_id, "token": token})
            return True

    settings = make_settings()
    providers = Providers(
        settings=settings,
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
        password_reset_delivery=Delivery(),
    )
    client = TestClient(create_app(settings, providers), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/auth/recovery",
        json={"email": "vet@example.com", "tenant_id": "default"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "queued"}
    assert len(calls) == 1
    assert calls[0]["email"] == "vet@example.com"
    assert calls[0]["tenant_id"] == "default"
    assert calls[0]["token"] not in response.text


def test_recovery_rate_limit_configuration_must_be_positive():
    settings = make_settings(recovery_rate_limit_per_min=0)

    try:
        settings.validate()
    except ValueError as exc:
        assert "RECOVERY_RATE_LIMIT_PER_MIN" in str(exc)
    else:
        raise AssertionError("zero recovery rate limit must fail closed")


def test_authenticated_snapshot_without_explicit_tenant_fails_closed():
    class MalformedIdentity:
        def validate_token(self, token):
            return SessionSnapshot(
                authenticated=True,
                session_state="active",
                user_id="malformed-user",
                role="VETERINARIAN",
                canonical_role="VETERINARIAN",
                permissions=["chat.query"],
                workspace_id="default",
                session_id="malformed-session",
            )

    settings = make_settings()
    providers = Providers(
        settings=settings,
        identity=MalformedIdentity(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
    )
    client = TestClient(create_app(settings, providers), raise_server_exceptions=False)
    client.cookies.set(settings.session_cookie_name, "malformed-token")

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401, response.text


def test_knowledge_service_rejects_a_legacy_unscoped_store_without_retrying() -> None:
    from services.knowledge_service import KnowledgeApplicationService

    calls: list[tuple[str, str | None]] = []

    class LegacyStore:
        def list_documents(self, workspace_id, collection_id=None):
            calls.append((workspace_id, collection_id))
            return []

    service = KnowledgeApplicationService(LegacyStore())

    assert service.list_documents(
        workspace_id="workspace-a",
        tenant_id="tenant-a",
        allowed=["collection-a"],
    ) == []
    assert calls == []


def test_knowledge_service_requires_explicit_tenant_and_rejects_tenantless_records() -> None:
    from services.knowledge_service import KnowledgeApplicationService

    class TenantlessStore:
        def list_documents(self, **_kwargs):
            return [{
                "document_id": "tenantless",
                "title": "must stay hidden",
                "collection_id": "collection-a",
                "workspace_id": "workspace-a",
                "status": "published",
            }]

    service = KnowledgeApplicationService(TenantlessStore())
    with pytest.raises(TypeError):
        service.list_documents(workspace_id="workspace-a", allowed=["collection-a"])
    with pytest.raises(ValueError, match="tenant_id is required"):
        service.list_documents(
            workspace_id="workspace-a",
            allowed=["collection-a"],
            tenant_id=None,
        )
    assert service.list_documents(
        workspace_id="workspace-a",
        allowed=["collection-a"],
        tenant_id="default",
    ) == []


def test_demo_knowledge_fixtures_bind_tenant_explicitly() -> None:
    from copy import deepcopy

    from services.knowledge_service import _DEMO_DOCS, _DEMO_SEED, _DEMO_TEXT, seed_demo_points

    assert all(item.tenant_id == "default" for item in (*_DEMO_SEED, *_DEMO_DOCS))

    class Store:
        def __init__(self) -> None:
            self.chunks = []

        def get_document(self, document_id):
            assert document_id == "doc-stub-1"
            return deepcopy(_DEMO_DOCS[0])

        def replace_document_chunks(self, document_id, chunks):
            assert document_id == "doc-stub-1"
            self.chunks = chunks

    class Embeddings:
        model = "test-model"

        def embed(self, texts):
            assert texts == [_DEMO_TEXT]
            return [[0.0, 1.0]]

    store = Store()
    points = seed_demo_points(store, Embeddings())

    assert store.chunks[0].tenant_id == "default"
    assert points[0]["payload"]["tenant_id"] == "default"
