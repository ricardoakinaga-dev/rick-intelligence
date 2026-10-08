"""Messages wire fixtures from the native API, with adversarial boundaries."""

from __future__ import annotations

import asyncio
import copy
import json
from contextlib import aclosing

import httpx
import pytest


from rick_providers import (
    AnthropicMessagesClient, OpenAICompatibleClient, ProviderConfig,
    ProviderConfigurationError, ProviderError, ResilientProvider, create_provider,
)

MODEL = "claude-sonnet-5-5"
MESSAGES = [{"role": "system", "content": "Be precise."}, {"role": "user", "content": "Hello"}]
TOOL = {"type": "function", "function": {"name": "lookup", "description": "Read a record",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}}, "strict": True}}


def config(**overrides):
    values = dict(provider_kind="anthropic", environment="production", chat_model=MODEL,
                  api_key="claude-secret", embedding_provider_kind="openai",
                  embedding_base_url="https://embed.invalid/v1", embedding_api_key="embedding-secret",
                  embedding_dimensions=3, max_attempts=3, retry_base_delay=0, timeout=1)
    values.update(overrides)
    return ProviderConfig(**values)


def message(**overrides):
    body = dict(id="msg_1", type="message", role="assistant", model=MODEL,
                content=[{"type": "text", "text": "Hello"}], stop_reason="end_turn", stop_sequence=None,
                usage={"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 3,
                       "cache_read_input_tokens": 2, "service_tier": "standard"})
    body.update(overrides)
    return body


def events(text="Hello", reason="end_turn", *, tools=False):
    body = message(content=[], stop_reason=None, usage={"input_tokens": 10, "output_tokens": 1})
    values = [{"type": "message_start", "message": body}]
    if tools:
        values.extend([
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {}}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": '{"id":'}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": '"item"}'}},
            {"type": "content_block_stop", "index": 1},
        ])
    else:
        values.extend([
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "ping"},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
            {"type": "content_block_stop", "index": 0},
        ])
    values.extend([
        {"type": "message_delta", "delta": {"stop_reason": reason, "stop_sequence": None}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ])
    return values


def wire(values):
    return b"".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode() for event in values)


class Stream(httpx.AsyncByteStream):
    def __init__(self, parts, *, error=None, wait=False):
        self.parts, self.error, self.wait = parts, error, wait
        self.closed = False
        self.waiting = asyncio.Event()

    async def __aiter__(self):
        for part in self.parts:
            yield part
        if self.error:
            raise self.error
        if self.wait:
            self.waiting.set()
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_native_request_and_independent_embedding_headers():
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "embed.invalid":
            return httpx.Response(200, json={"model": "text-embedding-3-small", "data": [{"index": 0, "embedding": [1, 2, 3]}]})
        return httpx.Response(200, json=message())

    async with create_provider(config(), transport=httpx.MockTransport(handle)) as provider:
        assert isinstance(provider, AnthropicMessagesClient)
        result = await provider.chat_completion(messages=MESSAGES, tools=[TOOL], correlation_id="logical-1")
        vector = await provider.get_embedding("document", correlation_id="logical-2")
    assert result.content == "Hello" and result.finish_reason == "stop"
    assert result.usage.model_dump() == {"prompt_tokens": 15, "completion_tokens": 5, "total_tokens": 20}
    assert vector.vector == [1, 2, 3]
    chat, embed = requests
    assert str(chat.url) == "https://api.anthropic.com/v1/messages"
    assert chat.headers["x-api-key"] == "claude-secret"
    assert chat.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in chat.headers
    payload = json.loads(chat.content)
    assert payload["model"] == MODEL and payload["max_tokens"] == 4096
    assert payload["system"] == [{"type": "text", "text": "Be precise."}]
    assert payload["messages"] == [MESSAGES[1]]
    assert payload["tools"] == [{"name": "lookup", "description": "Read a record", "strict": True,
                                  "input_schema": TOOL["function"]["parameters"]}]
    assert "temperature" not in payload and "response_format" not in payload
    assert str(embed.url) == "https://embed.invalid/v1/embeddings"
    assert embed.headers["authorization"] == "Bearer embedding-secret"
    assert "x-api-key" not in embed.headers and "anthropic-version" not in embed.headers
    assert json.loads(embed.content)["dimensions"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,expected", [("end_turn", "stop"), ("stop_sequence", "stop"),
    ("max_tokens", "length"), ("model_context_window_exceeded", "length"), ("tool_use", "tool_calls")])
