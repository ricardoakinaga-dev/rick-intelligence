"""Local, nonbillable discriminators for PROVIDER-01 through PROVIDER-09."""
import asyncio
import copy
import json
import time

import httpx
import pytest

from rick_providers import (AnthropicMessagesClient, OpenAICompatibleClient, ProviderConfig,
                            ProviderConfigurationError, ProviderError, ResilientProvider)

MESSAGES = [{"role": "user", "content": "hello"}]
TOOL = {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}
USAGE = {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12,
         "prompt_tokens_details": {"cached_tokens": 3, "audio_tokens": 0},
         "completion_tokens_details": {"reasoning_tokens": 2, "audio_tokens": 0,
                                       "accepted_prediction_tokens": 0, "rejected_prediction_tokens": 0}}


def config(kind="openai", **overrides):
    values = dict(provider_kind=kind, environment="production", api_key="chat-secret",
                  base_url="https://chat.invalid/v1", chat_model="chat-model",
                  embedding_provider_kind="openai", embedding_api_key="embed-secret",
                  embedding_base_url="https://embed.invalid/v1", embedding_dimensions=3,
                  max_attempts=1, timeout=0.04)
    values.update(overrides)
    return ProviderConfig(**values)


def body(kind="openai"):
    if kind == "anthropic":
        return dict(id="msg_1", type="message", role="assistant", model="chat-model",
                    content=[{"type": "text", "text": "hello"}], stop_reason="end_turn",
                    stop_sequence=None, usage={"input_tokens": 8, "output_tokens": 4})
    return dict(id="chatcmpl_fixture", object="chat.completion", created=123,
                model="chat-model", choices=[dict(index=0, logprobs=None, message={"role": "assistant", "content": "hello"},
                                                 finish_reason="stop")], usage=copy.deepcopy(USAGE))


def openai_completion_wire(payload):
    payload = copy.deepcopy(payload)
    usage = payload.pop("usage", None)
    payload['object'] = 'chat.completion.chunk'
    payload['usage'] = None
    events = [payload]
    if usage is not None:
        events.append({'id': payload['id'], 'object': 'chat.completion.chunk', 'created': payload['created'], "model": payload["model"], "choices": [], "usage": usage})
    return b''.join(f'data: {json.dumps(event)}\n\n'.encode() for event in events) + b'data: [DONE]\n\n'


def wire(kind="openai"):
    if kind == "anthropic":
        msg = body(kind); msg.update(content=[], stop_reason=None)
        events = [("message_start", {"type": "message_start", "message": msg}),
                  ("content_block_start", {"type": "content_block_start", "index": 0,
                                            "content_block": {"type": "text", "text": ""}}),
                  ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                            "delta": {"type": "text_delta", "text": "hello"}}),
                  ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                  ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                      "usage": {"output_tokens": 4}}),
                  ("message_stop", {"type": "message_stop"})]
        return ''.join(f'event: {name}\ndata: {json.dumps(data)}\n\n' for name, data in events).encode()
    data = dict(id="chatcmpl_fixture", object="chat.completion.chunk", created=123,
                model="chat-model", choices=[dict(index=0, delta={"role": "assistant", "content": "hello"},
                                                finish_reason="stop")], usage=USAGE)
    return openai_completion_wire(data)


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, raw, *, delay=0, drip=False):
        self.raw, self.delay, self.drip = raw, delay, drip
        self.closed = False

    async def __aiter__(self):
        if self.drip:
            for value in self.raw:
                await asyncio.sleep(self.delay)
                yield bytes([value])
        else:
            await asyncio.sleep(self.delay)
            yield self.raw

    async def aclose(self):
        await asyncio.sleep(0)
        self.closed = True


def adapter(kind, cfg, **kwargs):
    return (AnthropicMessagesClient if kind == "anthropic" else OpenAICompatibleClient)(cfg, **kwargs)


async def invoke(provider, operation):
    if operation == "chat":
        return await provider.chat_completion(messages=MESSAGES)
    if operation == "embed":
        return await provider.get_embedding("hello")
    if operation == "stream":
        return [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    return await provider.health_check()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "anthropic"])
