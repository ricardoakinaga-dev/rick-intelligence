"""Byte-level UTF-8 validity is required before any terminal publication."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import aclosing

import httpx
import pytest

from rick_providers import OpenAICompatibleClient, ProviderConfig, ProviderError

MODEL = "utf8-boundary"
TEXT = "choose ação 😀 漢字 \ufffd"
MESSAGES = [{"role": "user", "content": "read the envelope"}]
BAD_BYTES = [b"\xff", b"\x80", b"\xc0\xaf", b"\xed\xa0\x80", b"\xf4\x90\x80\x80", b"\xe2(\xa1"]


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def event(text=TEXT, finish="stop"):
    return {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, 'usage': None, "model": MODEL, "choices": [{'index': 0, 'logprobs': None, "delta": {"content": text}, "finish_reason": finish}]}


def frame(value):
    return b"data: " + (value if isinstance(value, bytes) else encode(value)) + b"\r\n\r\n"


def wire():
    return frame(event("provisional ", None)) + frame(event()) + frame(accounting()) + frame(b"[DONE]")


def accounting():
    return {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123,
            'model': MODEL, 'choices': [], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}


class ByteStream(httpx.AsyncByteStream):
    def __init__(self, raw, split):
        self.raw, self.split, self.closed = raw, split, False

    async def __aiter__(self):
        width = {"buffered": len(self.raw), "bytewise": 1, "fragmented": 7}[self.split]
        for offset in range(0, len(self.raw), width):
            yield self.raw[offset:offset + width]

    async def aclose(self):
        self.closed = True


def provider_for(raw, split):
    transport = ByteStream(raw, split)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=transport, request=request)

    provider = OpenAICompatibleClient(
        ProviderConfig(base_url="http://utf8.invalid/v1", chat_model=MODEL,
                       max_attempts=3, timeout=1, environment="test"),
        transport=httpx.MockTransport(handle),
    )
    return provider, transport, calls


def corrupt_at(stage, bad):
    raw = wire()
    if stage == "content":
        return raw.replace(b"choose", b"cho" + bad + b"ose")
    if stage == "comment_before":
        return b": " + bad + b"\r\n\r\n" + raw
    if stage == "comment_after_stop":
        return raw.replace(frame(b"[DONE]"), b": " + bad + b"\r\n" + frame(b"[DONE]"))
    if stage == "comment_after_done":
        return raw + b": " + bad + b"\r\n"
    if stage == "metadata_after_done":
        return raw + b"id: " + bad + b"\r\n"
    usage = {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, "model": MODEL, "choices": [],
             "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1}, "system_fingerprint": "MARKER"}
    return raw.replace(frame(accounting()), frame(usage).replace(b"MARKER", bad))


@pytest.mark.asyncio
@pytest.mark.parametrize("split", ["buffered", "fragmented", "bytewise"])
@pytest.mark.parametrize("stage", ["content", "comment_before", "comment_after_stop",
                                  "comment_after_done", "metadata_after_done", "usage_after_stop"])
@pytest.mark.parametrize("bad", BAD_BYTES)
async def test_invalid_utf8_anywhere_in_sse_never_delivers_terminal(split, stage, bad):
    provider, transport, calls = provider_for(corrupt_at(stage, bad), split)
    observed = []
    async with provider:
        with pytest.raises(ProviderError) as caught:
            async with aclosing(provider.chat_completion_stream(messages=MESSAGES)) as source:
                async for chunk in source:
                    observed.append(chunk)
    assert caught.value.code == "malformed_response" and not caught.value.retryable
    assert caught.value.attempts == 1
    assert all(chunk.finish_reason is None for chunk in observed)
    assert len(calls) == 1 and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("split", ["buffered", "fragmented", "bytewise"])
@pytest.mark.parametrize("stage", ["content", "comment_before", "comment_after_stop",
                                  "comment_after_done", "metadata_after_done", "usage_after_stop"])
async def test_fault_free_pair_at_every_corruption_site(split, stage):
    provider, transport, calls = provider_for(corrupt_at(stage, "\ufffd".encode("utf-8")), split)
    async with provider:
        observed = [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    assert observed[-1].finish_reason == "stop"
    expected = TEXT.replace("choose", "cho\ufffdose") if stage == "content" else TEXT
    assert "".join(chunk.delta for chunk in observed) == "provisional " + expected
    assert len(calls) == 1 and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("split", ["buffered", "fragmented", "bytewise"])
@pytest.mark.parametrize("partial", [b"\xe2", b"\xe2\x82", b"\xf0\x9f\x92"])
async def test_incomplete_utf8_at_eof_after_done_is_malformed(split, partial):
    provider, transport, calls = provider_for(wire() + b": truncated " + partial, split)
    observed = []
    async with provider:
        with pytest.raises(ProviderError) as caught:
            async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                observed.append(chunk)
    assert caught.value.code == "malformed_response" and caught.value.attempts == 1
    assert all(chunk.finish_reason is None for chunk in observed)
    assert len(calls) == 1 and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("split", ["buffered", "fragmented", "bytewise"])
@pytest.mark.parametrize("newline", [b"\n", b"\r", b"\r\n"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
async def test_valid_unicode_replacement_character_bom_and_line_endings(split, newline, bom):
    comments = ": ação 😀 漢字 \ufffd\r\nid: ação\r\n".encode("utf-8")
    raw = bom + (comments + wire() + comments).replace(b"\r\n", newline)
    provider, transport, calls = provider_for(raw, split)
    async with provider:
        observed = [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
    assert "".join(chunk.delta for chunk in observed) == "provisional " + TEXT
    assert [chunk.finish_reason for chunk in observed] == [None, "stop"]
    assert len(calls) == 1 and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("split", ["buffered", "bytewise"])
@pytest.mark.parametrize("bad", BAD_BYTES + [b"\xe2", b"\xe2\x82", b"\xf0\x9f\x92"])
async def test_json_corrupt_utf8_has_same_typed_encoding_failure(split, bad):
    body = encode({'id': 'chatcmpl_fixture', 'object': 'chat.completion', 'created': 123, "model": MODEL, "choices": [{'index': 0, 'logprobs': None, "message": {"role": "assistant", "content": TEXT}, "finish_reason": "stop"}]})
    provider, transport, calls = provider_for(body.replace(b"choose", b"cho" + bad + b"ose"), split)
    async with provider:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(messages=MESSAGES)
    assert caught.value.code == "malformed_response" and not caught.value.retryable
    assert caught.value.attempts == 1 and caught.value.status == 200
    assert len(calls) == 1 and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("split", ["buffered", "bytewise"])
@pytest.mark.parametrize("partial", [b"\xef", b"\xef\xbb"])
async def test_incomplete_initial_bom_is_a_typed_encoding_failure(split, partial):
    provider, transport, calls = provider_for(partial, split)
    async with provider:
        with pytest.raises(ProviderError) as caught:
            async for _ in provider.chat_completion_stream(messages=MESSAGES):
                pytest.fail("a partial BOM cannot contain a completion")
    assert caught.value.code == "malformed_response" and caught.value.status == 200
    assert caught.value.attempts == 1 and not caught.value.retryable
    assert len(calls) == 1 and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["early_close", "cancel_tail", "timeout_tail"])
async def test_partial_character_does_not_force_drain_or_extend_tail_deadline(ending):
    waiting = asyncio.Event()

    class WaitingBytes(httpx.AsyncByteStream):
        closed = False
        reads = 0

        async def __aiter__(self):
            self.reads += 1
            yield frame(event("provisional ", None))
            self.reads += 1
            yield frame(event()) + frame(b"[DONE]") + b": partial \xf0\x9f\x92"
            waiting.set()
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    transport, calls = WaitingBytes(), []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=transport, request=request)

    provider = OpenAICompatibleClient(
        ProviderConfig(base_url="http://utf8.invalid/v1", chat_model=MODEL,
                       max_attempts=3, timeout=0.05, environment="test"),
        transport=httpx.MockTransport(handle),
    )
    async with provider:
        async with aclosing(provider.chat_completion_stream(messages=MESSAGES)) as source:
            assert (await anext(source)).finish_reason is None
            if ending == "cancel_tail":
                pending = asyncio.create_task(anext(source))
                try:
                    await asyncio.wait_for(waiting.wait(), 1)
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                finally:
                    if not pending.done():
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
            elif ending == "timeout_tail":
                with pytest.raises(ProviderError) as caught:
                    await asyncio.wait_for(anext(source), 1)
                assert caught.value.code == "timeout" and caught.value.attempts == 1
    assert len(calls) == 1 and transport.closed
    assert transport.reads == (1 if ending == "early_close" else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["json", "sse"])
@pytest.mark.parametrize("fault", ["healthy", "content", "comment_before", "comment_after_done", "incomplete_tail"])
async def test_real_socket_utf8_rejection_and_healthy_pair(path, fault):
    if path == "sse":
        raw = wire() if fault == "healthy" else (
            wire() + b": incomplete \xf0\x9f\x92" if fault == "incomplete_tail" else corrupt_at(fault, b"\xff")
        )
    else:
        raw = encode({'id': 'chatcmpl_fixture', 'object': 'chat.completion', 'created': 123, "model": MODEL, "choices": [{'index': 0, 'logprobs': None, "message": {"role": "assistant", "content": TEXT}, "finish_reason": "stop"}]})
        if fault == "content":
            raw = raw.replace(b"choose", b"cho\xffose")
        elif fault != "healthy":
            raw += b"\xf0\x9f\x92" if fault == "incomplete_tail" else b"\xff"
    finished = asyncio.Event()
    requests, tasks = [], set()

    async def serve(reader, writer):
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            length = int(re.search(rb"(?i)content-length:\s*(\d+)", header).group(1))
            requests.append(json.loads(await reader.readexactly(length)))
            writer.write(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n")
            for offset in range(0, len(raw), 7):
                writer.write(raw[offset:offset + 7])
                await writer.drain()
                await asyncio.sleep(0)
        except (BrokenPipeError, ConnectionResetError):
            # A malformed response can be rejected before the server finishes
            # writing. Peer disconnect is expected; provider assertions follow.
            assert fault != "healthy"
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                assert fault != "healthy"
            finally:
                finished.set()

    def accept(reader, writer):
        task = asyncio.create_task(serve(reader, writer))
        tasks.add(task)

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    provider = OpenAICompatibleClient(ProviderConfig(
        base_url=f"http://127.0.0.1:{port}/v1", chat_model=MODEL,
        max_attempts=3, timeout=0.5, environment="test",
    ))
    observed = []

    async def deliver():
        if path == "json":
            return await provider.chat_completion(messages=MESSAGES)
        async for chunk in provider.chat_completion_stream(messages=MESSAGES):
            observed.append(chunk)
        return observed[-1]

    try:
        async with provider:
            if fault == "healthy":
                result = await deliver()
                assert result.finish_reason == "stop"
                assert (result.content if path == "json" else "".join(chunk.delta for chunk in observed)) == (
                    TEXT if path == "json" else "provisional " + TEXT
                )
            else:
                with pytest.raises(ProviderError) as caught:
                    await deliver()
                assert caught.value.code == "malformed_response" and not caught.value.retryable
                assert caught.value.attempts == 1 and caught.value.status == 200
                assert all(chunk.finish_reason is None for chunk in observed)
        await asyncio.wait_for(finished.wait(), 1)
        assert len(requests) == 1
    finally:
        server.close()
        await server.wait_closed()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert results == [None], results
