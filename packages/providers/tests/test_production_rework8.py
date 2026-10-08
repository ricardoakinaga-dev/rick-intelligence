"""Focused v8 public memory-transport deadline, identity and health matrix."""
import asyncio
import json

import httpx
import pytest

from rick_providers import AnthropicMessagesClient, OpenAICompatibleClient, ProviderConfig, ProviderError
from rick_providers.cleanup import CleanupError

MESSAGES = [{'role': 'user', 'content': 'Reply'}]
CLAUDE = 'claude-sonnet-4-5-20250929'


def config(kind, **overrides):
    values = dict(provider_kind=kind, environment='test', base_url='https://provider.invalid/v1',
                  api_key='synthetic-provider-key', chat_model=CLAUDE if kind == 'anthropic' else 'chat-model',
                  timeout=1, max_attempts=3, retry_base_delay=0)
    values.update(overrides)
    return ProviderConfig(**values)


def adapter(kind):
    return AnthropicMessagesClient if kind == 'anthropic' else OpenAICompatibleClient


def body(kind):
    if kind == 'anthropic':
        return dict(id='msg_control', type='message', role='assistant', model=CLAUDE,
                    content=[{'type': 'text', 'text': 'olá'}], stop_reason='end_turn', stop_sequence=None,
                    usage={'input_tokens': 2, 'output_tokens': 3})
    return dict(id='chatcmpl_control', object='chat.completion', created=100, model='chat-model',
                choices=[dict(index=0, message={'role': 'assistant', 'content': 'olá'},
                              finish_reason='stop', logprobs=None)],
                usage={'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5})


def events(kind='openai'):
    if kind == 'anthropic':
        start = body(kind)
        start.update(content=[], stop_reason=None, usage={'input_tokens': 2, 'output_tokens': 0})
        return [dict(type='message_start', message=start),
                dict(type='content_block_start', index=0, content_block={'type': 'text', 'text': ''}),
                dict(type='content_block_delta', index=0, delta={'type': 'text_delta', 'text': 'olá'}),
                dict(type='content_block_stop', index=0),
                dict(type='message_delta', delta={'stop_reason': 'end_turn', 'stop_sequence': None},
                     usage={'output_tokens': 3}), dict(type='message_stop')]
    base = dict(id='chatcmpl_control', object='chat.completion.chunk', created=100, model='chat-model')
    return [dict(base, usage=None, choices=[dict(index=0, delta={'content': 'olá'}, finish_reason=None)]),
            dict(base, usage=None, choices=[dict(index=0, delta={}, finish_reason='stop')]),
            dict(base, choices=[], usage=body(kind)['usage'])]


def wire(kind, frames):
    if kind == 'anthropic':
        return b''.join(f"event: {f['type']}\ndata: {json.dumps(f, ensure_ascii=False)}\n\n".encode() for f in frames)
    return b''.join(f'data: {json.dumps(f, ensure_ascii=False)}\n\n'.encode() for f in frames) + b'data: [DONE]\n\n'


class Delivery(httpx.AsyncByteStream):
    def __init__(self, raw, *, fail_after=False, stall_close=False):
        self.raw, self.fail_after, self.stall_close = raw, fail_after, stall_close
        self.closes = 0

    async def __aiter__(self):
        # Bytewise delivery also checks the retained UTF-8 decoder boundary.
        for byte in self.raw:
            yield bytes([byte])
        if self.fail_after:
            raise httpx.ReadError('synthetic read failure')

    async def aclose(self):
        self.closes += 1
        if self.stall_close:
            await asyncio.Event().wait()


class MemoryTransport(httpx.AsyncBaseTransport):
    def __init__(self, raw, *, late=False, statuses=(200,), fail_after=False, close_fault=None):
        self.raw, self.late, self.statuses = raw, late, statuses
        self.fail_after, self.close_fault = fail_after, close_fault
        self.requests, self.deliveries = [], []
        self.closes = self.cancelled = 0

    async def handle_async_request(self, request):
        self.requests.append(request)
        if self.late:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                # Finite cancellation suppression, never an unbounded-work claim.
                await asyncio.sleep(.005)
        delivery = Delivery(self.raw, fail_after=self.fail_after)
        self.deliveries.append(delivery)
        return httpx.Response(self.statuses[min(len(self.requests)-1, len(self.statuses)-1)], stream=delivery)

    async def aclose(self):
        self.closes += 1
        if self.closes == 1:
            if self.close_fault == 'false':
                return False
            if self.close_fault == 'raise':
                raise RuntimeError('synthetic close failure')
            if self.close_fault == 'stall':
                await asyncio.Event().wait()


async def invoke(provider, mode, chunks):
    if mode == 'health':
        return await provider.health_check()
    if mode == 'chat':
        return await provider.chat_completion(messages=MESSAGES)
    async for chunk in provider.chat_completion_stream(messages=MESSAGES):
        chunks.append(chunk)
    return chunks[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible', 'anthropic'])
@pytest.mark.parametrize('mode', ['chat', 'health', 'stream'])
@pytest.mark.parametrize('caller_owned', [False, True])
@pytest.mark.parametrize('late', [False, True])
async def test_header_deadline(kind, mode, caller_owned, late):
    payload = ({'type': 'model', 'id': CLAUDE, 'display_name': 'Claude Sonnet 4.5',
                'created_at': '2025-09-29T00:00:00Z'} if kind == 'anthropic' else
               {'object': 'list', 'data': [{'id': 'chat-model', 'object': 'model', 'created': 0, 'owned_by': 'fixture'}]}) if mode == 'health' else body(kind)
    raw = wire(kind, events(kind)) if mode == 'stream' else json.dumps(payload).encode()
    transport = MemoryTransport(raw, late=late)
    caller = httpx.AsyncClient(transport=transport, headers={'Authorization': 'ambient-auth'},
                               cookies={'ambient': 'cookie'}, auth=('ambient-user', 'ambient-pass')) if caller_owned else None
    kwargs = {'client': caller} if caller_owned else {'transport': transport}
    chunks = []
    try:
        async with adapter(kind)(config(kind, timeout=.01 if late else 1, max_attempts=1), **kwargs) as provider:
            if late and mode != 'health':
                with pytest.raises(ProviderError) as caught:
                    await invoke(provider, mode, chunks)
                assert caught.value.code == 'timeout' and caught.value.attempts == 1
                assert not chunks
            else:
                result = await invoke(provider, mode, chunks)
                if mode == 'health':
                    assert result is (not late)
                else:
                    assert result.finish_reason == 'stop'
        assert len(transport.requests) == len(transport.deliveries) == 1
        assert transport.deliveries[0].closes == 1
        assert transport.cancelled == int(late)
        request = transport.requests[0]
        assert request.headers.get('cookie') is None
        if kind == 'anthropic':
            assert request.headers['x-api-key'] == 'synthetic-provider-key'
            assert 'authorization' not in request.headers
        else:
            assert request.headers['authorization'] == 'Bearer synthetic-provider-key'
        assert transport.closes == int(not caller_owned)
        if caller_owned:
            assert not caller.is_closed
    finally:
        if caller is not None:
            await caller.aclose()
    assert transport.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible'])
@pytest.mark.parametrize('frame', [1, 2])
@pytest.mark.parametrize('field', ['id', 'created'])
@pytest.mark.parametrize('gap', [False, True])
async def test_supplied_identity_must_agree(kind, frame, field, gap):
    frames = events(kind)
    if gap:
        frames[0].pop(field)
        # With a terminal mutation, compare its identity to the usage frame.
    frames[frame][field] = 'chatcmpl_OTHER' if field == 'id' else 999
    transport = MemoryTransport(wire(kind, frames))
    chunks = []
    async with adapter(kind)(config(kind), transport=transport) as provider:
        with pytest.raises(ProviderError) as caught:
            await invoke(provider, 'stream', chunks)
        assert caught.value.code == 'malformed_response'
        assert caught.value.attempts == 1 and not caught.value.retryable
        assert not any(c.finish_reason for c in chunks)
        if not gap or kind == 'openai_compatible':
            assert ''.join(c.delta for c in chunks) == 'olá'
    assert len(transport.requests) == transport.deliveries[0].closes == transport.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible'])
@pytest.mark.parametrize('omission', ['none', 'all', 'id', 'created', 'alternating'])
async def test_identity_healthy_and_omission_policy(kind, omission):
    frames = events(kind)
    for index, frame in enumerate(frames):
        fields = {'none': (), 'all': ('id', 'created'), 'id': ('id',), 'created': ('created',),
                  'alternating': ('id',) if index == 1 else ('created',)}[omission]
        for field in fields:
            frame.pop(field)
    transport = MemoryTransport(wire(kind, frames))
    chunks = []
    async with adapter(kind)(config(kind), transport=transport) as provider:
        if kind == 'openai' and omission != 'none':
            with pytest.raises(ProviderError):
                await invoke(provider, 'stream', chunks)
            assert not any(c.finish_reason for c in chunks)
        else:
            result = await invoke(provider, 'stream', chunks)
            assert ''.join(c.delta for c in chunks) == 'olá'
            assert sum(c.finish_reason is not None for c in chunks) == 1
            assert result.usage.total_tokens == 5
    assert len(transport.requests) == transport.deliveries[0].closes == transport.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('model_id,healthy', [('', False), (' ', False), ('\n', False),
    ('claude\nmodel', False), ('claude\x00model', False), ('claude\x7fmodel', False),
    ('x'*257, False), ('x'*256, False), (None, False), (17, False), (CLAUDE, True)])
@pytest.mark.parametrize('requested', [CLAUDE, 'claude-sonnet-4-5'])
async def test_anthropic_health_id(model_id, healthy, requested):
    payload = dict(type='model', id=model_id, display_name='Claude Sonnet 4.5',
                   created_at='2025-09-29T00:00:00Z')
    transport = MemoryTransport(json.dumps(payload).encode())
    async with AnthropicMessagesClient(config('anthropic', chat_model=requested), transport=transport) as provider:
        assert await provider.health_check() is healthy
    assert transport.requests[0].url.path.endswith('/models/'+requested)
    assert len(transport.requests) == transport.deliveries[0].closes == transport.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('late,statuses,expected', [(False, (503, 429, 200), None),
    (False, (503,), 'server_error'), (False, (400,), 'http_error'), (True, (200,), 'timeout')])
async def test_retry_caps_and_configured_backoff(late, statuses, expected):
    transport = MemoryTransport(json.dumps(body('openai')).encode(), late=late, statuses=statuses)
    delays = []
    async def sleep(delay):
        delays.append(delay)
        await asyncio.sleep(delay)
    async with OpenAICompatibleClient(config('openai', timeout=.01, retry_base_delay=.03),
                                      transport=transport, sleep=sleep) as provider:
        if expected:
            with pytest.raises(ProviderError) as caught:
                await provider.chat_completion(messages=MESSAGES)
            assert caught.value.code == expected
            assert caught.value.attempts == (1 if statuses == (400,) else 3)
        else:
            assert (await provider.chat_completion(messages=MESSAGES)).finish_reason == 'stop'
    assert len(transport.requests) == (1 if statuses == (400,) else 3)
    assert delays == ([] if statuses == (400,) else [.03, .06])
    assert all(d.closes == 1 for d in transport.deliveries)
    assert transport.closes == 1


@pytest.mark.asyncio
async def test_accepted_stream_is_not_replayed():
    raw = wire('openai', events()[:1]).removesuffix(b'data: [DONE]\n\n')
    transport = MemoryTransport(raw, fail_after=True)
    chunks = []
    async with OpenAICompatibleClient(config('openai'), transport=transport) as provider:
        with pytest.raises(ProviderError):
            await invoke(provider, 'stream', chunks)
    assert ''.join(c.delta for c in chunks) == 'olá'
    assert not any(c.finish_reason for c in chunks)
    assert len(transport.requests) == transport.deliveries[0].closes == transport.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['false', 'raise', 'stall'])
async def test_failed_owned_disposal_retains_obligation(fault):
    transport = MemoryTransport(json.dumps(body('openai')).encode(), close_fault=fault)
    provider = OpenAICompatibleClient(config('openai'), transport=transport)
    await provider.chat_completion(messages=MESSAGES)
    start = asyncio.get_running_loop().time()
    with pytest.raises(CleanupError):
        await provider.aclose()
    assert asyncio.get_running_loop().time()-start < 1
    await provider.aclose()
    await provider.aclose()
    assert transport.closes == 2 and transport.deliveries[0].closes == 1
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