@pytest.mark.parametrize("operation", ["chat", "embed", "stream", "health"])
@pytest.mark.parametrize("auth", [None, httpx.BasicAuth("default-user", "default-secret")])
async def test_injected_defaults_never_cross_operation_credentials(kind, operation, auth):
    captured = []
    def handle(request):
        captured.append(request)
        if operation == "embed":
            raw = dict(model="text-embedding-3-small", data=[dict(index=0, embedding=[1, 2, 3])])
        elif operation == "health":
            raw = dict(type="model", id="chat-model", display_name="Claude test model",
                       created_at="1970-01-01T00:00:00Z") if kind == "anthropic" else dict(
                           object="list", data=[dict(id="chat-model", object="model", created=0, owned_by="fixture")])
        elif operation == "stream":
            return httpx.Response(200, content=wire(kind))
        else:
            raw = body(kind)
        return httpx.Response(200, json=raw)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), auth=auth,
                                cookies={"secret-cookie": "ambient-cookie"},
                                headers={"Authorization": "Bearer ambient-secret", "x-api-key": "ambient-native",
                                         "anthropic-version": "ambient-version", "x-custom-secret": "ambient-custom"}) as client:
        original = dict(client.headers)
        provider = adapter(kind, config(kind), client=client)
        result = await invoke(provider, operation)
        if operation == "health":
            assert result is True
        request = captured[0]
        native = kind == "anthropic" and operation != "embed"
        assert request.headers.get("Authorization") == (None if native else "Bearer " + ("embed-secret" if operation == "embed" else "chat-secret"))
        assert request.headers.get("x-api-key") == ("chat-secret" if native else None)
        assert request.headers.get("anthropic-version") == ("2023-06-01" if native else None)
        assert "cookie" not in request.headers and "x-custom-secret" not in request.headers
        assert request.headers["X-Correlation-ID"]
        assert request.extensions["timeout"]["read"] == 0.04
        assert dict(client.headers) == original
        await provider.aclose()
        assert not client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "anthropic"])
@pytest.mark.parametrize("operation", ["chat", "embed", "stream", "health"])
@pytest.mark.parametrize("drip", [False, True])
async def test_total_deadline_includes_headers_and_entire_body(kind, operation, drip):
    raw = wire(kind) if operation == "stream" else json.dumps(body(kind)).encode()
    stream = TrackedStream(raw, delay=0.008 if drip else 0.08, drip=drip)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as client:
        provider = adapter(kind, config(kind, timeout=0.025), client=client)
        started = time.monotonic()
        if operation == "health":
            assert await invoke(provider, operation) is False
        else:
            with pytest.raises(ProviderError) as caught:
                await invoke(provider, operation)
            assert caught.value.code == "timeout" and caught.value.attempts == 1
        assert time.monotonic() - started < 0.075
        assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["chat", "stream"])
async def test_native_nested_usage_normalizes_only_totals(operation):
    async with adapter("openai", config(), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=wire() if operation == "stream" else json.dumps(body()).encode()))) as provider:
        result = await invoke(provider, operation)
    usage = result[-1].usage if operation == "stream" else result.usage
    assert usage.model_dump() == {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"prompt_tokens_details": {"cached_tokens": True}},
    {"completion_tokens_details": {"reasoning_tokens": -1}},
    {"prompt_tokens_details": {"unknown": 1}},
    {"completion_tokens_details": 2}, {"total_tokens": 20},
])
@pytest.mark.parametrize("operation", ["chat", "stream"])
async def test_invalid_nested_usage_and_totals_fail_closed(invalid, operation):
    payload = body(); payload["usage"].update(invalid)
    if operation == "stream":
        payload["choices"][0]["delta"] = payload["choices"][0].pop("message")
        raw = openai_completion_wire(payload)
    else:
        raw = json.dumps(payload).encode()
    async with adapter("openai", config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))) as provider:
        with pytest.raises(ProviderError) as caught:
            await invoke(provider, operation)
        assert caught.value.code == "malformed_response"


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"messages": [{"role": "assistant", "content": "hello", "tool_calls": [TOOL]}]},
    {"messages": [{"role": "tool", "content": "hello", "tool_call_id": "id"}]},
    {"messages": [{"role": "user", "content": "hello", "unknown": 1}]},
    {"tools": [{"type": "function", "unknown": 1, "function": {"name": "f"}}]},
    {"tools": [{"type": "function", "function": {"name": "f", "unknown": 1}}]},
    {"tools": [{"type": "function", "function": {"name": "f"}}] * 2},
    {"response_format": {"type": "text", "unknown": 1}},
    {"response_format": {"type": "unknown"}},
    {"response_format": {"type": "json_schema", "json_schema": {"name": "reply", "schema": {}, "unknown": 1}}},
])
@pytest.mark.parametrize("operation", ["chat", "stream"])
async def test_unsupported_mappings_reject_before_network(kwargs, operation):
    calls = []
    async with adapter("openai", config(), transport=httpx.MockTransport(lambda request: calls.append(request))) as provider:
        options = dict(messages=MESSAGES); options.update(kwargs)
        with pytest.raises(ProviderError) as caught:
            if operation == "stream":
                [chunk async for chunk in provider.chat_completion_stream(**options)]
            else:
                await provider.chat_completion(**options)
        assert caught.value.attempts == 0 and not calls


