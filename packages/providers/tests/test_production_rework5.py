"""Native envelopes, required accounting, caps and raw cumulative accounting."""
import copy
import json

import httpx
import pytest

from rick_providers import ProviderError
from test_critic_remediation import adapter, config, MESSAGES
from test_anthropic import events as anthropic_events, wire as anthropic_wire


def envelope(*, stream=False, model='chat-model', choices=None):
    return dict(id='chatcmpl_1', object='chat.completion.chunk' if stream else 'chat.completion',
                created=123, model=model, choices=choices if choices is not None else [
                    dict(index=0, **({'delta': {'content': 'hello'}} if stream else {
                        'message': {'role': 'assistant', 'content': 'hello'}}),
                         finish_reason='stop', logprobs=None)])


def native_events(model='chat-model'):
    content = envelope(stream=True, model=model)
    content['choices'][0]['finish_reason'] = None
    content['usage'] = None
    terminal = envelope(stream=True, model=model)
    terminal['choices'][0]['delta'] = {}
    terminal['usage'] = None
    trailer = envelope(stream=True, model=model, choices=[])
    trailer['usage'] = dict(prompt_tokens=8, completion_tokens=4, total_tokens=12)
    return [content, terminal, trailer]


def wire(values):
    return b''.join(('data: '+json.dumps(v)+'\n\n').encode() for v in values) + b'data: [DONE]\n\n'


async def exercise(kind, operation, payload, valid, *, cfg=None, raw=None):
    requests, chunks = [], []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=raw if raw is not None else (
            wire(payload) if operation == 'stream' else json.dumps(payload).encode()))
    async with adapter(kind, cfg or config(kind), transport=httpx.MockTransport(handle)) as provider:
        async def invoke():
            if operation == 'stream':
                async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                    chunks.append(chunk)
                return chunks[-1]
            if operation == 'alias':
                return await provider.chat(MESSAGES)
            return await provider.chat_completion(messages=MESSAGES)
        if valid:
            result = await invoke()
            assert result.finish_reason == 'stop'
        else:
            with pytest.raises(ProviderError) as caught:
                await invoke()
            assert not any(c.finish_reason for c in chunks)
            assert caught.value.code in ('malformed_response', 'missing_field', 'invalid_model')
        assert len(requests) == 1
        return requests, chunks


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream'])
@pytest.mark.parametrize('field', ['healthy', 'id', 'object', 'created', 'model', 'index',
                                 'message', 'finish_reason', 'logprobs', 'usage'])
async def test_i1_01_native_required_fields(operation, field):
    payload = native_events() if operation == 'stream' else envelope()
    body = payload[1] if operation == 'stream' else payload
    if field in ('index', 'message', 'finish_reason', 'logprobs'):
        body['choices'][0].pop('delta' if field == 'message' and operation == 'stream' else field)
    elif field != 'healthy':
        # usage is required on native chunks when include_usage=true, optional on JSON.
        if field == 'usage' and operation == 'chat': body['usage'] = None
        else: body.pop(field)
    await exercise('openai', operation, payload, field == 'healthy'
                   or operation == 'chat' and field == 'usage'
                   or operation == 'stream' and field == 'logprobs')


@pytest.mark.asyncio
@pytest.mark.parametrize('frame', [0, 1, 2])
@pytest.mark.parametrize('fault', ['id_null', 'id_empty', 'id_control', 'created_bool', 'object_null', 'model_null'])
async def test_i1_01_native_bad_envelope_values(frame, fault):
    payload = native_events()
    key, value = {'id_null': ('id', None), 'id_empty': ('id', ''), 'id_control': ('id', '\n'),
                  'created_bool': ('created', True), 'object_null': ('object', None),
                  'model_null': ('model', None)}[fault]
    payload[frame][key] = value
    await exercise('openai', 'stream', payload, False)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible'])
@pytest.mark.parametrize('fault', ['healthy', 'absent', 'null', 'duplicate', 'early', 'combined'])
async def test_i1_02_trailing_usage(kind, fault):
    payload = native_events()
    if fault == 'absent': payload.pop()
    elif fault == 'null': payload[-1]['usage'] = None
    elif fault == 'duplicate': payload.append(copy.deepcopy(payload[-1]))
    elif fault == 'early': payload.insert(1, payload.pop())
    elif fault == 'combined': payload[1]['usage'] = payload.pop()['usage']
    valid = fault == 'healthy' or kind == 'openai_compatible'
    _, chunks = await exercise(kind, 'stream', payload, valid)
    if valid:
        assert (chunks[-1].usage is None) == (fault in ('absent', 'null'))


@pytest.mark.asyncio
@pytest.mark.parametrize('frame', [0, 1, 2])
@pytest.mark.parametrize('field', ['id', 'object', 'created', 'model'])
async def test_i1_01_native_core_required_on_every_frame(frame, field):
    payload = native_events(); payload[frame].pop(field)
    await exercise('openai', 'stream', payload, False)


