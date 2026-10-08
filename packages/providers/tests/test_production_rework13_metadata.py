"""Public memory-transport regressions for native metadata and citation bounds.

Unicode citation units are unspecified in the official Chat Completions schema;
these tests preserve Unicode responses without selecting an offset convention.
"""

import copy
import json

import httpx
import pytest

from rick_providers import AnthropicMessagesClient, OpenAICompatibleClient, ProviderConfig, ProviderError


MESSAGES = [{"role": "user", "content": "hello"}]
CORRELATION = "metadata-fixture"
USAGE = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}


def config(kind):
    return ProviderConfig(provider_kind=kind, environment="production",
                          api_key="synthetic-fixture-key", base_url="https://fixture.invalid/v1",
                          embedding_provider_kind="openai", embedding_api_key="synthetic-embedding-fixture",
                          embedding_base_url="https://embedding.invalid/v1",
                          chat_model="claude-sonnet-4-5" if kind == "anthropic" else "gpt-4o-mini",
                          max_attempts=3, retry_base_delay=0, timeout=1)


def completion(text="ok", **extra):
    return dict(id="chatcmpl_fixture", object="chat.completion", created=0,
                model="gpt-4o-mini", choices=[dict(index=0, logprobs=None,
                message=dict(role="assistant", content=text), finish_reason="stop")],
                usage=copy.deepcopy(USAGE), **extra)


def frame(delta=None, finish=None, **extra):
    return dict(id="chatcmpl_fixture", object="chat.completion.chunk", created=0,
                model="gpt-4o-mini", choices=[dict(index=0, delta=delta or {},
                finish_reason=finish)], usage=None, **extra)


def trailer(**extra):
    return dict(id="chatcmpl_fixture", object="chat.completion.chunk", created=0,
                model="gpt-4o-mini", choices=[], usage=copy.deepcopy(USAGE), **extra)


def openai_wire(events):
    return b"".join(("data: " + json.dumps(event) + "\n\n").encode() for event in events) + b"data: [DONE]\n\n"


def message(**extra):
    return dict(id="msg_fixture", type="message", role="assistant", model="claude-sonnet-4-5",
                content=[dict(type="text", text="ok")], stop_reason="end_turn", stop_sequence=None,
                usage=dict(input_tokens=3, output_tokens=2), **extra)


def anthropic_wire(extra):
    start = message(**extra)
    start.update(content=[], stop_reason=None, usage=dict(input_tokens=3, output_tokens=0))
    events = [dict(type="message_start", message=start),
              dict(type="content_block_start", index=0, content_block=dict(type="text", text="")),
              dict(type="content_block_delta", index=0, delta=dict(type="text_delta", text="ok")),
              dict(type="content_block_stop", index=0),
              dict(type="message_delta", delta=dict(stop_reason="end_turn", stop_sequence=None),
                   usage=dict(output_tokens=2)), dict(type="message_stop")]
    return b"".join((f"event: {event['type']}\ndata: {json.dumps(event)}\n\n").encode() for event in events)


async def public_response(kind, mode, payload, healthy, text="ok"):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    requests, chunks = [], []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=raw)

    cls = AnthropicMessagesClient if kind == "anthropic" else OpenAICompatibleClient
    async with cls(config(kind), transport=httpx.MockTransport(handle)) as provider:
        async def invoke():
            if mode == "buffer":
                return await provider.chat_completion(messages=MESSAGES, correlation_id=CORRELATION)
            async for chunk in provider.chat_completion_stream(messages=MESSAGES, correlation_id=CORRELATION):
                chunks.append(chunk)
            return chunks[-1]

        if healthy:
            result = await invoke()
            assert result.finish_reason == "stop" and result.correlation_id == CORRELATION
            assert result.usage.total_tokens == 5
            assert (result.content if mode == "buffer" else "".join(c.delta for c in chunks)) == text
            if mode == "stream":
                assert sum(c.finish_reason is not None for c in chunks) == 1
        else:
            with pytest.raises(ProviderError) as caught:
                await invoke()
            assert caught.value.code == "malformed_response"
            assert caught.value.attempts == 1 and caught.value.correlation_id == CORRELATION
            assert not any(c.finish_reason is not None for c in chunks)
    assert len(requests) == 1 and requests[0].method == "POST"
    assert requests[0].headers["X-Correlation-ID"] == CORRELATION


async def public_health(kind, payload, healthy):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    cls = AnthropicMessagesClient if kind == "anthropic" else OpenAICompatibleClient
    async with cls(config(kind), transport=httpx.MockTransport(handle)) as provider:
        assert await provider.health_check() is healthy
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.path == ("/v1/models/claude-sonnet-4-5" if kind == "anthropic" else "/v1/models")


def model_item(**extra):
    return dict(id="gpt-4o-mini", object="model", created=0, owned_by="openai", **extra)


def health_cases():
    valid = dict(object="list", data=[model_item(shutdown_date=None, future={"unused": True})])
    cases = [(valid, True), (dict(object="list", data=[dict(model_item(), created=1730000000)]), True)]
    for field in ("object", "created", "owned_by", "id"):
        item = model_item()
        item.pop(field)
        cases.append((dict(object="list", data=[item]), False))
    for field, values in {"object": ["list", None, True], "created": [True, -1, "0", None, 1.5],
                          "owned_by": [{}, None, 1, False]}.items():
        cases.extend((dict(object="list", data=[dict(model_item(), **{field: value})]), False) for value in values)
    cases.extend([(dict(data=[model_item()]), False), (dict(object="model", data=[model_item()]), False),
                  (dict(object="list", data=[model_item(), dict(id="another")]), False)])
    return cases


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,healthy", health_cases())
async def test_openai_model_health_native_required_metadata(payload, healthy):
    await public_health("openai", payload, healthy)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [dict(status="ok", custom={}), dict(data=[dict(id="gpt-4o-mini")]),
                                    dict(data=[dict(model="gpt-4o-mini", custom=True)]),
                                    dict(object="custom", data=[dict(id="gpt-4o-mini", owned_by={})])])