@pytest.mark.asyncio
async def test_strict_tool_schema_survives_serialization():
    captured = []
    tool = dict(type="function", function=dict(name="lookup", strict=True, description="Read a record",
                parameters={"type": "object", "properties": {}, "additionalProperties": False}))
    def handler(request):
        captured.append(json.loads(request.content)); return httpx.Response(200, json=body())
    async with adapter("openai", config(), transport=httpx.MockTransport(handler)) as provider:
        await provider.chat_completion(messages=MESSAGES, tools=[tool])
    assert captured[0]["tools"] == [tool]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["wrong-role", "missing-role", "duplicate-id", "stop-tools", "tool-reason-no-tools"])
@pytest.mark.parametrize("operation", ["chat", "stream"])
async def test_chat_roles_tool_identities_and_stop_semantics(case, operation):
    payload = body(); choice = payload["choices"][0]; message = choice["message"]
    if case == "wrong-role":
        message["role"] = "user"
    elif case == "missing-role":
        message.pop("role")
        if operation == "stream":
            # Stream role is optional for subsequent chunks, so test an invalid role instead.
            message["role"] = "tool"
    elif case == "tool-reason-no-tools":
        choice["finish_reason"] = "tool_calls"
    else:
        message["tool_calls"] = [copy.deepcopy(TOOL)]
        if case == "duplicate-id":
            message["tool_calls"].append(copy.deepcopy(TOOL)); choice["finish_reason"] = "tool_calls"
    if operation == "stream":
        choice["delta"] = choice.pop("message")
        for index, call in enumerate(message.get("tool_calls", [])):
            call["index"] = index
        raw = f'data: {json.dumps(payload)}\n\ndata: [DONE]\n\n'.encode()
    else:
        raw = json.dumps(payload).encode()
    async with adapter("openai", config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))) as provider:
        with pytest.raises(ProviderError) as caught:
            await invoke(provider, operation)
        assert caught.value.code == "malformed_response"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "anthropic"])
async def test_resilience_aclose_awaits_underlying_response_cleanup(kind):
    if kind == "openai":
        event = dict(id="chatcmpl_fixture", object="chat.completion.chunk", created=123, usage=None,
                     model="chat-model", choices=[dict(index=0, delta={"content": "hello"}, finish_reason=None)])
        raw = f'data: {json.dumps(event)}\n\n'.encode()
    else:
        raw = wire(kind)
    stream = TrackedStream(raw)
    async with adapter(kind, config(kind), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as provider:
        wrapped = ResilientProvider(provider)
        iterator = wrapped.chat_completion_stream(messages=MESSAGES)
        await anext(iterator)
        await iterator.aclose()
        assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["error", "extra", "index", "missing-index", "boolean-index"])