@pytest.mark.asyncio
@pytest.mark.parametrize('position', [0, 2, 3])
async def test_i1_02_null_empty_choices_not_masked_by_valid_accounting(position):
    payload = native_events()
    null_event = envelope(stream=True, choices=[]); null_event['usage'] = None
    payload.insert(position, null_event)
    await exercise('openai', 'stream', payload, False)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream'])
async def test_explicit_gateway_omission_policy(operation):
    payload = native_events()[:2] if operation == 'stream' else envelope()
    for body in payload if operation == 'stream' else [payload]:
        for field in ('id', 'object', 'created'): body.pop(field)
        for choice in body['choices']: choice.pop('index'); choice.pop('logprobs')
    if operation == 'stream':
        payload[1]['choices'][0].pop('delta')
        for body in payload: body.pop('model'); body.pop('usage')
    await exercise('openai_compatible', operation, payload, True)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream', 'alias'])
@pytest.mark.parametrize('model', ['gpt-4o-mini', 'gpt-4o-mini-2024-07-18', 'gpt-5.1', 'o1', 'o3', 'gateway-model'])
async def test_i1_03_output_limit_serialized(operation, model):
    kind = 'openai_compatible' if model == 'gateway-model' else 'openai'
    payload = native_events(model) if operation == 'stream' else envelope(model=model)
    requests, _ = await exercise(kind, operation, payload, True, cfg=config(kind, chat_model=model, max_output_tokens=17))
    field = 'max_tokens' if kind == 'openai_compatible' else 'max_completion_tokens'
    assert requests[0][field] == 17
    assert 'max_output_tokens' not in requests[0]
    assert ('max_tokens' in requests[0]) == (kind == 'openai_compatible')


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream', 'alias'])
@pytest.mark.parametrize('limit', [True, 0, -1, 1.5, 128001, 16385])
async def test_i1_03_invalid_native_cap_before_io(operation, limit):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=envelope(model='gpt-4o-mini'))
    async with adapter('openai', config(chat_model='gpt-4o-mini', max_output_tokens=limit), transport=httpx.MockTransport(handle)) as provider:
        with pytest.raises(ProviderError) as caught:
            if operation == 'stream':
                [c async for c in provider.chat_completion_stream(messages=MESSAGES)]
            elif operation == 'alias': await provider.chat(MESSAGES)
            else: await provider.chat_completion(messages=MESSAGES)
    assert caught.value.code == 'invalid_configuration' and caught.value.attempts == 0
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['healthy', 'prompt_swap', 'creation_regress', 'thinking_regress',
    'thinking_null', 'thinking_disappear', 'creation_null', 'server_regress', 'server_disappear',
    'output_regress', 'prompt_regress', 'cache_null', 'partial_delta', 'details_progress'])
async def test_i1_04_raw_cumulative_accounting(fault):
    payload = anthropic_events(); payload[0]['message']['model'] = 'chat-model'
    initial = dict(input_tokens=4, cache_read_input_tokens=4, cache_creation_input_tokens=3,
        output_tokens=3, cache_creation=dict(ephemeral_1h_input_tokens=1, ephemeral_5m_input_tokens=2),
        output_tokens_details=dict(thinking_tokens=3), server_tool_use=dict(web_fetch_requests=1, web_search_requests=2))
    payload[0]['message']['usage'] = initial
    delta = copy.deepcopy(initial); delta['output_tokens'] = 4
    if fault == 'prompt_swap': delta.update(input_tokens=8, cache_read_input_tokens=0)
    elif fault == 'creation_regress': delta['cache_creation'] = dict(ephemeral_1h_input_tokens=0, ephemeral_5m_input_tokens=3)
    elif fault == 'thinking_regress': delta['output_tokens_details']['thinking_tokens'] = 0
    elif fault == 'thinking_null': delta['output_tokens_details'] = None
    elif fault == 'thinking_disappear': delta['output_tokens_details'] = {}
    elif fault == 'creation_null': delta['cache_creation'] = None
    elif fault == 'server_regress': delta['server_tool_use']['web_fetch_requests'] = 0
    elif fault == 'server_disappear': delta['server_tool_use'] = None
    elif fault == 'output_regress': delta['output_tokens'] = 2; delta['output_tokens_details']['thinking_tokens'] = 2
    elif fault == 'prompt_regress': delta['input_tokens'] = 3
    elif fault == 'cache_null': delta['cache_read_input_tokens'] = None
    elif fault == 'partial_delta': delta = dict(output_tokens=4)
    elif fault == 'details_progress': delta['output_tokens_details']['thinking_tokens'] = 4
    payload[-2]['usage'] = delta
    await exercise('anthropic', 'stream', payload, fault in ('healthy', 'partial_delta', 'details_progress'), raw=anthropic_wire(payload))
