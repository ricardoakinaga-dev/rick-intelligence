"""A03 regression: one idempotency key is bound to exactly one conversation.

The baseline defect let a key minted in conv-A answer a request aimed at
conv-B. These tests are discriminating: reverting the conversation/fingerprint
check in ``ChatApplicationService`` makes every one of them fail.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from conftest import login_as


def _session(user_id: str = "user-a"):
    from models import SessionSnapshot

    return SessionSnapshot(
        authenticated=True, session_state="active", user_id=user_id,
        role="VETERINARIAN", canonical_role="VETERINARIAN",
        permissions=["chat.query"], tenant_id="tenant-a", workspace_id="workspace-a",
        allowed_collection_ids=["allowed"],
    )


def _store(kind: str, tmp_path):
    from services.chat_history import InMemoryChatHistoryStore, SQLiteChatHistoryStore

    if kind == "memory":
        return InMemoryChatHistoryStore()
    return SQLiteChatHistoryStore(tmp_path / "idempotency.sqlite3")


class CountingBackend:
    """Deterministic backend that records every generation it was asked for."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(self, *, message: str, **_kwargs):
        self.calls.append(message)
        return {"answer": f"ANSWER_FOR::{message}", "citations": [], "metadata": {}}

    async def generate_stream(self, *, message: str, **_kwargs):
        self.calls.append(message)
        yield {
            "type": "final",
            "result": {"answer": f"ANSWER_FOR::{message}", "citations": [], "metadata": {}},
        }


def _chat(service, *, message: str, conversation_id: str, key: str,
          collection_id: str | None = None, user_id: str = "user-a"):
    return asyncio.run(service.chat(
        session=_session(user_id), message=message, conversation_id=conversation_id,
        collection_id=collection_id, workspace_id=None, mode="grounded",
        idempotency_key=key,
    ))


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    history = _store(request.param, tmp_path)
    yield history
    if hasattr(history, "close"):
        history.close()


def _service(store):
    from services.chat_service import ChatApplicationService

    backend = CountingBackend()
    return ChatApplicationService(backend, history=store), backend


def test_json_chat_replays_an_identical_turn_but_refuses_another_conversation(store):
    from core.errors import ApiError

    service, backend = _service(store)
    first = _chat(service, message="ALPHA", conversation_id="conv-A", key="K")
    retry = _chat(service, message="ALPHA", conversation_id="conv-A", key="K")

    assert first["conversation_id"] == "conv-A"
    assert retry == first, "an identical retry has to be byte for byte the same turn"
    assert backend.calls == ["ALPHA"], "a replay must not generate again"

    with pytest.raises(ApiError) as conflict:
        _chat(service, message="BETA", conversation_id="conv-B", key="K")
    assert conflict.value.code == "conflict"
    assert backend.calls == ["ALPHA"], "an incompatible reuse must not generate"


def test_json_chat_refuses_the_same_key_for_another_message_or_collection(store):
    from core.errors import ApiError

    service, backend = _service(store)
    _chat(service, message="ALPHA", conversation_id="conv-A", key="K")

    with pytest.raises(ApiError) as message_clash:
        _chat(service, message="GAMMA", conversation_id="conv-A", key="K")
    assert message_clash.value.code == "conflict"

    with pytest.raises(ApiError) as collection_clash:
        _chat(service, message="ALPHA", conversation_id="conv-A", key="K",
              collection_id="allowed")
    assert collection_clash.value.code == "conflict"
    assert backend.calls == ["ALPHA"]


def test_json_chat_scopes_a_shared_key_to_its_own_user(store):
    service, backend = _service(store)
    mine = _chat(service, message="ALPHA", conversation_id="conv-A", key="K")
    theirs = _chat(
        service, message="ALPHA", conversation_id="conv-B", key="K", user_id="user-b",
    )

    assert backend.calls == ["ALPHA", "ALPHA"], "another user never sees a stored turn"
    assert theirs["conversation_id"] == "conv-B"
    assert theirs["message_id"] != mine["message_id"]


def test_stream_chat_reports_conflict_instead_of_replaying(store):
    service, backend = _service(store)

    async def exercise():
        first = [
            event async for event in service.stream_events(
                session=_session(), message="ALPHA", conversation_id="conv-A",
                collection_id=None, workspace_id=None, mode="grounded",
                idempotency_key="K",
            )
        ]
        replay = [
            event async for event in service.stream_events(
                session=_session(), message="ALPHA", conversation_id="conv-A",
                collection_id=None, workspace_id=None, mode="grounded",
                idempotency_key="K",
            )
        ]
        clash = [
            event async for event in service.stream_events(
                session=_session(), message="BETA", conversation_id="conv-B",
                collection_id=None, workspace_id=None, mode="grounded",
                idempotency_key="K",
            )
        ]
        return first, replay, clash

    first, replay, clash = asyncio.run(exercise())
    assert backend.calls == ["ALPHA"], "a replay and a clash must never generate"

    assert [event["type"] for event in first] == ["start", "delta", "completion"]
    assert [event["type"] for event in replay] == ["start", "delta", "completion"]
    assert replay[-1]["conversation_id"] == "conv-A"
    assert replay[-1]["answer"] == first[-1]["answer"]

    assert clash[-1]["type"] == "error"
    assert clash[-1]["code"] == "conflict"


def test_http_chat_returns_409_for_a_key_reused_in_another_conversation(client):
    from services.chat_history import InMemoryChatHistoryStore

    client.app.state.providers.chat_history = InMemoryChatHistoryStore()
    login_as(client, "vet@example.com")

    first = client.post("/api/v1/chat", json={
        "message": "ALPHA", "conversation_id": "conv-A", "idempotency_key": "http-K",
    })
    retry = client.post("/api/v1/chat", json={
        "message": "ALPHA", "conversation_id": "conv-A", "idempotency_key": "http-K",
    })
    clash = client.post("/api/v1/chat", json={
        "message": "BETA", "conversation_id": "conv-B", "idempotency_key": "http-K",
    })

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert clash.status_code == 409, clash.text
    body = clash.json()
    assert body["error"]["code"] == "conflict"
    assert "answer" not in body, "a conflict never carries another conversation's answer"


def test_http_stream_reports_conflict_for_a_key_reused_in_another_conversation(client):
    import json as jsonlib

    from services.chat_history import InMemoryChatHistoryStore

    client.app.state.providers.chat_history = InMemoryChatHistoryStore()
    login_as(client, "vet@example.com")

    first = client.post("/api/v1/chat", json={
        "message": "ALPHA", "conversation_id": "conv-A", "idempotency_key": "sse-K",
    })
    assert first.status_code == 200, first.text

    clash = client.post("/api/v1/chat", json={
        "message": "BETA", "conversation_id": "conv-B", "idempotency_key": "sse-K",
        "stream": True,
    })
    assert clash.status_code == 200
    events = [
        jsonlib.loads(line.removeprefix("data: "))
        for line in clash.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "conflict"
    assert not any(event.get("type") == "completion" for event in events)
