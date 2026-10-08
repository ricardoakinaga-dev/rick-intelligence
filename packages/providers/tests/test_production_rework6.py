"""Public memory-transport discriminators for native health and SSE framing."""
import copy
import json

import httpx
import pytest

from rick_providers import ProviderError
from test_critic_remediation import adapter, config, MESSAGES
from test_production_rework5 import native_events, wire
from test_anthropic import events as anthropic_events, wire as anthropic_wire, config as anthropic_config


class Delivery(httpx.AsyncByteStream):
    def __init__(self, raw, bytewise):
        self.raw, self.bytewise, self.closes = raw, bytewise, 0

    async def __aiter__(self):
        if self.bytewise:
            for byte in self.raw:
                yield bytes([byte])
        else:
            yield self.raw

    async def aclose(self):
        self.closes += 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible'])
@pytest.mark.parametrize('payload,native_ok,gateway_ok', [
    ({}, False, True), ({'status': 'ok'}, False, True),
    ({'error': None}, False, False), ({'error': {'message': 'private'}}, False, False),
    ({'data': None}, False, False), ({'data': []}, False, False),
    ({'data': {}}, False, False), ({'data': [{'id': 'other'}]}, False, False),
    ({'data': [{'model': 'chat-model'}]}, False, True),
    ({'object': 'list', 'data': [{'id': 'chat-model', 'object': 'model', 'created': 0, 'owned_by': 'fixture'}]}, True, True),
    ({'data': [{'id': 'chat-model'}], 'error': False}, False, False),
])
async def test_i1_01_health_policy(kind, payload, native_ok, gateway_ok):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=payload)
    async with adapter(kind, config(kind, timeout=1), transport=httpx.MockTransport(handle)) as provider:
        assert await provider.health_check() is (native_ok if kind == 'openai' else gateway_ok)
    assert len(calls) == 1 and calls[0].url.path == '/v1/models'


async def exercise(raw, bytewise, valid, *, kind='openai'):
    delivery, calls, chunks = Delivery(raw, bytewise), [], []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=delivery)
    async with adapter(kind, config(kind, timeout=1, max_attempts=3, retry_base_delay=0),
                       transport=httpx.MockTransport(handle)) as provider:
        async def invoke():
            async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                chunks.append(chunk)
        if valid:
            await invoke()
            assert ''.join(chunk.delta for chunk in chunks) == 'hello'
            assert sum(chunk.finish_reason is not None for chunk in chunks) == 1
            assert chunks[-1].finish_reason == 'stop' and chunks[-1].usage.total_tokens == 12
        else:
            with pytest.raises(ProviderError) as caught:
                await invoke()
            assert caught.value.code in {'malformed_response', 'invalid_json'}
            assert not caught.value.retryable and caught.value.attempts == 1
            assert not any(chunk.finish_reason for chunk in chunks)
    assert len(calls) == delivery.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('bytewise', [False, True])
@pytest.mark.parametrize('frame', [0, 1, 2])
@pytest.mark.parametrize('field', ['id', 'created'])
async def test_i1_02_completion_identity_is_immutable(bytewise, frame, field):
    events = native_events()
    if frame == 0:
        # First role-only frame still establishes identity before content.
        role = copy.deepcopy(events[0]); role['choices'][0]['delta'] = {'role': 'assistant'}
        events.insert(0, role)
        frame = 1
    events[frame][field] = 'chatcmpl_other' if field == 'id' else 124
    await exercise(wire(events), bytewise, False)


@pytest.mark.asyncio
@pytest.mark.parametrize('bytewise', [False, True])
@pytest.mark.parametrize('framing', [
    'healthy', 'multiline', 'crlf', 'cr', 'metadata', 'no_separators',
    'only_final_separator', 'missing_middle_separator', 'eof_data',
    'eof_done_line', 'eof_partial', 'tail_data', 'tail_empty_data',
])
async def test_i1_03_sse_dispatch_requires_complete_event(bytewise, framing):
    raw = wire(native_events())
    if framing == 'multiline':
        raw = b''.join(('data: ' + json.dumps(event, indent=2).replace('\n', '\ndata: ') + '\n\n').encode()
                       for event in native_events()) + b'data: [DONE]\n\n'
    elif framing in ('crlf', 'cr'):
        raw = raw.replace(b'\n', b'\r\n' if framing == 'crlf' else b'\r')
    elif framing == 'metadata':
        raw = b'\xef\xbb\xbf: comment\nid: first\nevent: message\nretry: 5\n' + raw + b': tail\nid: last\n'
    elif framing == 'no_separators': raw = raw.replace(b'\n\n', b'\n')
    elif framing == 'only_final_separator': raw = raw.replace(b'\n\n', b'\n') + b'\n'
    elif framing == 'missing_middle_separator': raw = raw.replace(b'\n\n', b'\n', 1)
    elif framing == 'eof_data': raw = raw.rsplit(b'data: [DONE]', 1)[0].rstrip(b'\n')
    elif framing == 'eof_done_line': raw = raw[:-1]
    elif framing == 'eof_partial': raw = raw[:-3]
    elif framing == 'tail_data': raw += b'data: {}'
    elif framing == 'tail_empty_data': raw += b'data:\n\n'
    await exercise(raw, bytewise, framing in ('healthy', 'multiline', 'crlf', 'cr', 'metadata'))


@pytest.mark.asyncio
@pytest.mark.parametrize('bytewise', [False, True])
async def test_i1_03_explicit_gateway_uses_same_event_framing(bytewise):
    events = native_events()
    for event in events:
        for field in ('id', 'object', 'created'): event.pop(field)
    await exercise(wire(events), bytewise, True, kind='openai_compatible')
    await exercise(wire(events).replace(b'\n\n', b'\n'), bytewise, False, kind='openai_compatible')


@pytest.mark.asyncio
@pytest.mark.parametrize('bytewise', [False, True])
@pytest.mark.parametrize('framing', ['healthy', 'multiline', 'no_separator', 'eof_tail'])
async def test_i1_03_anthropic_event_behavior_preserved(bytewise, framing):
    events = anthropic_events(text='hello')
    raw = anthropic_wire(events)
    if framing == 'multiline':
        raw = b''.join(('event: ' + event['type'] + '\ndata: ' +
                        json.dumps(event, indent=2).replace('\n', '\ndata: ') + '\n\n').encode()
                       for event in events)
    elif framing == 'no_separator': raw = raw.replace(b'\n\n', b'\n')
    elif framing == 'eof_tail': raw = raw[:-1]
    delivery, chunks, calls = Delivery(raw, bytewise), [], []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=delivery)
    async with adapter('anthropic', anthropic_config(), transport=httpx.MockTransport(handle)) as provider:
        async def invoke():
            async for chunk in provider.chat_completion_stream(messages=MESSAGES): chunks.append(chunk)
        if framing in ('healthy', 'multiline'):
            await invoke()
            assert ''.join(chunk.delta for chunk in chunks) == 'hello'
            assert sum(chunk.finish_reason is not None for chunk in chunks) == 1
            assert chunks[-1].finish_reason == 'stop'
        else:
            with pytest.raises(ProviderError) as caught: await invoke()
            assert not caught.value.retryable and not any(chunk.finish_reason for chunk in chunks)
    assert len(calls) == delivery.closes == 1