async def test_embedding_success_identity_is_exact(case):
    payload = dict(model="text-embedding-3-small", data=[dict(index=0, embedding=[1, 2, 3])])
    if case == "error": payload["error"] = {"message": "synthetic"}
    if case == "extra": payload["data"].append(dict(index=1, embedding=[3, 2, 1]))
    if case == "index": payload["data"][0]["index"] = 7
    if case == "missing-index": payload["data"][0].pop("index")
    if case == "boolean-index": payload["data"][0]["index"] = False
    async with adapter("openai", config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as provider:
        with pytest.raises(ProviderError) as caught:
            await provider.get_embedding("hello")
        assert caught.value.code == "malformed_response"


@pytest.mark.parametrize("kind", ["openai", "anthropic", "openai_compatible"])
@pytest.mark.parametrize("endpoint", ["chat", "embed"])
@pytest.mark.parametrize("environment", ["production", "prod", "live"])
def test_remote_plaintext_production_credentials_are_rejected(kind, endpoint, environment):
    overrides = {"base_url" if endpoint == "chat" else "embedding_base_url": "http://remote.invalid/v1"}
    with pytest.raises(ProviderConfigurationError):
        config(kind, environment=environment, **overrides).validate()


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_native_plaintext_loopback_is_not_a_tls_proof(kind):
    with pytest.raises(ProviderConfigurationError):
        config(kind, base_url="http://127.0.0.1/v1", api_key=None).validate()


def test_only_explicit_dev_credential_free_loopback_compatible_gateway_allows_http():
    with pytest.raises(ProviderConfigurationError):
        config("openai_compatible", api_key=None, base_url="http://127.0.0.1:8080/v1").validate()
    config("openai_compatible", environment="dev", api_key=None, base_url="http://127.0.0.1:8080/v1").validate()
    with pytest.raises(ProviderConfigurationError):
        config("openai_compatible", base_url="http://localhost/v1").validate()
    config(environment="test", base_url="http://remote.invalid/v1").validate()


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_common_retry_environment_and_constructor_ms_aliases(kind):
    values = {"LLM_PROVIDER": kind, "RICK_ENV": "test", "OPENAI_MAX_ATTEMPTS": "1",
              "OPENAI_RETRY_DELAY_MS": "1234", "OPENAI_MAX_BACKOFF_MS": "2345"}
    cfg = ProviderConfig.from_env(values)
    assert (cfg.max_attempts, cfg.retry_base_delay, cfg.max_backoff_delay) == (1, 1.234, 2.345)
    cfg = config(kind, retry_delay_ms=1234, max_backoff_ms=2345)
    cfg.validate()
    assert (cfg.retry_base_delay, cfg.max_backoff_delay) == (1.234, 2.345)


@pytest.mark.parametrize("override", [dict(max_attempts=0), dict(max_attempts=11), dict(max_attempts=True),
    dict(retry_base_delay=float('nan')), dict(max_backoff_delay=float('inf')),
    dict(retry_base_delay=121), dict(max_backoff_delay=121)])
def test_retry_policy_bounds(override):
    with pytest.raises(ProviderConfigurationError):
        config(**override).validate()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "anthropic"])
@pytest.mark.parametrize("operation", ["chat", "embed", "stream", "health"])
async def test_injected_transport_header_wait_is_bounded(kind, operation):
    cancelled = False
    async def handle(request):
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True
    async with adapter(kind, config(kind, timeout=0.02), transport=httpx.MockTransport(handle)) as provider:
        if operation == "health":
            assert await invoke(provider, operation) is False
        else:
            with pytest.raises(ProviderError) as caught:
                await invoke(provider, operation)
            assert caught.value.code == "timeout"
    assert cancelled


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "anthropic"])
async def test_stream_timeout_never_cancels_consumer_between_yields(kind):
    if kind == "openai":
        event = dict(id="chatcmpl_fixture", object="chat.completion.chunk", created=123, usage=None,
                     model="chat-model", choices=[dict(index=0, delta={"content": "hello"}, finish_reason=None)])
        raw = f'data: {json.dumps(event)}\n\n'.encode()
    else:
        raw = wire(kind)
    class StalledTail(TrackedStream):
        async def __aiter__(self):
            yield self.raw
            # Pausing the caller is free; a subsequent wire stall spends the
            # remaining cumulative I/O budget and must still close the response.
            await asyncio.Event().wait()

    stream = StalledTail(raw)
    async with adapter(kind, config(kind, timeout=0.02), transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as provider:
        iterator = provider.chat_completion_stream(messages=MESSAGES)
        await anext(iterator)
        await asyncio.sleep(0.04)
        assert asyncio.current_task().cancelling() == 0
        with pytest.raises(ProviderError) as caught:
            async for chunk in iterator:
                assert chunk.finish_reason is None
        assert caught.value.code == "timeout"
        assert stream.closed


@pytest.mark.asyncio
async def test_supported_strict_response_schema_is_preserved():
    captured = []
    fmt = {"type": "json_schema", "json_schema": {"name": "reply", "description": "Structured reply",
           "schema": {"type": "object", "properties": {}, "additionalProperties": False}, "strict": True}}
    def handle(request):
        payload = body(); payload["choices"][0]["message"]["content"] = "{}"
        captured.append(json.loads(request.content)); return httpx.Response(200, json=payload)
    async with adapter("openai", config(), transport=httpx.MockTransport(handle)) as provider:
        await provider.chat_completion(messages=MESSAGES, response_format=fmt)
    assert captured[0]["response_format"] == fmt


@pytest.mark.parametrize("override", [dict(retry_delay_ms=True), dict(max_backoff_ms=False),
    dict(retry_delay_ms=float('nan')), dict(max_backoff_ms=float('inf'))])
def test_invalid_ms_aliases_are_safe(override):
    with pytest.raises(ProviderConfigurationError):
        config(**override).validate()
