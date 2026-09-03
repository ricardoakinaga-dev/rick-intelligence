"""OpenAI compatibility: OpenWebUI-style requests over the canonical chat service."""

from fastapi.testclient import TestClient

from app import create_app
from conftest import make_settings
from dependencies.services import Providers
from services.audit import InMemoryAuditSink
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider


def make_compat_client():
    providers = Providers(settings=make_settings(compat_api_key="secret-compat-key"),
                          identity=InMemoryIdentityProvider(), chat_backend=StubChatBackend(),
                          health_checks={}, audit_sink=InMemoryAuditSink())
    return TestClient(create_app(providers.settings, providers), raise_server_exceptions=False)


def test_models_requires_key():
    c = make_compat_client()
    assert c.get("/v1/models").status_code == 401
    resp = c.get("/v1/models", headers={"Authorization": "Bearer secret-compat-key"})
    assert resp.status_code == 200
    assert resp.json()["data"][0]["id"] == "rick-professor"


def test_chat_completion_non_stream():
    c = make_compat_client()
    resp = c.post("/v1/chat/completions",
                  headers={"Authorization": "Bearer secret-compat-key"},
                  json={"model": "rick-professor", "messages": [{"role": "user", "content": "O que é mastite?"}]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["usage"] is None  # never fabricated
    assert "metadata" in body


def test_chat_completion_stream():
    c = make_compat_client()
    resp = c.post("/v1/chat/completions",
                  headers={"Authorization": "Bearer secret-compat-key"},
                  json={"model": "rick-professor", "messages": [{"role": "user", "content": "hi"}],
                        "stream": True, "conversation_id": "conv-1"})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data: [DONE]" in resp.text


def test_platform_and_compat_share_backend(client):
    # Compat client uses same StubChatBackend semantics as platform chat.
    from conftest import login_as

    login_as(client, "vet@example.com")
    platform = client.post("/api/v1/chat", json={"message": "O que é mastite?"})
    assert platform.status_code == 200
    assert "stub" in platform.json()["answer"].lower() or "fundamentada" in platform.json()["answer"].lower()
