"""Caller pauses are outside the cumulative cooperative adapter I/O budget."""
import asyncio
import json

import httpx
import pytest

from rick_providers import ProviderError
from test_production_rework8 import adapter, config, events, MESSAGES


class Frames(httpx.AsyncByteStream):
    def __init__(self, kind, delay):
        self.kind, self.delay, self.closes = kind, delay, 0

    async def __aiter__(self):
        for frame in events(self.kind):
            await asyncio.sleep(self.delay)
            prefix = f"event: {frame['type']}\n" if self.kind == 'anthropic' else ''
            yield f'{prefix}data: {json.dumps(frame)}\n\n'.encode()
        if self.kind != 'anthropic':
            yield b'data: [DONE]\n\n'

    async def aclose(self):
        self.closes += 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible', 'anthropic'])
@pytest.mark.parametrize('pause', [0, .16])
@pytest.mark.parametrize('io_delay,header_delay,timeout', [(0, 0, .12), (.015, 0, .12)])
async def test_consumer_pause_does_not_spend_io_budget(kind, pause, io_delay, header_delay, timeout):
    stream = Frames(kind, io_delay)
    requests, chunks = [], []

    async def respond(request):
        requests.append(request)
        await asyncio.sleep(header_delay)
        return httpx.Response(200, stream=stream)

    async with adapter(kind)(config(kind, timeout=timeout, max_attempts=1),
                             transport=httpx.MockTransport(respond)) as provider:
        async for chunk in provider.chat_completion_stream(messages=MESSAGES):
            chunks.append(chunk)
            if chunk.delta:
                await asyncio.sleep(pause)
    assert ''.join(c.delta for c in chunks) == 'olá'
    assert sum(c.finish_reason is not None for c in chunks) == 1
    assert chunks[-1].usage.total_tokens == 5
    assert len(requests) == stream.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible', 'anthropic'])
@pytest.mark.parametrize('pause', [0, .16])
@pytest.mark.parametrize('io_delay,header_delay', [(.055, 0), (.055, .065)])
async def test_pauses_do_not_reset_cumulative_io_budget(kind, pause, io_delay, header_delay):
    stream = Frames(kind, io_delay)
    requests, chunks = [], []

    async def respond(request):
        requests.append(request)
        await asyncio.sleep(header_delay)
        return httpx.Response(200, stream=stream)

    async with adapter(kind)(config(kind, timeout=.12, max_attempts=1),
                             transport=httpx.MockTransport(respond)) as provider:
        with pytest.raises(ProviderError) as caught:
            async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                chunks.append(chunk)
                if chunk.delta:
                    await asyncio.sleep(pause)
        assert caught.value.code == 'timeout'
        assert caught.value.attempts == 1
    assert not any(c.finish_reason for c in chunks)
    assert len(requests) == stream.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible', 'anthropic'])
async def test_closing_during_consumer_pause_closes_response(kind):
    stream = Frames(kind, 0)
    async with adapter(kind)(config(kind, timeout=.03, max_attempts=1),
                             transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))) as provider:
        iterator = provider.chat_completion_stream(messages=MESSAGES)
        chunk = await anext(iterator)
        while not chunk.delta:
            chunk = await anext(iterator)
        assert chunk.delta == 'olá'
        await asyncio.sleep(.05)
        await iterator.aclose()
    assert stream.closes == 1
