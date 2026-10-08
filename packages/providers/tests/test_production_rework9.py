"""Public memory-transport cancellation and native model metadata contracts."""
import asyncio
import copy
import json

import httpx
import pytest

from rick_providers import AnthropicMessagesClient, ProviderError
from test_production_rework8 import (
    CLAUDE, Delivery, adapter, body, config, events, invoke, wire,
)


def model_info():
    return dict(id=CLAUDE, type='model', display_name='Claude Sonnet 4.5',
                created_at='2025-09-29T00:00:00Z')


class Headers(httpx.AsyncBaseTransport):
    def __init__(self, raw, behavior):
        self.raw, self.behavior = raw, behavior
        self.entered = asyncio.Event()
        self.requests, self.deliveries = [], []
        self.closes = self.suppressed = 0
        self.count_after_headers = None

    async def handle_async_request(self, request):
        self.requests.append(request)
        self.entered.set()
        if self.behavior in ('suppressed', 'acknowledged', 'cooperative', 'deadline', 'both'):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if self.behavior == 'cooperative':
                    raise
                self.suppressed += 1
                if self.behavior == 'acknowledged':
                    asyncio.current_task().uncancel()  # Explicit transport acknowledgement.
                end = asyncio.get_running_loop().time() + (.025 if self.behavior == 'both' else .002)
                while asyncio.get_running_loop().time() < end:
                    try:
                        await asyncio.sleep(max(0, end - asyncio.get_running_loop().time()))
                    except asyncio.CancelledError:
                        self.suppressed += 1
        self.count_after_headers = asyncio.current_task().cancelling()
        delivery = Delivery(self.raw)
        self.deliveries.append(delivery)
        return httpx.Response(200, stream=delivery)

    async def aclose(self):
        self.closes += 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible', 'anthropic'])
@pytest.mark.parametrize('method', ['chat', 'health', 'stream'])
@pytest.mark.parametrize('caller_owned', [False, True])
@pytest.mark.parametrize('behavior', [
    'healthy', 'suppressed', 'cooperative', 'acknowledged', 'pending',
    'pending_acknowledged', 'deadline', 'both',
])
async def test_public_header_control_flow(kind, method, caller_owned, behavior):
    payload = (model_info() if kind == 'anthropic' else
               {'object': 'list', 'data': [{'id': 'chat-model', 'object': 'model', 'created': 0, 'owned_by': 'fixture'}]}) if method == 'health' else body(kind)
    raw = wire(kind, events(kind)) if method == 'stream' else json.dumps(payload).encode()
    transport = Headers(raw, behavior)
    caller = httpx.AsyncClient(transport=transport) if caller_owned else None
    kwargs = {'client': caller} if caller_owned else {'transport': transport}
    chunks = []
    provider = adapter(kind)(config(kind, timeout=.01 if behavior in ('deadline', 'both') else .5), **kwargs)

    async def call():
        if behavior in ('pending', 'pending_acknowledged'):
            task = asyncio.current_task()
            task.cancel()
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                if behavior == 'pending_acknowledged':
                    task.uncancel()  # Caller explicitly clears its prior cancellation.
        return await invoke(provider, method, chunks)

    task = asyncio.create_task(call())
    try:
        await transport.entered.wait()
        if behavior in ('suppressed', 'cooperative', 'acknowledged', 'both'):
            task.cancel()
        if behavior in ('suppressed', 'cooperative', 'pending', 'both'):
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled() and task.cancelling() == 1
            assert chunks == []
        elif behavior == 'deadline':
            if method == 'health':
                assert await task is False
            else:
                with pytest.raises(ProviderError) as caught:
                    await task
                assert caught.value.code == 'timeout' and caught.value.attempts == 3
            assert not chunks and task.cancelling() == 0
        else:
            result = await task
            assert task.cancelling() == 0
            if method == 'health':
                assert result is True
            else:
                assert result.finish_reason == 'stop'
                if method == 'stream':
                    assert sum(c.finish_reason is not None for c in chunks) == 1
        expected = 3 if behavior == 'deadline' and method != 'health' else 1
        assert len(transport.requests) == expected
        assert len(transport.deliveries) == (0 if behavior == 'cooperative' else expected)
        assert all(d.closes == 1 for d in transport.deliveries)
        if behavior in ('suppressed', 'pending', 'both'):
            assert transport.count_after_headers == (2 if behavior == 'both' else 1)
        await provider.aclose()
        assert transport.closes == int(not caller_owned)
        if caller_owned:
            assert not caller.is_closed
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await provider.aclose()
        if caller is not None:
            await caller.aclose()
    assert transport.closes == 1
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]


def support(supported=True):
    return {'supported': supported}


