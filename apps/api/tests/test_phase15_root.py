"""Root Phase 1.5 vertical-slice checks through the public API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _package in ("knowledge", "ingestion", "retrieval", "providers", "locking", "professor"):
    _source = str(ROOT / "packages" / _package / "src")
    if _source not in sys.path:
        sys.path.insert(0, _source)

from fastapi.testclient import TestClient

from app import create_app
from core.config import ApiSettings


DEMO_QUERY = (
    "Mastite bovina exige higiene rigorosa na ordenha, isolamento do animal "
    "afetado e avaliação veterinária antes da escolha do tratamento."
)


def _settings(**overrides):
    values = {
        "cors_allowed_origins": ("http://localhost:3000",),
        "session_cookie_secure": False,
        "environment": "local",
        "chat_backend_mode": "professor",
        "compat_api_key": "compat-secret",
    }
    values.update(overrides)
    return ApiSettings(**values)


def _client(**overrides) -> TestClient:
    settings = _settings(**overrides)
    return TestClient(create_app(settings), raise_server_exceptions=False)


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "vet@example.com", "password": "password123", "tenant_id": "default"},
    )
    assert response.status_code == 200, response.text


def test_authenticated_root_chat_reaches_professor_and_returns_provenance() -> None:
    client = _client()
    _login(client)

    response = client.post("/api/v1/chat", json={"message": DEMO_QUERY})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["backend"] == "professor"
    assert body["metadata"]["evidence_status"] == "APPROVED_EVIDENCE"
    assert body["citations"] == [
        {
            "document_id": "doc-stub-1",
            "chunk_id": "chunk-stub-1",
            "title": "Stub document",
            "collection_id": "rag_phase0",
            "page_start": 1,
            "page_end": 1,
            "checksum": "b614197d056058ebd8496e05c490f71b0778caa8015538aafaa52123de785ca5",
        }
    ]
    assert "stub" not in body["answer"].lower()


def test_root_chat_cannot_widen_collection_scope() -> None:
    client = _client()
    _login(client)

    response = client.post(
        "/api/v1/chat",
        json={"message": DEMO_QUERY, "collection_id": "vet-library"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_compatibility_uses_same_root_backend_and_finite_server_scope() -> None:
    client = _client()

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer compat-secret"},
        json={"messages": [{"role": "user", "content": DEMO_QUERY}]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["backend"] == "professor"
    assert body["metadata"]["workspace_id"] == "default"
    assert body["usage"] is None


def test_professor_provider_failure_maps_to_safe_public_error() -> None:
    client = _client()
    _login(client)

    class FailingProvider:
        async def chat_completion(self, *, messages, correlation_id):
            raise RuntimeError("provider secret and response body must not escape")

    backend = client.app.state.providers.chat_backend
    backend.provider.provider = FailingProvider()
    response = client.post("/api/v1/chat", json={"message": DEMO_QUERY})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert "secret" not in response.text.lower()
    assert "response body" not in response.text.lower()

    stream = client.post("/api/v1/chat", json={"message": DEMO_QUERY, "stream": True})
    assert stream.status_code == 200
    assert '"type": "error"' in stream.text or '"type":"error"' in stream.text
    assert "provider_unavailable" in stream.text
    assert "[DONE]" in stream.text


def test_production_rejects_stub_and_wildcard_compat_scope() -> None:
    with pytest.raises(ValueError, match="stub"):
        create_app(
            ApiSettings(
                cors_allowed_origins=("https://app.example",),
                session_cookie_secure=True,
                environment="production",
                chat_backend_mode="stub",
            )
        )
    with pytest.raises(ValueError, match="wildcard"):
        create_app(_settings(compat_allowed_collection_ids=("*",)))


def test_security_configuration_fails_closed_for_production_and_proxy_inputs() -> None:
    with pytest.raises(ValueError, match="IDENTITY_MODE"):
        ApiSettings(
            cors_allowed_origins=("https://app.example",),
            session_cookie_secure=True,
            environment="production",
            identity_mode="dev",
            chat_backend_mode="professor",
        ).validate()

    with pytest.raises(ValueError, match="secure session"):
        ApiSettings(
            cors_allowed_origins=("https://app.example",),
            session_cookie_secure=False,
            environment="production",
            identity_mode="production",
            chat_backend_mode="professor",
        ).validate()

    with pytest.raises(ValueError, match="SameSite=None"):
        _settings(session_cookie_samesite="none", session_cookie_secure=False).validate()

    with pytest.raises(ValueError, match="TRUSTED_PROXIES"):
        _settings(trusted_proxies=("not-an-ip",)).validate()


def test_production_aliases_are_normalized_and_require_external_identity() -> None:
    settings = ApiSettings(
        cors_allowed_origins=("https://app.example",),
        session_cookie_secure=True,
        environment="prod",
        identity_mode="production",
        chat_backend_mode="legacy",
        use_legacy_adapters=True,
    )
    assert settings.environment == "production"
    with pytest.raises(RuntimeError, match="external identity"):
        create_app(settings)

    with pytest.raises(ValueError, match="RICK_ENV"):
        ApiSettings(environment="staging")


def test_explicit_legacy_mode_does_not_change_to_the_root_stub() -> None:
    client = _client(chat_backend_mode="legacy")
    assert type(client.app.state.providers.chat_backend).__name__ == "LegacyProfessorAdapter"