async def test_nonstream_stop_reasons_and_tools(reason, expected):
    content = [{"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"id": "item"}}] if reason == "tool_use" else [{"type": "text", "text": "answer"}]
    body = message(stop_reason=reason, stop_sequence="END" if reason == "stop_sequence" else None, content=content)
    async with create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as provider:
        result = await provider.chat_completion(MESSAGES)
    assert result.finish_reason == expected
    if reason == "tool_use":
        assert json.loads(result.tool_calls[0].function.arguments) == {"id": "item"}


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"stop_reason": None}, {"stop_reason": "refusal"}, {"stop_reason": "pause_turn"},
    {"stop_details": {"type": "refusal", "explanation": "private refusal"}},
    {"stop_details": False}, {"model": "other-model"}, {"role": "user"},
    {"content": []}, {"content": [{"type": "thinking", "thinking": "private"}]},
    {"content": [{"type": "text", "text": "hello", "citations": [{"id": "lost"}]}]},
    {"content": [{"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": []}], "stop_reason": "tool_use"},
    {"usage": {"input_tokens": True, "output_tokens": 1}},
    {"usage": {"input_tokens": 10, "output_tokens": -1}},
    {"content": [{"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {}}]},
])
async def test_nonstream_malformed_and_refusal_never_succeed(overrides):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=message(**overrides))
    async with create_provider(config(), transport=httpx.MockTransport(handle)) as provider:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(MESSAGES)
    assert len(calls) == 1 and not caught.value.retryable
    assert "private" not in str(caught.value) and "secret" not in repr(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"messages": [{"role": "tool", "content": "unsupported", "tool_call_id": "id"}]},
    {"messages": [{"role": "user", "content": "hello", "images": ["lost"]}]},
    {"messages": [MESSAGES[1], MESSAGES[0]]}, {"messages": [MESSAGES[0]]},
    {"messages": [{"role": "assistant", "content": "prefill"}]},
    {"temperature": 2}, {"temperature": float("nan")},
    {"response_format": {"type": "json_schema", "schema": {}}},
    {"response_format": {"type": []}},
    {"tools": [dict(TOOL, ignored=True)]}, {"tools": [TOOL, TOOL]}, {"tools": 5},
    {"tools": [{"type": "function", "function": {"name": "x", "parameters": {"type": "array"}}}]},
])
async def test_unsupported_input_is_typed_and_never_sent(kwargs):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=message())
    params = {"messages": MESSAGES, **kwargs}
    async with create_provider(config(), transport=httpx.MockTransport(handle)) as provider:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(**params)
    assert caught.value.attempts == 0 and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("split", ["whole", "events", "bytes"])
@pytest.mark.parametrize("reason,tools", [("end_turn", False), ("max_tokens", False), ("tool_use", True)])
async def test_native_stream_normalizes_and_closes(split, reason, tools):
    values = events("Olá �", reason, tools=tools)
    raw = wire(values)
    parts = [raw] if split == "whole" else [wire([event]) for event in values] if split == "events" else [bytes([byte]) for byte in raw]
    transport = Stream(parts)
    async with create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=transport))) as provider:
        chunks = [chunk async for chunk in provider.chat_completion_stream(MESSAGES)]
    assert "".join(chunk.delta for chunk in chunks) == "Olá �"
    assert chunks[-1].finish_reason == {"end_turn": "stop", "max_tokens": "length", "tool_use": "tool_calls"}[reason]
    assert chunks[-1].usage.total_tokens == 15
    assert sum(chunk.finish_reason is not None for chunk in chunks) == 1
    if tools:
        calls = [call for chunk in chunks for call in chunk.tool_calls or []]
        assert {call.index for call in calls} == {0}
        assert calls[0].id == "toolu_1"
        assert json.loads("".join(call.function.arguments for call in calls)) == {"id": "item"}
    assert transport.closed