def capabilities():
    return dict(**{k: support() for k in ('batch', 'citations', 'code_execution',
                'image_input', 'pdf_input', 'structured_outputs')},
                context_management=dict(supported=True, clear_thinking_20251015=support(),
                    clear_tool_uses_20250919=support(False), compact_20260112=None),
                effort=dict(supported=True, **{k: support() for k in ('high', 'low', 'max', 'medium')}, xhigh=None),
                thinking=dict(supported=True, types=dict(enabled=support(), adaptive=support(False))))


HEALTHY = [
    model_info(),
    dict(model_info(), created_at='1970-01-01T00:00:00Z'),
    dict(model_info(), created_at='2024-02-29t12:34:56.123456z'),
    dict(model_info(), created_at='2025-09-29T12:34:56+03:30'),
    dict(model_info(), max_input_tokens=None, max_tokens=None, capabilities=None),
    dict(model_info(), max_input_tokens=0, max_tokens=4096, capabilities=capabilities()),
    dict(model_info(), future_metadata={'private': 'unused'}, capabilities=dict(capabilities(), future_feature=17)),
    dict(model_info(), display_name='', capabilities={
        **{k: support(False) for k in ('batch', 'citations', 'code_execution',
            'image_input', 'pdf_input', 'structured_outputs')},
        'context_management': support(False),
        'effort': dict(supported=False, **{k: support(False) for k in ('high', 'low', 'max', 'medium')}, xhigh=support(False)),
        'thinking': dict(supported=False, types=dict(enabled=support(False), adaptive=support(False)))}),
]


def malformed_models():
    cases = []
    for field in ('id', 'type', 'display_name', 'created_at'):
        missing = model_info()
        missing.pop(field)
        cases.append(missing)
    for field, values in {
        'id': [None, 17, ''], 'type': [None, 'message'],
        'display_name': [None, 17, {}, []],
        'created_at': [None, 17, {}, 'not-a-date', '2025-02-30T00:00:00Z',
            '2025-09-29', '2025-09-29T00:00:00', '2025-09-29 00:00:00Z',
            '2025-09-29T24:00:00Z', '2025-09-29T00:00:00+24:00',
            '2025-09-29T00:00:00+01:60', '2025-09-29T00:00:00+0300'],
        'max_input_tokens': [True, 1.5, '100', {}, float('inf')],
        'max_tokens': [False, 1.5, '100', [], float('nan')],
        'capabilities': [True, [], 'yes', {}],
    }.items():
        cases.extend(dict(model_info(), **{field: value}) for value in values)
    known = capabilities()
    for field in known:
        for bad in (None, True, [], {}, {'supported': 1}):
            value = copy.deepcopy(known)
            value[field] = bad
            cases.append(dict(model_info(), capabilities=value))
        value = copy.deepcopy(known)
        value.pop(field)
        cases.append(dict(model_info(), capabilities=value))
    for group, names in {
        'context_management': ('clear_thinking_20251015', 'clear_tool_uses_20250919', 'compact_20260112'),
        'effort': ('high', 'low', 'max', 'medium', 'xhigh'),
    }.items():
        for name in names:
            value = copy.deepcopy(known)
            value[group][name] = {'supported': 'true'}
            cases.append(dict(model_info(), capabilities=value))
    for bad in (None, [], {}, {'enabled': support()}):
        value = copy.deepcopy(known)
        value['thinking']['types'] = bad
        cases.append(dict(model_info(), capabilities=value))
    for name in ('high', 'low', 'max', 'medium'):
        for remove in (True, False):
            value = copy.deepcopy(known)
            if remove:
                value['effort'].pop(name)
            else:
                value['effort'][name] = None
            cases.append(dict(model_info(), capabilities=value))
    for name in ('enabled', 'adaptive'):
        value = copy.deepcopy(known)
        value['thinking']['types'][name] = {'supported': 1}
        cases.append(dict(model_info(), capabilities=value))
    return cases


@pytest.mark.asyncio
@pytest.mark.parametrize('payload,healthy', [(p, True) for p in HEALTHY] + [(p, False) for p in malformed_models()])
async def test_native_model_info(payload, healthy):
    transport = Headers(json.dumps(payload).encode(), 'healthy')
    async with AnthropicMessagesClient(config('anthropic', chat_model='claude-sonnet-4-5'), transport=transport) as provider:
        assert await provider.health_check() is healthy
    assert len(transport.requests) == len(transport.deliveries) == 1
    assert transport.requests[0].method == 'GET'
    assert transport.requests[0].url.path.endswith('/models/claude-sonnet-4-5')
    assert transport.deliveries[0].closes == transport.closes == 1
