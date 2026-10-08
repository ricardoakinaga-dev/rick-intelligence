"""Full-response SSE termination, transport bounds, and cancellation controls."""

from __future__ import annotations

import asyncio
import json
from contextlib import aclosing

import httpx
import pytest

import rick_providers.client as provider_module
from rick_providers import OpenAICompatibleClient, ProviderConfig, ProviderError


MODEL = "termination-test"
MESSAGES = [{"role": "user", "content": "bounded request"}]
USAGE = {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, "model": MODEL, "choices": [],
         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
TOOL = {"index": 0, "id": "call-1", "type": "function",
        "function": {"name": "status", "arguments": "{}"}}


def event(text="", reason=None, tools=None):
    delta = {"content": text}
    if tools:
        delta["tool_calls"] = tools
    return {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, 'usage': None, "model": MODEL, "choices": [{'index': 0, 'logprobs': None, "delta": delta, "finish_reason": reason}]}


def wire(*events):
    events = list(events)
    # Historical fixture callers provide choices and DONE. Complete their
    # native accounting seed before byte/tail faults are injected by each test.
    if "[DONE]" in events and not any(isinstance(v, dict) and v.get('usage') is not None for v in events):
        events.insert(events.index("[DONE]"), USAGE)
    return b"".join(
        b"data: " + (value.encode() if isinstance(value, str) else json.dumps(value).encode()) + b"\n\n"
        for value in events
    )


class WireStream(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts = parts
        self.closed = False
        self.reads = 0

    async def __aiter__(self):
        for part in self.parts:
            self.reads += 1
            yield part

    async def aclose(self):
        self.closed = True


def provider_for(stream, *, timeout=1, kind="openai"):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=stream, request=request)

    config = ProviderConfig(
        base_url="https://termination.invalid/v1", chat_model=MODEL,
        timeout=timeout, max_attempts=3, environment="test", provider_kind=kind,
    )
    return OpenAICompatibleClient(config, transport=httpx.MockTransport(handle)), calls


@pytest.mark.asyncio
@pytest.mark.parametrize("split", ["buffered", "separate", "bytewise"])
@pytest.mark.parametrize("tail", [
    event("illegal tail"), event("", "stop"), event(tools=[TOOL]),
    "{truncated", "[DONE]", USAGE,
    {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, "model": MODEL, "choices": [], "usage": {"total_tokens": "bad"}},
], ids=["content", "terminal", "tools", "invalid_json", "duplicate_done", "usage", "bad_usage"])
async def test_data_after_done_is_rejected_before_terminal_delivery(split, tail):
    head = wire(event("complete", "stop"), "[DONE]")
    raw_tail = wire(tail)
    parts = [head + raw_tail] if split == "buffered" else [head, raw_tail]
    if split == "bytewise":
        parts = [bytes([value]) for value in head + raw_tail]
    transport = WireStream(parts)
    provider, calls = provider_for(transport)
    observed = []
    async with provider:
        with pytest.raises(ProviderError) as caught:
            async with aclosing(provider.chat_completion_stream(messages=MESSAGES)) as source:
                async for chunk in source:
                    observed.append(chunk)
    assert caught.value.code == "malformed_response"
    assert caught.value.attempts == 1 and not caught.value.retryable
    assert observed == []
    assert len(calls) == 1 and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("split", [False, True])
async def test_valid_usage_then_done_then_metadata_preserves_stop(split):
    raw = wire(event("complete", "stop"), USAGE, "[DONE]")
    raw += b": keepalive\r\n\r\nevent: message\r\nid: last\r\nretry: 1000\r\n"
    parts = [bytes([value]) for value in raw] if split else [raw]
    transport = WireStream(parts)
    provider, calls = provider_for(transport)
    async with provider:
        chunks = [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    assert len(chunks) == 1
    assert chunks[0].delta == "complete" and chunks[0].finish_reason == "stop"
    assert transport.closed and len(calls) == 1


@pytest.mark.asyncio
async def test_invalid_usage_before_done_is_not_silently_ignored():
    invalid = {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, "model": MODEL, "choices": [], "usage": {"total_tokens": "bad"}}
    transport = WireStream([wire(event("complete", "stop"), invalid, "[DONE]")])
    provider, _ = provider_for(transport)
    async with provider:
        with pytest.raises(ProviderError) as caught:
            [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    assert caught.value.code == "malformed_response" and not caught.value.retryable
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["json", "stream"])
@pytest.mark.parametrize("reason", ["stop", "length", "content_filter", "tool_calls"])
@pytest.mark.parametrize("text", ["", " \t\n"])
async def test_empty_text_without_tools_matches_json_missing_field(path, reason, text):
    calls = []

    def handle(request):
        calls.append(request)
        if path == "json":
            return httpx.Response(200, json={'id': 'chatcmpl_fixture', 'object': 'chat.completion', 'created': 123, "model": MODEL, "choices": [{'index': 0, 'logprobs': None,
                "message": {"role": "assistant", "content": text}, "finish_reason": reason,
            }]}, request=request)
        return httpx.Response(200, content=wire(event(text, reason), "[DONE]"), request=request)

    config = ProviderConfig(base_url="https://termination.invalid/v1", chat_model=MODEL,
                            timeout=1, max_attempts=3, environment="test")
    async with OpenAICompatibleClient(config, transport=httpx.MockTransport(handle)) as provider:
        with pytest.raises(ProviderError) as caught:
            if path == "json":
                await provider.chat_completion(messages=MESSAGES)
            else:
                [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    assert caught.value.code == "missing_field" and not caught.value.retryable
    assert caught.value.attempts == len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["stop", "length", "content_filter", "tool_calls"])
async def test_recognized_nonempty_stream_conclusions_remain_typed(reason):
    tools = [TOOL] if reason == "tool_calls" else None
    transport = WireStream([wire(event("typed conclusion", reason, tools=tools), "[DONE]")])
    provider, _ = provider_for(transport)
    async with provider:
        chunks = [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    assert chunks[-1].finish_reason == reason and chunks[-1].delta == "typed conclusion"


@pytest.mark.asyncio
async def test_tools_only_stream_is_a_valid_typed_tool_conclusion():
    transport = WireStream([wire(event(tools=[TOOL]), event(reason="tool_calls"), "[DONE]")])
    provider, _ = provider_for(transport)
    async with provider:
        chunks = [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    assert chunks[0].tool_calls[0].function.name == "status"
    assert chunks[-1].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_terminal_delivery_waits_for_response_eof():
    reading_tail, release = asyncio.Event(), asyncio.Event()

    class GatedStream(WireStream):
        async def __aiter__(self):
            yield wire(event("provisional"))
            yield wire(event(" final", "stop"), "[DONE]")
            reading_tail.set()
            await release.wait()
            yield b": legal tail\n\n"

    transport = GatedStream([])
    provider, calls = provider_for(transport)
    async with provider:
        async with aclosing(provider.chat_completion_stream(messages=MESSAGES)) as source:
            first = await anext(source)
            assert first.delta == "provisional" and first.finish_reason is None
            pending = asyncio.create_task(anext(source))
            try:
                await asyncio.wait_for(reading_tail.wait(), timeout=1)
                assert not pending.done()
                release.set()
                final = await asyncio.wait_for(pending, timeout=1)
                assert final.delta == " final" and final.finish_reason == "stop"
            finally:
                release.set()
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
    assert transport.closed and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["stall", "keepalive", "incomplete_line"])
async def test_tail_deadline_is_fixed_even_with_keepalives(ending):
    class NeverEndingStream(WireStream):
        async def __aiter__(self):
            yield wire(event("complete", "stop"), "[DONE]")
            if ending == "stall":
                await asyncio.Event().wait()
            while True:
                await asyncio.sleep(0.002)
                self.reads += 1
                yield b": keepalive\n\n" if ending == "keepalive" else b":"

    transport = NeverEndingStream([])
    provider, calls = provider_for(transport, timeout=0.05)
    observed = []
    async with provider:
        with pytest.raises(ProviderError) as caught:
            async with asyncio.timeout(1):
                async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                    observed.append(chunk)
    assert caught.value.code == "timeout" and caught.value.attempts == 1
    assert observed == [] and transport.closed and len(calls) == 1


@pytest.mark.asyncio
async def test_after_done_comment_bytes_still_consume_response_budget(monkeypatch):
    head = wire(event("complete", "stop"), "[DONE]")
    monkeypatch.setattr(provider_module, "MAX_RESPONSE_BYTES", len(head) + 16)
    transport = WireStream([head, b": 12345\n" * 3, b"unread"])
    provider, calls = provider_for(transport)
    async with provider:
        with pytest.raises(ProviderError) as caught:
            [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    assert caught.value.code == "malformed_response" and caught.value.attempts == 1
    assert transport.reads == 2 and transport.closed and len(calls) == 1


@pytest.mark.asyncio
async def test_transport_failure_after_done_cannot_deliver_terminal_or_retry():
    class BrokenTail(WireStream):
        async def __aiter__(self):
            yield wire(event("complete", "stop"), "[DONE]")
            raise httpx.ReadError("synthetic tail failure")

    transport = BrokenTail([])
    provider, calls = provider_for(transport)
    observed = []
    async with provider:
        with pytest.raises(ProviderError) as caught:
            async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                observed.append(chunk)
    assert caught.value.code == "unavailable" and caught.value.attempts == 1
    assert observed == [] and transport.closed and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["malformed", "close"])
async def test_byte_iterator_finalizer_is_awaited_on_parser_exit(ending):
    byte_iterator_closed = asyncio.Event()

    class WatchedResponse(httpx.Response):
        async def aiter_bytes(self, chunk_size=None):
            try:
                if ending == "malformed":
                    yield wire(event("complete", "stop"), "[DONE]", event("illegal tail"))
                else:
                    yield wire(event("provisional"))
                await asyncio.Event().wait()
            finally:
                byte_iterator_closed.set()

    config = ProviderConfig(base_url="https://termination.invalid/v1", chat_model=MODEL,
                            timeout=1, max_attempts=1, environment="test")
    async with OpenAICompatibleClient(config, transport=httpx.MockTransport(
        lambda request: WatchedResponse(200, content=b"", request=request),
    )) as provider:
        async with aclosing(provider.chat_completion_stream(messages=MESSAGES)) as source:
            if ending == "malformed":
                with pytest.raises(ProviderError) as caught:
                    await anext(source)
                assert caught.value.code == "malformed_response"
            else:
                assert (await anext(source)).finish_reason is None
        assert byte_iterator_closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["close", "cancel_tail"])
async def test_early_close_or_cancel_closes_response_without_draining(ending):
    reading_tail = asyncio.Event()

    class OpenStream(WireStream):
        async def __aiter__(self):
            self.reads += 1
            yield wire(event("provisional"))
            self.reads += 1
            yield wire(event("final", "stop"), "[DONE]")
            reading_tail.set()
            await asyncio.Event().wait()

    transport = OpenStream([])
    provider, calls = provider_for(transport)
    async with provider:
        async with aclosing(provider.chat_completion_stream(messages=MESSAGES)) as source:
            first = await anext(source)
            assert first.finish_reason is None
            if ending == "cancel_tail":
                pending = asyncio.create_task(anext(source))
                try:
                    await asyncio.wait_for(reading_tail.wait(), timeout=1)
                finally:
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
    assert transport.closed and len(calls) == 1
    assert transport.reads == (1 if ending == "close" else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("position", ["before", "after"])
@pytest.mark.parametrize("empty_choice", [False, True])
async def test_usage_only_accounting_is_visible_before_done(position, empty_choice):
    events = [event("complete"), event("", "stop")]
    usage_event = {**USAGE, "choices": [{"delta": {}, "finish_reason": None}]} if empty_choice else USAGE
    events.insert(1 if position == "before" else 2, usage_event)
    transport = WireStream([wire(*events, "[DONE]")])
    provider, calls = provider_for(transport, kind="openai_compatible")
    async with provider:
        chunks = []
        if position == "after" and empty_choice:
            with pytest.raises(ProviderError) as caught:
                async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                    chunks.append(chunk)
            assert caught.value.code == "malformed_response"
            assert not any(chunk.finish_reason for chunk in chunks)
            assert len(calls) == 1 and transport.closed
            return
        chunks = [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    assert any(chunk.usage and chunk.usage.total_tokens == 2 for chunk in chunks)
    assert chunks[-1].finish_reason == "stop"
    assert len(calls) == 1 and transport.closed


@pytest.mark.asyncio
async def test_decreasing_usage_trailer_withholds_success():
    high = {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, "model": MODEL, "choices": [], "usage": {
        "prompt_tokens": 1, "completion_tokens": 19999, "total_tokens": 20000}}
    transport = WireStream([wire(event("complete", "stop"), high, USAGE, "[DONE]")])
    provider, calls = provider_for(transport, kind="openai_compatible")
    async with provider:
        chunks = []
        with pytest.raises(ProviderError) as caught:
            async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                chunks.append(chunk)
    assert caught.value.code == "malformed_response"
    assert not any(chunk.finish_reason for chunk in chunks)
    assert transport.closed and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ['{"doc":', '[]', '{"x":1,"x":2}', '{"x":NaN}'])
async def test_completed_stream_tool_arguments_use_strict_json_object_contract(arguments):
    tool = {**TOOL, "function": {"name": "status", "arguments": arguments}}
    transport = WireStream([wire(event(tools=[tool]), event("", "tool_calls"), "[DONE]")])
    provider, calls = provider_for(transport)
    observed = []
    async with provider:
        with pytest.raises(ProviderError) as caught:
            async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                observed.append(chunk)
    assert caught.value.code in {"malformed_response", "invalid_json"}
    assert not any(chunk.finish_reason for chunk in observed)
    assert len(calls) == 1 and transport.closed and not caught.value.retryable


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["id", "type", "name"])
async def test_conflicting_tool_identity_fragments_are_rejected(field):
    conflict = {"index": 0, "function": {"arguments": ""}}
    if field == "name":
        conflict["function"]["name"] = "different"
    else:
        conflict[field] = "different"
    transport = WireStream([wire(event(tools=[TOOL]), event(tools=[conflict]),
                                event("", "tool_calls"), "[DONE]")])
    provider, calls = provider_for(transport)
    async with provider:
        with pytest.raises(ProviderError):
            [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    assert len(calls) == 1 and transport.closed
