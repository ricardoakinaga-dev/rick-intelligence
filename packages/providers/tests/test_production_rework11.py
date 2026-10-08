"""Explicit gateway identity must be valid; omitted identity stays compatible."""
import json
import httpx
import pytest
from rick_providers import ProviderError
from test_production_rework8 import Delivery, adapter, body, config, events, invoke, wire

BAD = [None, '', ' \n ', 'x\0y', 'x\x7fy', 'x'*257, True, 17]
GOOD = ['completion-id', 'x'*256, 'omitted']


async def exercise(kind, method, identifier, stage='all'):
    payload = body(kind) if method == 'chat' else events(kind)
    frames = [payload] if method == 'chat' else payload
    if method == 'stream':
        frames.insert(0, dict(frames[0], choices=[dict(index=0,
            delta={'role':'assistant'},finish_reason=None)],usage=None))
    if stage != 'all':
        # Other compatible frames omit identity, so a malformed supplied ID
        # cannot be refused merely because it differs from another valid ID.
        for frame in frames: frame.pop('id', None)
    selected = frames if stage == 'all' else [frames[{'role':0,'content':1,'terminal':2,'accounting':3}[stage]]]
    for frame in selected:
        if identifier == 'omitted': frame.pop('id', None)
        else: frame['id'] = identifier
    raw = json.dumps(payload).encode() if method == 'chat' else wire(kind,payload)
    delivery = Delivery(raw)
    async with adapter(kind)(config(kind), transport=httpx.MockTransport(
        lambda request: httpx.Response(200,stream=delivery))) as provider:
        chunks = []
        valid = identifier in GOOD and (identifier != 'omitted' or kind == 'openai_compatible')
        if valid:
            result = await invoke(provider,method,chunks)
            assert result.finish_reason == 'stop'
            if method == 'stream': assert sum(c.finish_reason is not None for c in chunks) == 1
        else:
            with pytest.raises(ProviderError) as error:
                await invoke(provider,method,chunks)
            assert error.value.code == 'malformed_response'
            assert not any(c.finish_reason is not None for c in chunks)
    assert delivery.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['openai','openai_compatible'])
@pytest.mark.parametrize('method',['chat','stream'])
@pytest.mark.parametrize('identifier', BAD+GOOD)
async def test_supplied_completion_identity(kind,method,identifier):
    await exercise(kind,method,identifier)


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['role','content','terminal','accounting'])
@pytest.mark.parametrize('identifier',BAD)
async def test_gateway_each_frame_identity(stage,identifier):
    await exercise('openai_compatible','stream',identifier,stage)