def broken_events(case):
    values = events()
    if case == "eof":
        return wire(values[:-1])
    if case == "missing_delta":
        return wire(values[:-2] + [values[-1]])
    if case == "missing_block_stop":
        values = [event for event in values if event["type"] != "content_block_stop"]
    elif case == "bad_index":
        values[3]["index"] = 3
    elif case == "duplicate_start":
        values.insert(1, copy.deepcopy(values[0]))
    elif case == "post_terminal":
        values.append({"type": "ping"})
    elif case == "refusal":
        values[-2]["delta"]["stop_details"] = {"type": "refusal", "explanation": "private"}
    elif case == "refusal_reason":
        values[-2]["delta"]["stop_reason"] = "refusal"
    elif case == "bad_usage":
        values[-2]["usage"]["output_tokens"] = -1
    elif case == "mismatch_event":
        return wire(values).replace(b"event: message_stop", b"event: ping")
    elif case == "invalid_json":
        return wire(values) + b"event: x\ndata: {invalid\n\n"
    elif case == "invalid_utf8_tail":
        return wire(values) + b": \xff\n\n"
    elif case == "incomplete_frame":
        return wire(values).rstrip(b"\n")
    elif case == "unknown_block":
        values[1]["content_block"]["type"] = "thinking"
    elif case == "empty":
        return b""
    elif case == "tool_json":
        values = events(reason="tool_use", tools=True)
        values[5]["delta"]["partial_json"] = "["
    elif case == "duplicate_json":
        return wire(values).replace(b'"type": "message_stop"', b'"type":"message_stop","type":"message_stop"')
    return wire(values)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["eof", "missing_delta", "missing_block_stop", "bad_index", "duplicate_start",
    "post_terminal", "refusal", "refusal_reason", "bad_usage", "mismatch_event", "invalid_json",
    "invalid_utf8_tail", "incomplete_frame", "unknown_block", "empty", "tool_json", "duplicate_json"])
async def test_bad_stream_never_delivers_terminal(case):
    stream = Stream([broken_events(case)])
    calls, observed = [], []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=stream)
    async with create_provider(config(), transport=httpx.MockTransport(handle)) as provider:
        with pytest.raises(ProviderError) as caught:
            async for chunk in provider.chat_completion_stream(MESSAGES):
                observed.append(chunk)
    assert not any(chunk.finish_reason is not None for chunk in observed)
    assert len(calls) == 1 and not caught.value.retryable
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,attempts", [(429, "rate_limit", 3), (529, "server_error", 3),
    (408, "timeout", 3), (401, "http_error", 1), (400, "model_not_found", 1), (302, "http_error", 1)])
@pytest.mark.parametrize("streaming", [False, True])
async def test_http_errors_are_bounded_redacted_and_classified(status, code, attempts, streaming):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "model not found private" if status == 400 else "private", "type": "not_found_error"}},
                              headers={"location": "https://other.invalid/secret"})
    async with create_provider(config(), transport=httpx.MockTransport(handle)) as provider:
        with pytest.raises(ProviderError) as caught:
            if streaming:
                [chunk async for chunk in provider.chat_completion_stream(MESSAGES, correlation_id="one")]
            else:
                await provider.chat_completion(MESSAGES, correlation_id="one")
    assert caught.value.code == code and caught.value.attempts == attempts
    assert len(calls) == attempts and {request.headers["x-correlation-id"] for request in calls} == {"one"}
    assert "private" not in str(caught.value) and "secret" not in repr(caught.value)


