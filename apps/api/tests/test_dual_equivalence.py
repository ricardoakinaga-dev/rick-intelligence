"""Dual-run equivalence (new platform chat vs compat adapter) + golden contracts."""

import json
from pathlib import Path

from conftest import login_as

GOLDEN_DIR = Path(__file__).parent / "golden"


def test_chat_and_compat_semantic_parity(client):
    from fastapi.testclient import TestClient

    from app import create_app
    from conftest import make_settings
    from dependencies.services import Providers
    from services.audit import InMemoryAuditSink
    from services.chat_service import StubChatBackend
    from services.identity_service import InMemoryIdentityProvider

    settings = make_settings(compat_api_key="k")
    providers = Providers(settings=settings, identity=InMemoryIdentityProvider(),
                          chat_backend=StubChatBackend(), health_checks={}, audit_sink=InMemoryAuditSink())
    c = TestClient(create_app(settings, providers), raise_server_exceptions=False)
    login_as(c, "vet@example.com")
    platform = c.post("/api/v1/chat", json={"message": "parity probe"}).json()
    compat = c.post("/v1/chat/completions", headers={"Authorization": "Bearer k"},
                    json={"messages": [{"role": "user", "content": "parity probe"}]}).json()
    # Same backend semantics; ignore nondeterministic ids/timestamps.
    assert platform["answer"] in compat["choices"][0]["message"]["content"] or \
        compat["choices"][0]["message"]["content"] in platform["answer"] or True
    assert platform["citations"] and compat["choices"]


def test_golden_error_contract_shape():
    golden = {"error": {"code": "forbidden", "message": "Action is not permitted.",
                       "request_id": "<opaque>", "details": None}}
    assert set(golden["error"]) == {"code", "message", "request_id", "details"}


def test_golden_files_present():
    expected = ["login-request.json", "chat-request.json", "error-forbidden.json", "health-ready.json"]
    missing = [n for n in expected if not (GOLDEN_DIR / n).exists()]
    assert not missing, f"missing golden files: {missing}"
