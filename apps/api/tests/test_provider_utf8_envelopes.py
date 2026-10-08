"""Public Professor paths reject corrupt raw bytes and approve healthy Unicode."""

from __future__ import annotations

import hashlib
import json
import re

import httpx
import pytest

from app import create_app
from core.config import ApiSettings
from dependencies.identity import require_authenticated
from dependencies.services import Providers
from models import SessionSnapshot
from rick_knowledge import Chunk, Collection, Document, InMemoryKnowledgeStore
from rick_providers import OpenAICompatibleClient, ProviderConfig
from rick_professor import ProfessorLimits
from services.professor_backend import ProfessorChatBackend


QUERY = "How do I upload a document?"
TEXT = "Choose a collection, select a document and submit the upload. ação 😀 漢字 \ufffd"
CONTEXT = {"tenant_id": "default", "workspace_id": "utf8-ws", "user_id": "reader",
           "permissions": ["chat.query"], "allowed_collection_ids": ["utf8-col"]}


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def raw_response(answer, streaming, fault):
    choice = {"index": 0, "logprobs": None, "finish_reason": "stop"}
    choice["delta" if streaming else "message"] = {"content": answer}
    if not streaming:
        choice["message"]["role"] = "assistant"
    if fault == "refusal":
        choice["delta" if streaming else "message"]["refusal"] = "I cannot comply."
    if fault in {"tool_stop", "tool_allowed_stop", "tool_bad_json", "tool_array", "tool_duplicate"}:
        call = {"id": "call-envelope", "type": "function",
                "function": {"name": "status", "arguments": {
                    "tool_bad_json": "{truncated", "tool_array": "[]",
                    "tool_duplicate": '{"x":1,"x":2}',
                }.get(fault, "{}")}}
        if streaming:
            call["index"] = 0
        choice["delta" if streaming else "message"]["tool_calls"] = [call]
    envelope = {"id": "chatcmpl_utf8", "object": "chat.completion.chunk" if streaming else "chat.completion", "created": 123, "model": "utf8-public", "choices": [choice]}
    if fault in {"usage_healthy", "usage_over_budget", "usage_empty_healthy", "usage_empty_over_budget", "usage_post_terminal_choice"}:
        total = 100 if fault in {"usage_healthy", "usage_empty_healthy", "usage_post_terminal_choice"} else 20000
        envelope["usage"] = {"prompt_tokens": 50, "completion_tokens": total - 50, "total_tokens": total}
    if streaming and "usage" not in envelope:
        envelope["usage"] = None
    body = encode(envelope)
    if fault == "content":
        body = body.replace(b"Choose", b"Cho\xffose")
    if streaming:
        usage_trailer = b"data: " + encode({**envelope, "choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 50, "total_tokens": 100}}) + b"\r\n\r\n"
        if envelope.get("usage") is not None:
            body = encode({**envelope, "choices": [choice], "usage": None})
            usage_trailer = b"data: " + encode({**envelope, "choices": [{"index": 0, "delta": {}, "finish_reason": None}] if fault == "usage_post_terminal_choice" else [],
                                                "usage": envelope["usage"]}) + b"\r\n\r\n"
        body = (
            "\ufeff: ação 😀 \ufffd\r\n".encode("utf-8") + b"data: " + body + b"\r\n\r\n" + usage_trailer + b"data: [DONE]\r\n\r\n"
        )
    if fault == "tail":
        body += b": corrupt \xff\r\n" if streaming else b"\xff"
    if fault == "incomplete_tail":
        body += b": truncated \xf0\x9f\x92" if streaming else b"\xf0\x9f\x92"
    return body


class Bytes(httpx.AsyncByteStream):
    def __init__(self, raw):
        self.raw, self.closed = raw, False

    async def __aiter__(self):
        # Every multibyte character and CRLF is fragmented at the byte boundary.
        for value in self.raw:
            yield bytes([value])

    async def aclose(self):
        self.closed = True


def grounded_backend(fault, fallback):
    knowledge = InMemoryKnowledgeStore()
    checksum = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
    knowledge.upsert_collection(Collection(tenant_id="default", workspace_id="utf8-ws", collection_id="utf8-col"))
    knowledge.upsert_document(Document(
        tenant_id="default", workspace_id="utf8-ws", collection_id="utf8-col", document_id="utf8-doc",
        document_version="v1", status="published", content_checksum=checksum,
        title="Upload instructions", filename="utf8.txt",
    ))
    knowledge.replace_document_chunks("utf8-doc", [Chunk(
        tenant_id="default", document_id="utf8-doc", chunk_id="utf8-part", text=TEXT, checksum=checksum,
    )])

    class Retrieval:
        async def retrieve(self, **kwargs):
            return {"evidence": [{"tenant_id": "default", "workspace_id": "utf8-ws", "collection_id": "utf8-col",
                                  "document_id": "utf8-doc", "chunk_id": "utf8-part", "text": "untrusted",
                                  "retrieval_quality_score": 0.99}]}

    calls, streams = [], []

    def handle(request):
        payload = json.loads(request.content)
        calls.append(payload)
        prompt = payload["messages"][0]["content"]
        assert TEXT in prompt
        source = re.search(r"SOURCE (ev_[a-f0-9]{32})", prompt).group(1)
        stream = Bytes(raw_response(f"{TEXT} [cite:{source}]", bool(payload.get("stream")), fault))
        streams.append(stream)
        return httpx.Response(200, stream=stream, request=request)

    provider = OpenAICompatibleClient(
        ProviderConfig(base_url="http://utf8.invalid/v1", chat_model="utf8-public",
                       environment="test", max_attempts=3, timeout=1),
        transport=httpx.MockTransport(handle),
    )

    class JSONOnly:
        async def chat_completion(self, *args, **kwargs):
            return await provider.chat_completion(*args, **kwargs)

    backend = ProfessorChatBackend(
        retrieval=Retrieval(), knowledge=knowledge, provider=JSONOnly() if fallback else provider,
        authorization_revalidator=lambda *, context: dict(context),
        limits=ProfessorLimits(max_tool_calls=1 if fault in {
            "tool_allowed_stop", "tool_bad_json", "tool_array", "tool_duplicate",
        } else 0),
    )
    return provider, backend, knowledge, calls, streams


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["healthy", "content", "tail", "incomplete_tail", "refusal", "tool_stop",
                                 "tool_allowed_stop", "tool_bad_json", "tool_array", "tool_duplicate",
                                 "usage_healthy", "usage_over_budget", "usage_empty_healthy", "usage_empty_over_budget"])
@pytest.mark.parametrize("path", ["canonical_json", "canonical_stream", "compat_json", "compat_stream",
                                 "canonical_stream_fallback", "compat_stream_fallback"])
async def test_public_utf8_contract_including_json_stream_fallback(path, fault):
    provider, backend, knowledge, calls, streams = grounded_backend(fault, "fallback" in path)
    settings = ApiSettings(environment="test", compat_api_key="utf8-key",
                           compat_workspace_id="utf8-ws", compat_allowed_collection_ids=("utf8-col",))
    app = create_app(settings, Providers(settings=settings, chat_backend=backend, knowledge=knowledge))
    app.dependency_overrides[require_authenticated] = lambda: SessionSnapshot(
        authenticated=True, session_state="active", **CONTEXT,
    )
    streaming = "stream" in path
    async with provider:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as api:
            if path.startswith("canonical"):
                response = await api.post("/api/v1/chat", json={
                    "message": QUERY, "stream": streaming, "conversation_id": f"utf8-{fault}-{path}",
                    "collection_id": "utf8-col", "workspace_id": "utf8-ws",
                })
            else:
                response = await api.post("/v1/chat/completions", headers={"Authorization": "Bearer utf8-key"},
                                          json={"model": "rick-professor", "messages": [{"role": "user", "content": QUERY}],
                                                "stream": streaming})
    assert len(calls) == 1 and all(stream.closed for stream in streams)
    assert bool(calls[0].get("stream")) is (streaming and "fallback" not in path)
    if not streaming:
        assert response.status_code == (200 if fault in {"healthy", "usage_healthy", "usage_empty_healthy"} else 503)
        if fault in {"healthy", "usage_healthy", "usage_empty_healthy"}:
            assert response.json()["metadata"]["evidence_status"] == "APPROVED_EVIDENCE"
            assert response.json()["metadata"]["publication_validation"] == "verified"
        else:
            assert "APPROVED_EVIDENCE" not in response.text
        return
    assert response.status_code == 200 and response.text.count("data: [DONE]") == 1
    events = [json.loads(line[6:]) for line in response.text.splitlines()
              if line.startswith("data: ") and line != "data: [DONE]"]
    if path.startswith("canonical"):
        completions = [event for event in events if event.get("type") == "completion"]
        errors = [event for event in events if event.get("type") == "error"]
        if fault in {"healthy", "usage_healthy", "usage_empty_healthy"}:
            assert len(completions) == 1
            assert completions[0]["metadata"]["evidence_status"] == "APPROVED_EVIDENCE"
            assert completions[0]["metadata"]["publication_validation"] == "verified"
        else:
            assert not completions and not any(event.get("type") == "delta" for event in events)
    else:
        completions = [choice for event in events for choice in event.get("choices", [])
                       if choice.get("finish_reason") == "stop"]
        errors = [event for event in events if "error" in event]
        assert len(completions) == (1 if fault in {"healthy", "usage_healthy", "usage_empty_healthy"} else 0)
    assert len(errors) == (0 if fault in {"healthy", "usage_healthy", "usage_empty_healthy"} else 1)
    if fault not in {"healthy", "usage_healthy", "usage_empty_healthy"}:
        assert "APPROVED_EVIDENCE" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["canonical_stream", "compat_stream"])
async def test_public_stream_rejects_choice_in_post_terminal_usage(path):
    await test_public_utf8_contract_including_json_stream_fallback(path, "usage_post_terminal_choice")