@pytest.mark.asyncio
async def test_stream_error_retries_only_before_visible_output():
    calls = []
    overload = {"type": "error", "error": {"type": "overloaded_error", "message": "private"}}
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=wire([overload]) if len(calls) == 1 else wire(events()))
    async with create_provider(config(), transport=httpx.MockTransport(handle)) as provider:
        result = [chunk async for chunk in provider.chat_completion_stream(MESSAGES)]
    assert result[-1].finish_reason == "stop" and len(calls) == 2
    calls.clear()
    def partial(request):
        calls.append(request)
        return httpx.Response(200, content=wire(events()[:4] + [overload]))
    observed = []
    async with create_provider(config(), transport=httpx.MockTransport(partial)) as provider:
        with pytest.raises(ProviderError) as caught:
            async for chunk in provider.chat_completion_stream(MESSAGES):
                observed.append(chunk)
    assert caught.value.code == "server_error" and len(calls) == 1
    assert not any(chunk.finish_reason for chunk in observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_byte_bound_closes_response(streaming):
    stream = Stream([b"x" * 1_000_001])
    async with create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as provider:
        with pytest.raises(ProviderError) as caught:
            if streaming:
                [chunk async for chunk in provider.chat_completion_stream(MESSAGES)]
            else:
                await provider.chat_completion(MESSAGES)
    assert caught.value.code == "malformed_response" and stream.closed


@pytest.mark.asyncio
async def test_stream_cancel_and_explicit_close_keep_no_terminal():
    stream = Stream([wire(events()[:4])], wait=True)
    async with create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as provider:
        observed = []
        async def consume():
            async for chunk in provider.chat_completion_stream(MESSAGES):
                observed.append(chunk)
        task = asyncio.create_task(consume())
        await asyncio.wait_for(stream.waiting.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stream.closed and not any(chunk.finish_reason for chunk in observed)
    stream = Stream([wire(events())])
    async with create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as provider:
        async with aclosing(provider.chat_completion_stream(MESSAGES)) as source:
            await anext(source)
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_absolute_deadline_bounds_hanging_body(streaming):
    streams = []
    def handle(request):
        stream = Stream([wire(events())] if streaming else [], wait=True)
        streams.append(stream)
        return httpx.Response(200, stream=stream)
    async with create_provider(config(timeout=0.02, max_attempts=2), transport=httpx.MockTransport(handle)) as provider:
        observed = []
        with pytest.raises(ProviderError) as caught:
            if streaming:
                async for chunk in provider.chat_completion_stream(MESSAGES):
                    observed.append(chunk)
            else:
                await provider.chat_completion(MESSAGES)
    assert caught.value.code == "timeout" and all(stream.closed for stream in streams)
    assert len(streams) == (1 if streaming else 2)
    assert not any(chunk.finish_reason for chunk in observed)


@pytest.mark.asyncio
async def test_json_object_mode_validates_before_terminal():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=wire(events('{"ok":true}')))
    async with create_provider(config(), transport=httpx.MockTransport(handle)) as provider:
        chunks = [chunk async for chunk in provider.chat_completion_stream(MESSAGES, response_format={"type": "json_object"})]
    assert chunks[-1].finish_reason == "stop"
    assert "JSON object" in json.loads(requests[0].content)["system"][-1]["text"]
    async with create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=message(content=[{"type": "text", "text": "[]"}])))) as provider:
        with pytest.raises(ProviderError):
            await provider.chat_completion(MESSAGES, response_format={"type": "json_object"})


@pytest.mark.asyncio
async def test_health_native_model_lookup_and_caller_client_ownership():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"id": MODEL, "type": "model",
            "display_name": "Claude Sonnet 4.5", "created_at": "2025-09-29T00:00:00Z"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    provider = create_provider(config(), client=client)
    try:
        assert await provider.health_check()
        await provider.aclose()
        assert not client.is_closed
    finally:
        await client.aclose()
    assert requests[0].url.path == f"/v1/models/{MODEL}"
    assert requests[0].method == "GET" and requests[0].headers["x-api-key"] == "claude-secret"


@pytest.mark.parametrize("overrides", [{"embedding_provider_kind": None, "embedding_base_url": None, "embedding_api_key": None},
    {"embedding_api_key": None}, {"embedding_provider_kind": "anthropic"}, {"embedding_base_url": "https://user:secret@bad.invalid"},
    {"api_key": None}, {"api_key": "secret\r\nx: bad"}, {"anthropic_version": "bad\n"}, {"max_output_tokens": 0}, {"chat_model": ""}])