async def test_gateway_health_preserves_omission_and_custom_fields(payload):
    await public_health("openai_compatible", payload, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["max_tokens", "max_input_tokens"])
@pytest.mark.parametrize("value,healthy", [(None, True), (0, True), (4096, True), (-1, False),
                                          (True, False), (1.5, False), ("4096", False)])
async def test_anthropic_health_token_limits(field, value, healthy):
    payload = dict(id="claude-sonnet-4-5", type="model", display_name="Claude",
                   created_at="1970-01-01T00:00:00Z", capabilities=None, future={"unused": True})
    payload[field] = value
    await public_health("anthropic", payload, healthy)


TIMESTAMPS = [("1970-01-01T00:00:00Z", True), ("2024-02-29t12:34:56.123456789z", True),
              ("2026-10-04T00:00:00-03:30", True), ("2026-10-04T00:00:00+00:00", True),
              ("2026-10-04X00:00:00Z", False), ("20261004T00:00:00Z", False),
              ("2026-10-04T00:00:00+01:02:03", False), ("2026-10-04 00:00:00Z", False),
              ("2026-10-04T00:00:00+0300", False), ("2026-02-30T00:00:00Z", False),
              ("2026-10-04T24:00:00Z", False), ("2026-10-04T00:00:00", False)]


@pytest.mark.asyncio
@pytest.mark.parametrize("timestamp,healthy", TIMESTAMPS)
async def test_anthropic_model_datetime(timestamp, healthy):
    await public_health("anthropic", dict(id="claude-sonnet-4-5", type="model", display_name="Claude",
                                         created_at=timestamp), healthy)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["buffer", "stream"])
@pytest.mark.parametrize("timestamp,healthy", TIMESTAMPS + [(None, True)])
async def test_anthropic_container_uses_same_datetime_gate(mode, timestamp, healthy):
    extra = dict(container=None if timestamp is None else dict(id="container_fixture", expires_at=timestamp))
    payload = message(**extra) if mode == "buffer" else anthropic_wire(extra)
    await public_response("anthropic", mode, payload, healthy)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "openai_compatible"])
@pytest.mark.parametrize("mode", ["buffer", "stream", "trailer"])
@pytest.mark.parametrize("tier", [None, "auto", "default", "flex", "scale", "priority", "fast", "bogus"])
async def test_supplied_service_tier(kind, mode, tier):
    metadata = dict(service_tier=tier, system_fingerprint=None, metadata={"fixture": "value"}, moderation=None)
    if mode == "buffer":
        payload = completion(**metadata)
    else:
        payload = openai_wire([frame(dict(content="o"), **(metadata if mode == "stream" else {})),
                               frame(dict(content="k"), "stop"),
                               trailer(**(metadata if mode == "trailer" else {}))])
    await public_response(kind, "buffer" if mode == "buffer" else "stream", payload,
                          tier != "bogus" or kind != "openai")


def citation(start, end):
    return dict(type="url_citation", url_citation=dict(start_index=start, end_index=end,
                title="fixture", url="https://source.invalid"))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "openai_compatible"])
@pytest.mark.parametrize("mode", ["buffer", "early", "delta", "terminal"])
@pytest.mark.parametrize("text,start,end,healthy", [("ok", 0, 2, True), ("ok", 1, 2, True),
    ("ok", 100, 200, False), ("ok", 0, 3, False), ("ok", 3, 3, False),
    ("ok", -1, 2, False), ("ok", 2, 1, False), ("ok", True, 2, False),
    ("ok", 0, False, False), ("😀", 0, 2, True), ("é", 0, 2, True), ("e\u0301", 0, 2, True)])
async def test_citation_ranges_use_completed_message(kind, mode, text, start, end, healthy):
    annotations = dict(annotations=[citation(start, end)])
    if mode == "buffer":
        payload = completion(text)
        payload["choices"][0]["message"].update(annotations)
    else:
        first = dict(content=text[:1])
        terminal = dict(content=text[1:])
        if mode == "delta":
            first.update(annotations)
        if mode == "terminal":
            terminal.update(annotations)
        events = ([frame(annotations)] if mode == "early" else []) + [frame(first), frame(terminal, "stop"), trailer()]
        payload = openai_wire(events)
    await public_response(kind, "buffer" if mode == "buffer" else "stream", payload, healthy, text)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["buffer", "stream"])
async def test_null_annotations_and_native_metadata_are_optional(mode):
    if mode == "buffer":
        payload = completion(service_tier=None, metadata=None, system_fingerprint=None)
        payload["choices"][0]["message"]["annotations"] = None
    else:
        payload = openai_wire([frame(dict(content="ok", annotations=None), "stop"), trailer()])
    await public_response("openai", mode, payload, True)


@pytest.mark.asyncio
async def test_stream_checks_all_citations_including_ignored_frames():
    payload = openai_wire([frame(dict(annotations=[citation(100, 200)])),
                          frame(dict(content="ok", annotations=[citation(0, 2)]), "stop"), trailer()])
    await public_response("openai", "stream", payload, False)
