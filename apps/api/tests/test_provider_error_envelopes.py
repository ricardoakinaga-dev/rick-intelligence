"""AUD03-14: raw provider error envelopes never establish successful delivery."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import aclosing

import httpx
import pytest

from app import create_app
from core.config import ApiSettings
from dependencies.services import Providers
from rick_knowledge import Chunk, Collection, Document, InMemoryKnowledgeStore
from rick_providers import OpenAICompatibleClient, ProviderConfig, ProviderError
from services.professor_backend import ProfessorBackendError, ProfessorChatBackend


MODEL = "envelope-test"
QUERY = "How do I upload a document?"
TEXT = "Choose a collection, select a document and submit the upload."
RAW_ERROR = "raw-provider-error-secret https://provider.invalid/private-stack"
NO_ERROR = object()
ERROR_VALUES = [NO_ERROR, None, False, 0, "", {}, [], RAW_ERROR, {"message": RAW_ERROR}]
ERROR_IDS = ["fault_free", "null", "false", "zero", "empty_string", "empty_object",
             "empty_array", "untyped_string", "provider_error"]
CORE = {"id": "chatcmpl_error", "object": "chat.completion.chunk", "created": 123, "model": MODEL}
USAGE = {**CORE, "choices": [],
         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


def error_field(payload, error):
    return payload if error is NO_ERROR else {**payload, "error": error}


def frame(text="", reason=None):
    return {**CORE, "usage": None, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": reason}]}


def raw_json(answer, error):
    return json.dumps(error_field({**CORE, "object": "chat.completion", "choices": [{"index": 0, "logprobs": None,
        "message": {"role": "assistant", "content": answer}, "finish_reason": "stop",
    }]}, error)).encode()


def raw_sse(answer, error, stage="usage_after_stop"):
    initial, terminal = frame(answer[:9]), frame(answer[9:], "stop")
    frames = [initial, terminal]
    if stage == "initial_delta":
        frames[0] = error_field(initial, error)
    elif stage == "terminal":
        frames[1] = error_field(terminal, error)
    elif stage == "usage_before_stop":
        frames.insert(1, error_field(USAGE, error))
    elif stage == "usage_after_stop":
        frames.append(error_field(USAGE, error))
    elif stage == "empty_choices":
        frames.append(error_field(USAGE, error))
    if stage not in {"usage_before_stop", "usage_after_stop", "empty_choices"}:
        frames.append(USAGE)
    frames.append("[DONE]")
    if stage == "after_done" and error is not NO_ERROR:
        frames.append(error_field(USAGE, error))
    return b"".join(
        b"data: " + (value.encode() if isinstance(value, str) else json.dumps(value).encode()) + b"\n\n"
        for value in frames
    )


class ByteStream(httpx.AsyncByteStream):
    def __init__(self, raw, split=False):
        self.raw, self.split, self.closed = raw, split, False

    async def __aiter__(self):
        if self.split:
            for value in self.raw:
                yield bytes([value])
        else:
            yield self.raw

    async def aclose(self):
        self.closed = True


def provider_for(handler):
    calls = []

    def handle(request):
        calls.append(request)
        return handler(request)

    config = ProviderConfig(base_url="https://provider.invalid/v1", chat_model=MODEL,
                            environment="test", max_attempts=3, timeout=1)
    return OpenAICompatibleClient(config, transport=httpx.MockTransport(handle)), calls


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ERROR_VALUES, ids=ERROR_IDS)
async def test_json_error_presence_rejects_success_before_field_extraction(error):
    provider, calls = provider_for(
        lambda request: httpx.Response(200, content=raw_json(TEXT, error), request=request),
    )
    async with provider:
        if error is NO_ERROR:
            result = await provider.chat_completion(messages=[{"role": "user", "content": QUERY}])
            assert result.finish_reason == "stop" and result.content == TEXT
        else:
            with pytest.raises(ProviderError) as caught:
                await provider.chat_completion(messages=[{"role": "user", "content": QUERY}])
            assert caught.value.code == "malformed_response" and not caught.value.retryable
            assert caught.value.attempts == 1
            assert RAW_ERROR not in caught.value.to_json()
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("split", [False, True], ids=["buffered", "bytewise"])
@pytest.mark.parametrize("stage", ["initial_delta", "terminal", "usage_before_stop",
                                  "usage_after_stop", "empty_choices", "after_done"])
@pytest.mark.parametrize("error", ERROR_VALUES, ids=ERROR_IDS)
async def test_sse_error_presence_prevents_terminal_delivery_at_every_stage(split, stage, error):
    transport = ByteStream(raw_sse(TEXT, error, stage), split)
    provider, calls = provider_for(lambda request: httpx.Response(200, stream=transport, request=request))
    observed = []
    async with provider:
        async with aclosing(provider.chat_completion_stream(messages=[{"role": "user", "content": QUERY}])) as source:
            if error is NO_ERROR and stage != "usage_before_stop":
                observed = [chunk async for chunk in source]
                assert "".join(chunk.delta for chunk in observed) == TEXT
                assert observed[-1].finish_reason == "stop"
            else:
                with pytest.raises(ProviderError) as caught:
                    async for chunk in source:
                        observed.append(chunk)
                assert caught.value.code == "malformed_response" and not caught.value.retryable
                assert caught.value.attempts == 1 and RAW_ERROR not in caught.value.to_json()
                assert all(chunk.finish_reason is None for chunk in observed)
    assert len(calls) == 1 and transport.closed


def grounded_provider(path, error):
    context = {"tenant_id": "default", "workspace_id": "ws", "user_id": "reader",
               "permissions": ["chat.query"], "allowed_collection_ids": ["col"]}
    knowledge = InMemoryKnowledgeStore()
    checksum = hashlib.sha256(TEXT.encode()).hexdigest()
    knowledge.upsert_collection(Collection(tenant_id="default", workspace_id="ws", collection_id="col"))
    knowledge.upsert_document(Document(
        tenant_id="default", workspace_id="ws", collection_id="col", document_id="doc",
        document_version="v1", status="published", content_checksum=checksum,
        title="Upload instructions", filename="upload.txt",
    ))
    knowledge.replace_document_chunks("doc", [Chunk(
        tenant_id="default", document_id="doc", chunk_id="part", text=TEXT, checksum=checksum,
    )])

    class Retrieval:
        async def retrieve(self, **kwargs):
            return {"evidence": [{"tenant_id": "default", "workspace_id": "ws", "collection_id": "col",
                                  "document_id": "doc", "chunk_id": "part", "text": "untrusted",
                                  "retrieval_quality_score": 0.99}]}

    def handle(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        assert TEXT in prompt
        source = re.search(r"SOURCE (ev_[a-f0-9]{32})", prompt).group(1)
        answer = f"{TEXT} [cite:{source}]"
        raw = raw_json(answer, error) if path == "json" else raw_sse(answer, error)
        return httpx.Response(200, content=raw, request=request)

    provider, calls = provider_for(handle)
    backend = ProfessorChatBackend(
        retrieval=Retrieval(), knowledge=knowledge, provider=provider,
        authorization_revalidator=lambda *, context: dict(context),
    )
    return provider, backend, context, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["json", "stream"])
@pytest.mark.parametrize("error", ERROR_VALUES, ids=ERROR_IDS)
async def test_public_professor_error_presence_never_approves(path, error):
    provider, backend, context, calls = grounded_provider(path, error)
    observed = []

    async def deliver():
        if path == "json":
            return await backend.generate(message=QUERY, context=context, conversation_id="envelope")
        async with aclosing(backend.generate_stream(message=QUERY, context=context, conversation_id="envelope")) as source:
            async for event in source:
                observed.append(event)
        return observed[-1]["result"]

    async with provider:
        if error is NO_ERROR:
            result = await deliver()
            assert result["metadata"]["evidence_status"] == "APPROVED_EVIDENCE"
            assert result["metadata"]["publication_validation"] == "verified"
        else:
            with pytest.raises(ProfessorBackendError) as caught:
                await deliver()
            assert caught.value.stage == "provider_failed"
            assert all(event["type"] == "delta" and event["provisional"] for event in observed)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["json", "stream"])
@pytest.mark.parametrize("error", ERROR_VALUES, ids=ERROR_IDS)
async def test_real_compatibility_api_error_presence_never_publishes_success(path, error):
    provider, backend, _, calls = grounded_provider(path, error)
    settings = ApiSettings(environment="test", compat_api_key="envelope-key",
                           compat_workspace_id="ws", compat_allowed_collection_ids=("col",))
    app = create_app(settings, Providers(settings=settings, chat_backend=backend))
    async with provider:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as api:
            response = await api.post("/v1/chat/completions", headers={"Authorization": "Bearer envelope-key"},
                                      json={"model": "rick-professor", "messages": [{"role": "user", "content": QUERY}],
                                            "stream": path == "stream"})
    assert len(calls) == 1 and RAW_ERROR not in response.text
    if path == "json":
        assert response.status_code == (200 if error is NO_ERROR else 503)
        if error is NO_ERROR:
            assert response.json()["metadata"]["evidence_status"] == "APPROVED_EVIDENCE"
            assert response.json()["metadata"]["publication_validation"] == "verified"
        else:
            assert "APPROVED_EVIDENCE" not in response.text
    else:
        assert response.status_code == 200
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: ") and line != "data: [DONE]"]
        terminals = [choice for event in events for choice in event.get("choices", [])
                     if choice.get("finish_reason") == "stop"]
        errors = [event for event in events if "error" in event]
        assert bool(terminals) is (error is NO_ERROR)
        assert bool(errors) is (error is not NO_ERROR)
        assert response.text.count("data: [DONE]") == 1