def test_production_anthropic_fails_closed_without_complete_config(overrides):
    with pytest.raises(ProviderConfigurationError) as caught:
        create_provider(config(**overrides))
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_local_anthropic_cannot_send_embeddings_to_chat_endpoint():
    calls = []
    provider = create_provider(config(environment="test", embedding_provider_kind=None,
        embedding_base_url=None, embedding_api_key=None), transport=httpx.MockTransport(lambda request: calls.append(request)))
    with pytest.raises(ProviderError) as caught:
        await provider.get_embedding("document")
    assert caught.value.code == "invalid_configuration" and caught.value.operation == "embeddings"
    assert calls == []


def test_env_contract_and_redacted_config():
    cfg = ProviderConfig.from_env({"RICK_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "claude-secret",
        "ANTHROPIC_CHAT_MODEL": MODEL, "RICK_EMBEDDING_PROVIDER": "openai", "EMBEDDING_API_KEY": "embedding-secret",
        "EMBEDDING_BASE_URL": "https://embed.invalid/v1", "ANTHROPIC_MAX_TOKENS": "1024"})
    cfg.validate()
    assert cfg.base_url == "https://api.anthropic.com/v1" and cfg.chat_model == MODEL
    assert cfg.max_output_tokens == 1024 and "secret" not in repr(cfg) and "invalid" not in repr(cfg)
    legacy = ProviderConfig.from_env({"OPENAI_API_KEY": "openai-secret", "OPENAI_CHAT_MODEL": "gpt-6-astra"})
    legacy.validate()
    assert legacy.api_key == "openai-secret" and legacy.embedding_provider_kind is None
    with pytest.raises(ProviderConfigurationError):
        create_provider(ProviderConfig(provider_kind="deterministic", environment="production"))


@pytest.mark.asyncio
async def test_openai_frontier_payload_preserves_configurable_model():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={'id': 'chatcmpl_fixture', 'object': 'chat.completion', 'created': 123, "model": "gpt-6-astra", "choices": [{'index': 0, 'logprobs': None, "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}]})
    async with create_provider(ProviderConfig(chat_model="gpt-6-astra"), transport=httpx.MockTransport(handle)) as provider:
        result = await provider.chat_completion(MESSAGES)
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(MESSAGES, tools=[TOOL])
    assert result.model == "gpt-6-astra" and "temperature" not in json.loads(calls[0].content)
    assert len(calls) == 1 and caught.value.code == "invalid_configuration"


@pytest.mark.asyncio
async def test_resilience_does_not_convert_truncation_to_stop():
    provider = ResilientProvider(create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=wire(events(reason="max_tokens"))))))
    try:
        chunks = [chunk async for chunk in provider.chat_completion_stream(MESSAGES)]
    finally:
        await provider.aclose()
    assert chunks[-1].finish_reason == "length"


