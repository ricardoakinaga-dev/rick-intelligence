"""Streaming: SSE shape, single final event, cancellation-safe."""

import json
from types import SimpleNamespace

import pytest

from apps.api.tests.support import login_as


def _chat_session():
    from models import SessionSnapshot

    return SessionSnapshot(
        authenticated=True, session_state="active", user_id="user-a",
        role="VETERINARIAN", canonical_role="VETERINARIAN",
        permissions=["chat.query"], tenant_id="tenant-a", workspace_id="workspace-a",
        allowed_collection_ids=["allowed"],
    )


def test_platform_chat_sse(client):
    login_as(client, "vet@example.com")
    resp = client.post("/api/v1/chat", json={"message": "hello world, this is a streaming test", "stream": True})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    text = resp.text
    assert "data: [DONE]" in text
    assert text.count("[DONE]") == 1  # no duplicate final event
    assert '"type": "start"' in text or '"type":"start"' in text or "start" in text


def test_platform_chat_non_stream_shape(client):
    login_as(client, "vet@example.com")
    resp = client.post("/api/v1/chat", json={"message": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert {"conversation_id", "message_id", "answer", "citations", "metadata"} <= set(body)
    assert "chain" not in str(body).lower()


def test_chat_validates_idempotency_winner_returned_by_append():
    import asyncio
    from core.errors import ApiError
    from services.chat_service import ChatApplicationService

    class Backend:
        async def generate(self, **_kwargs):
            return {"answer": "fresh", "citations": [], "metadata": {}}

    class RacingHistory:
        def append(self, **_kwargs):
            return {
                "conversation_id": "conv-winner", "message_id": "msg-winner",
                "answer": "stale winner",
                "citations": [{"collection_id": "other", "document_id": "doc-1", "chunk_id": "chunk-1"}],
                "metadata": {"evidence_status": "WEAK_EVIDENCE"},
            }

    service = ChatApplicationService(Backend(), history=RacingHistory())
    with pytest.raises(ApiError) as error:
        asyncio.run(service.chat(
            session=_chat_session(), message="question", conversation_id=None,
            collection_id="allowed", workspace_id=None, mode="grounded",
            idempotency_key="same-request",
        ))
    assert error.value.code == "forbidden"


def test_concurrent_idempotent_streams_keep_their_start_identifiers():
    import asyncio
    from services.chat_history import InMemoryChatHistoryStore
    from services.chat_service import ChatApplicationService

    class Backend:
        async def generate(self, **_kwargs):
            return {"answer": "answer", "citations": [], "metadata": {}}

        async def generate_stream(self, **kwargs):
            await asyncio.sleep(0)
            yield {"type": "final", "result": await self.generate(**kwargs)}

    async def exercise():
        history = InMemoryChatHistoryStore()
        service = ChatApplicationService(Backend(), history=history)
        keys = (" same-request ", "same-request")
        streams = [
            service.stream_events(
                session=_chat_session(), message="question", conversation_id=None,
                collection_id=None, workspace_id=None, mode="grounded",
                idempotency_key=key,
            )
            for key in keys
        ]
        starts = [await anext(stream) for stream in streams]

        async def rest(stream):
            return [event async for event in stream]

        tails = await asyncio.gather(*(rest(stream) for stream in streams))
        for start, events in zip(starts, tails):
            identifiers = {
                (event.get("conversation_id"), event.get("message_id"))
                for event in events if event.get("type") in {"delta", "citation", "completion"}
            }
            assert identifiers == {(start["conversation_id"], start["message_id"])}
            assert not any(event.get("type") == "error" for event in events)
        assert history.get_idempotent(
            session=_chat_session(), idempotency_key="same-request",
        ) is not None

    asyncio.run(exercise())


def test_json_chat_uses_one_canonical_idempotency_key():
    import asyncio
    from services.chat_history import InMemoryChatHistoryStore
    from services.chat_service import ChatApplicationService

    class Backend:
        def __init__(self):
            self.calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            return {"answer": "answer", "citations": [], "metadata": {}}

    async def exercise():
        backend = Backend()
        history = InMemoryChatHistoryStore()
        service = ChatApplicationService(backend, history=history)
        first = await service.chat(
            session=_chat_session(), message="question", conversation_id=None,
            collection_id=None, workspace_id=None, mode="grounded",
            idempotency_key=" retry-key ",
        )
        retry = await service.chat(
            session=_chat_session(), message="question", conversation_id=None,
            collection_id=None, workspace_id=None, mode="grounded",
            idempotency_key="retry-key",
        )
        assert (retry["conversation_id"], retry["message_id"]) == (
            first["conversation_id"], first["message_id"],
        )
        assert backend.calls == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("invalid_key", ["   ", "retry\nkey", "retry\x7fkey"])
def test_invalid_idempotency_key_is_rejected_for_json_and_stream_chat(invalid_key):
    import asyncio
    from core.errors import ApiError
    from services.chat_history import InMemoryChatHistoryStore
    from services.chat_service import ChatApplicationService

    class Backend:
        async def generate(self, **_kwargs):
            raise AssertionError("blank retry key must be rejected before generation")

        async def generate_stream(self, **_kwargs):
            raise AssertionError("blank retry key must be rejected before generation")
            yield  # pragma: no cover - makes this an async generator

    async def exercise():
        history = InMemoryChatHistoryStore()
        service = ChatApplicationService(Backend(), history=history)
        with pytest.raises(ApiError) as error:
            await service.chat(
                session=_chat_session(), message="question", conversation_id=None,
                collection_id=None, workspace_id=None, mode="grounded",
                idempotency_key=invalid_key,
            )
        assert error.value.code == "validation_error"

        events = [event async for event in service.stream_events(
            session=_chat_session(), message="question", conversation_id=None,
            collection_id=None, workspace_id=None, mode="grounded",
            idempotency_key=invalid_key,
        )]
        assert [event["type"] for event in events] == ["start", "error"]
        assert events[-1]["code"] == "validation_error"
        assert history.list_history(session=_chat_session()) == []

    asyncio.run(exercise())


@pytest.mark.parametrize("stream_mode", ["live", "buffered"])
@pytest.mark.parametrize("evidence_status", ["APPROVED_EVIDENCE", "WEAK_EVIDENCE", "NO_EVIDENCE", None])
def test_completion_metadata_matches_json_replay_and_history(client, tmp_path, stream_mode, evidence_status):
    from rick_contracts.chat import Citation
    from services.chat_history import SQLiteChatHistoryStore

    calls = []
    metadata = {"evidence_status": evidence_status} if evidence_status else {}
    result = {
        "answer": "Resposta canônica.",
        "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1"}],
        "metadata": metadata,
    }

    async def generate(**kwargs):
        calls.append(kwargs)
        return result

    async def generate_stream(**kwargs):
        yield {"type": "delta", "delta": "Resposta provisória."}
        yield {"type": "final", "result": await generate(**kwargs)}

    backend = SimpleNamespace(generate=generate)
    if stream_mode == "live":
        backend.generate_stream = generate_stream
    client.app.state.providers.chat_backend = backend
    store = SQLiteChatHistoryStore(tmp_path / "chat.sqlite3")
    client.app.state.providers.chat_history = store
    login_as(client, "km@example.com")
    request = {"message": "pergunta", "conversation_id": "conv-equivalence", "idempotency_key": "turn-1"}
    response = client.post("/api/v1/chat", json={**request, "stream": True})
    assert response.status_code == 200, response.text

    def completion(response):
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: ") and line != "data: [DONE]"]
        assert not any(event["type"] == "error" for event in events)
        assert response.text.count("data: [DONE]") == 1
        final = next(event for event in events if event["type"] == "completion")
        start = next(event for event in events if event["type"] == "start")
        assert (start["conversation_id"], start["message_id"]) == (
            final["conversation_id"], final["message_id"],
        )
        assert [event["citation"] for event in events if event["type"] == "citation"] == final["citations"]
        return final

    streamed = completion(response)
    replayed = completion(client.post("/api/v1/chat", json={**request, "stream": True}))
    canonical = client.post("/api/v1/chat", json=request).json()
    history = client.get("/api/v1/history").json()["items"]
    conversation = client.get("/api/v1/conversations/conv-equivalence").json()["items"]
    assert len(calls) == len(history) == len(conversation) == 1

    for payload in (streamed, replayed, history[0], conversation[0]):
        for field in ("conversation_id", "message_id", "answer", "metadata"):
            assert payload[field] == canonical[field]
        assert [Citation.model_validate(item).model_dump() for item in payload["citations"]] == canonical["citations"]
    assert (streamed["conversation_id"], streamed["message_id"]) == (
        replayed["conversation_id"], replayed["message_id"],
    )
    assert streamed["metadata"]["stream_mode"] == stream_mode
    assert streamed["metadata"].get("evidence_status") == evidence_status
