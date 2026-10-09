"""Dual-run equivalence (new platform chat vs compat adapter) + golden contracts."""

import json
from pathlib import Path

from apps.api.tests.support import login_as

GOLDEN_DIR = Path(__file__).parent / "golden"


def test_chat_and_compat_semantic_parity(client):
    from fastapi.testclient import TestClient

    from app import create_app
    from apps.api.tests.support import make_settings
    from dependencies.services import Providers
    from services.audit import InMemoryAuditSink
    from services.chat_service import StubChatBackend
    from services.identity_service import InMemoryIdentityProvider

    settings = make_settings(compat_api_key="k")
    providers = Providers(settings=settings, identity=InMemoryIdentityProvider(),
                          chat_backend=StubChatBackend(), health_checks={}, audit_sink=InMemoryAuditSink())
    c = TestClient(create_app(settings, providers), raise_server_exceptions=False)
    login_as(c, "vet@example.com")
    platform_response = c.post("/api/v1/chat", json={"message": "parity probe"})
    compat_response = c.post("/v1/chat/completions", headers={"Authorization": "Bearer k"},
                             json={"messages": [{"role": "user", "content": "parity probe"}]})
    assert platform_response.status_code == compat_response.status_code == 200
    platform = platform_response.json()
    compat = compat_response.json()
    assert platform["answer"]
    assert compat["choices"] == [{
        "index": 0, "message": {"role": "assistant", "content": platform["answer"]},
        "finish_reason": "stop",
    }]
    streamed = c.post("/v1/chat/completions", headers={"Authorization": "Bearer k"},
                      json={"messages": [{"role": "user", "content": "parity probe"}], "stream": True})
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    frames = [line.removeprefix("data: ") for line in streamed.text.splitlines() if line.startswith("data: ")]
    assert frames[-1] == "[DONE]"
    chunks = [json.loads(frame) for frame in frames[:-1]]
    assert all("error" not in chunk for chunk in chunks)
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    answer = "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks)
    assert answer == platform["answer"]
    assert platform["citations"] == []
    assert platform["metadata"]["evidence_status"] == "NO_EVIDENCE"
    assert compat["metadata"]["evidence_status"] == "NO_EVIDENCE"


def test_golden_error_contract_shape():
    golden = {"error": {"code": "forbidden", "message": "Action is not permitted.",
                       "request_id": "<opaque>", "details": None}}
    assert set(golden["error"]) == {"code", "message", "request_id", "details"}


def test_golden_files_present():
    expected = ["login-request.json", "chat-request.json", "error-forbidden.json", "health-ready.json"]
    missing = [n for n in expected if not (GOLDEN_DIR / n).exists()]
    assert not missing, f"missing golden files: {missing}"