@pytest.mark.asyncio
async def test_cumulative_usage_deltas_and_terminal_are_separate():
    values = events()
    values.insert(-2, {"type": "message_delta", "delta": {"stop_reason": None, "stop_sequence": None},
                       "usage": {"output_tokens": 3}})
    values.insert(-1, {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 7}})
    async with create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=wire(values)))) as provider:
        chunks = [chunk async for chunk in provider.chat_completion_stream(MESSAGES)]
    assert [chunk.usage.completion_tokens for chunk in chunks if chunk.usage] == [1, 3, 5, 7, 7]
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_tool_with_no_arguments_keeps_valid_empty_object():
    values = events(reason="tool_use", tools=True)
    values = [event for event in values if not (event["type"] == "content_block_delta" and event["index"] == 1)]
    async with create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=wire(values)))) as provider:
        chunks = [chunk async for chunk in provider.chat_completion_stream(MESSAGES)]
    calls = [call for chunk in chunks for call in chunk.tool_calls or []]
    assert "".join(call.function.arguments for call in calls) == "{}"
    assert chunks[-1].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_nonstream_cancellation_and_backoff_cancellation_close():
    stream = Stream([], wait=True)
    async with create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as provider:
        task = asyncio.create_task(provider.chat_completion(MESSAGES))
        await asyncio.wait_for(stream.waiting.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stream.closed
    calls = []
    sleeping = asyncio.Event()
    async def sleep(_):
        sleeping.set()
        await asyncio.Event().wait()
    def handle(request):
        calls.append(request)
        return httpx.Response(529, content="private")
    async with create_provider(config(), transport=httpx.MockTransport(handle), sleep=sleep) as provider:
        task = asyncio.create_task(provider.chat_completion(MESSAGES))
        await asyncio.wait_for(sleeping.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(calls) == 1


@pytest.mark.parametrize("values", [
    {"LLM_PROVIDER": "anthropic", "RICK_PROVIDER": "openai"},
    {"LLM_MODEL": "one", "ANTHROPIC_CHAT_MODEL": "two"},
    {"LLM_API_KEY": "private", "ANTHROPIC_API_KEY": "different"},
])
def test_env_alias_conflicts_fail_closed(values):
    with pytest.raises(ProviderConfigurationError) as caught:
        ProviderConfig.from_env({"LLM_PROVIDER": "anthropic", **values})
    assert "private" not in str(caught.value)


def test_canonical_provider_env_also_resolves_native_api():
    cfg = ProviderConfig.from_env({"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "private",
        "LLM_MODEL": MODEL, "RICK_EMBEDDING_PROVIDER": "openai", "EMBEDDING_BASE_URL": "https://embed.invalid/v1",
        "EMBEDDING_API_KEY": "embedding-private", "EMBEDDING_MODEL": "text-embedding-3-small"})
    cfg.validate()
    assert cfg.provider_kind == "anthropic" and cfg.chat_model == MODEL


@pytest.mark.asyncio
async def test_openai_frontier_stream_omits_sampling_parameter():
    calls = []
    def handle(request):
        calls.append(request)
        event = {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, 'usage': None, "model": "gpt-6-astra", "choices": [{'index': 0, 'logprobs': None, "delta": {"content": "answer"}, "finish_reason": "stop"}]}
        return httpx.Response(200, content=("data: " + json.dumps(event) + "\n\ndata: " + json.dumps({"id": "chatcmpl_fixture", "object": "chat.completion.chunk", "created": 123, "model": "gpt-6-astra", "choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}}) + "\n\ndata: [DONE]\n\n"))
    async with create_provider(ProviderConfig(chat_model="gpt-6-astra"), transport=httpx.MockTransport(handle)) as provider:
        chunks = [chunk async for chunk in provider.chat_completion_stream(MESSAGES)]
    assert chunks[-1].finish_reason == "stop" and "temperature" not in json.loads(calls[0].content)


@pytest.mark.asyncio
async def test_nonstream_duplicate_json_keys_and_bad_utf8_are_redacted():
    for raw in (json.dumps(message()).replace('"stop_reason": "end_turn"', '"stop_reason":"end_turn","stop_reason":"refusal"').encode(), b'"\xff"'):
        async with create_provider(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))) as provider:
            with pytest.raises(ProviderError) as caught:
                await provider.chat_completion(MESSAGES)
        assert caught.value.code in {"invalid_json", "malformed_response"}


@pytest.mark.asyncio
async def test_compatible_openai_retains_sampling_defaults():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={'id': 'chatcmpl_fixture', 'object': 'chat.completion', 'created': 123, "model": "gpt-6-custom", "choices": [{'index': 0, 'logprobs': None, "message": {"role": "assistant", "content": "answer"}, "finish_reason": "stop"}]})
    async with create_provider(ProviderConfig(provider_kind="openai_compatible", chat_model="gpt-6-custom"), transport=httpx.MockTransport(handle)) as provider:
        await provider.chat_completion(MESSAGES)
    assert json.loads(calls[0].content)["temperature"] == 0.2
