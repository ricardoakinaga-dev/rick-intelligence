"""REC M0: effective permissions and safe configuration/composition facts."""

import pytest
from fastapi.testclient import TestClient

from app import create_app
from core.config import ApiSettings
from conftest import login_as, make_settings
from routes.auth import _public_session
from rick_contracts.security import SessionSnapshot


@pytest.mark.parametrize("canonical,legacy,value,attribute,expected", [
    ("LLM_PROVIDER", "RICK_PROVIDER", "openai-compatible", "provider_kind", "openai_compatible"),
    ("LLM_BASE_URL", "OPENAI_BASE_URL", "https://synthetic.invalid/v1", "provider_base_url", "https://synthetic.invalid/v1"),
    ("LLM_API_KEY", "EXTERNAL_CHAT_API_KEY", "synthetic-secret", "external_chat_api_key", "synthetic-secret"),
    ("LLM_MODEL", "OPENAI_CHAT_MODEL", "synthetic-model", "provider_chat_model", "synthetic-model"),
    ("EMBEDDING_MODEL", "OPENAI_EMBEDDING_MODEL", "synthetic-vector", "provider_embedding_model", "synthetic-vector"),
    ("EMBEDDING_DIMENSION", "OPENAI_EMBEDDING_DIMENSIONS", "128", "provider_embedding_dimensions", 128),
])
def test_canonical_and_legacy_config(monkeypatch, canonical, legacy, value, attribute, expected):
    monkeypatch.delenv(canonical, raising=False)
    monkeypatch.setenv(legacy, value)
    assert getattr(ApiSettings(), attribute) == expected
    monkeypatch.setenv(canonical, value)
    assert getattr(ApiSettings(), attribute) == expected
    monkeypatch.setenv(legacy, "different-secret")
    with pytest.raises(ValueError) as error:
        ApiSettings()
    assert "different-secret" not in str(error.value)
    assert value not in str(error.value)
    monkeypatch.setenv(legacy, "")
    assert getattr(ApiSettings(), attribute) == expected


def test_invalid_integer_does_not_echo_value(monkeypatch):
    monkeypatch.setenv("API_MAX_JSON_BYTES", "synthetic-secret")
    with pytest.raises(ValueError, match="Invalid integer") as error:
        ApiSettings()
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("grants", [[], ["chat.query"], ["*"]])
def test_public_snapshot_does_not_restore_role_defaults(grants):
    snapshot = SessionSnapshot(authenticated=True, role="PLATFORM_ADMIN", permissions=grants)
    assert _public_session(snapshot)["permissions"] == grants


@pytest.mark.parametrize("email,documents,admin", [
    ("vet@example.com", False, False), ("km@example.com", True, True),
    ("admin@example.com", True, True),
])
def test_login_and_refresh_project_identical_permissions(client, email, documents, admin):
    initial = login_as(client, email).json()
    grants = initial["permissions"]
    assert ("*" in grants or "documents.read" in grants) is documents
    assert ("*" in grants or "audit.read" in grants) is admin
    for route in ("/api/v1/auth/me", "/api/v1/session"):
        assert client.get(route).json()["permissions"] == grants


def test_injected_runtime_is_not_misrepresented_or_leaked(client):
    login_as(client, "vet@example.com")
    assert client.get("/api/v1/admin/system").status_code == 403
    client.cookies.clear()
    login_as(client, "admin@example.com")
    data = client.get("/api/v1/admin/system").json()["runtime"]
    assert data["composition"] == "injected"
    assert data["active_chat_provider"] == "externally_managed"
    assert data["production_verified"] is False


@pytest.mark.parametrize("mode,provider", [("stub", "not_used"), ("professor", "deterministic")])
def test_factory_runtime_diagnostics(mode, provider, monkeypatch):
    monkeypatch.setenv("RICK_API_ROOT_KNOWLEDGE", "1")
    monkeypatch.setenv("RICK_API_ROOT_RETRIEVAL", "1")
    settings = make_settings(chat_backend_mode=mode, provider_kind="deterministic",
                             external_chat_api_key="synthetic-secret", provider_base_url="https://synthetic.invalid/v1")
    with TestClient(create_app(settings)) as client:
        login_as(client, "admin@example.com")
        response = client.get("/api/v1/admin/system")
        assert "synthetic-secret" not in response.text
        assert "synthetic.invalid" not in response.text
        assert response.json()["runtime"]["active_chat_provider"] == provider
        assert response.json()["runtime"]["embedding"] == "deterministic_local"
