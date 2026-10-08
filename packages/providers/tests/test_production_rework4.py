"""Negative and healthy public HTTP discriminators for provider critic v4."""
import asyncio
import copy
import json
import time

import httpx
import pytest

from rick_providers import ProviderError
from test_critic_remediation import adapter, body, config, MESSAGES
from test_anthropic import events as anthropic_events, wire as anthropic_wire


def openai_wire(values):
    return b''.join(('data: ' + json.dumps(v) + '\n\n').encode() for v in values) + b'data: [DONE]\n\n'


def choice(delta=None, reason=None):
    return {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, 'usage': None, 'model': 'chat-model', 'choices': [{'logprobs': None, 'index': 0, 'delta': delta or {}, 'finish_reason': reason}]}


def usage(prompt=3, completion=2, **details):
    return {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, 'model': 'chat-model', 'choices': [], 'usage': {
        'prompt_tokens': prompt, 'completion_tokens': completion, 'total_tokens': prompt + completion, **details}}


async def response_case(kind, operation, payload, valid, *, cfg=None):
    if operation == 'stream':
        raw = anthropic_wire(payload) if kind == 'anthropic' else openai_wire(payload)
    else:
        raw = json.dumps(payload).encode()
    calls, chunks = [], []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=raw)
    # Schema checks must not race the 40 ms deadline from the shared fixture:
    # a full-suite garbage collection can pause this process for longer.
    # Deadline-specific cases pass their own configuration below.
    async with adapter(kind, cfg or config(kind, timeout=1.0), transport=httpx.MockTransport(handle)) as provider:
        async def invoke():
            if operation == 'stream':
                async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                    chunks.append(chunk)
                return chunks[-1]
            return await provider.chat_completion(messages=MESSAGES)
        if valid:
            result = await invoke()
            assert result.finish_reason == 'stop'
            return result, calls, chunks
        with pytest.raises(ProviderError) as caught:
            await invoke()
        assert caught.value.code == 'malformed_response'
        assert caught.value.attempts == 1 and len(calls) == 1
        assert not any(chunk.finish_reason for chunk in chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream'])
@pytest.mark.parametrize('extra,valid', [({}, True), ({'stop_details': None}, True),
    ({'container': None}, True), ({'container': {'id': 'container_1', 'expires_at': '2026-10-04T00:00:00Z'}}, True),
    ({'unrecognized_safety_detail': {'refusal': 'blocked'}}, False),
    ({'stop_details': {'type': 'refusal', 'explanation': 'private'}}, False),
    ({'container': {'id': 42, 'expires_at': 'invalid'}}, False),
    ({'container': {'id': 'container_1', 'expires_at': '2026-10-04T00:00:00Z', 'unknown': True}}, False)])
async def test_f1_anthropic_message_field_gate(operation, extra, valid):
    if operation == 'stream':
        payload = anthropic_events()
        payload[0]['message']['model'] = 'chat-model'
        payload[0]['message'].update(copy.deepcopy(extra))
    else:
        payload = body('anthropic'); payload.update(copy.deepcopy(extra))
    await response_case('anthropic', operation, payload, valid)


TOKEN = {'token': 'hello', 'logprob': -0.25, 'bytes': [104, 101, 108, 108, 111],
         'top_logprobs': [{'token': 'hello', 'logprob': -0.25, 'bytes': None}]}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream'])
@pytest.mark.parametrize('fault', ['healthy', 'nullable_bytes', 'absent_bytes', 'sentinel', 'token', 'logprob', 'positive', 'bool', 'bytes', 'byte_bool',
    'top_type', 'top_token', 'top_logprob', 'top_bytes', 'top_unknown', 'missing_top', 'unknown', 'refusal'])
async def test_f2_nested_logprobs(operation, fault):
    token = copy.deepcopy(TOKEN)
    valid = fault in ('healthy', 'nullable_bytes', 'absent_bytes', 'sentinel')
    if fault == 'nullable_bytes': token['bytes'] = None
    elif fault == 'absent_bytes': token.pop('bytes'); token['top_logprobs'][0].pop('bytes')
    elif fault == 'sentinel': token['logprob'] = -9999.0
    elif fault == 'token': token['token'] = 42
    elif fault == 'logprob': token['logprob'] = 'invalid'
    elif fault == 'positive': token['logprob'] = 0.2
    elif fault == 'bool': token['logprob'] = True
    elif fault == 'bytes': token['bytes'] = [256]
    elif fault == 'byte_bool': token['bytes'] = [False]
    elif fault == 'top_type': token['top_logprobs'] = 'invalid'
    elif fault == 'missing_top': token.pop('top_logprobs')
    elif fault == 'unknown': token['unknown_safety'] = 'blocked'
    elif fault.startswith('top_'):
        key = fault[4:]
        token['top_logprobs'][0][key] = {'token': 42, 'logprob': 'invalid', 'bytes': [-1], 'unknown': 1}[key]
    payload = body()
    payload.pop('usage')
    payload['choices'][0]['logprobs'] = {'content': [token], 'refusal': [copy.deepcopy(TOKEN)] if fault == 'refusal' else None}
    if operation == 'stream':
        payload['object'] = 'chat.completion.chunk'
        payload['usage'] = None
        payload['choices'][0]['delta'] = payload['choices'][0].pop('message')
        payload = [payload, usage()]
    await response_case('openai', operation, payload, valid)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible'])
@pytest.mark.parametrize('case', ['healthy', 'conflict', 'regress', 'increase', 'duplicate', 'before', 'combined',
    'prompt_change', 'detail_regress', 'detail_conflict', 'detail_progress', 'detail_disappear',
    'detail_appear', 'detail_add', 'detail_null_to_known', 'prompt_detail_conflict'])
async def test_f3_stream_usage_contract(kind, case):
    values = [choice({'content': 'hello'}), choice(reason='stop'), usage()]
    gateway = kind == 'openai_compatible'
    valid = case == 'healthy' or gateway and case in ('increase', 'duplicate', 'before', 'combined', 'detail_progress',
                                                   'detail_appear', 'detail_add', 'detail_null_to_known')
    if case == 'conflict': values.append(usage(1, 4))
    elif case == 'regress': values.append(usage(1, 1))
    elif case == 'increase': values.append(usage(3, 3))
    elif case == 'duplicate': values.append(usage())
    elif case == 'before': values.insert(1, values.pop())
    elif case == 'combined': values[1]['usage'] = values.pop()['usage']
    elif case == 'prompt_change': values.append(usage(4, 3))
    elif case == 'detail_appear':
        values.append(usage(3, 3, completion_tokens_details={'reasoning_tokens': 1}, prompt_tokens_details={'cached_tokens': 1}))
    elif case == 'detail_add':
        values[-1] = usage(completion_tokens_details={'reasoning_tokens': 1})
        values.append(usage(3, 3, completion_tokens_details={'reasoning_tokens': 1, 'text_tokens': 1}))
    elif case == 'detail_null_to_known':
        values[-1] = usage(completion_tokens_details={'reasoning_tokens': None})
        values.append(usage(3, 3, completion_tokens_details={'reasoning_tokens': 1}))
    elif case == 'prompt_detail_conflict':
        values[-1] = usage(prompt_tokens_details={'cached_tokens': 1})
        values.append(usage(3, 3, prompt_tokens_details={'cached_tokens': 0}))
    elif case.startswith('detail_'):
        values[-1] = usage(completion_tokens_details={'reasoning_tokens': 1})
        counter = 2 if case == 'detail_progress' else 0
        values.append(usage(3, 3 if case in ('detail_regress', 'detail_progress', 'detail_disappear') else 2,
                            **({} if case == 'detail_disappear' else {'completion_tokens_details': {'reasoning_tokens': counter}})))
    result = await response_case(kind, 'stream', values, valid)
    if valid:
        terminal, calls, _ = result
        latest = next(event['usage'] for event in reversed(values) if event.get('usage') is not None)
        assert terminal.usage.model_dump() == {key: latest[key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
        if kind == 'openai': assert json.loads(calls[0].content)['stream_options'] == {'include_usage': True}


@pytest.mark.asyncio
@pytest.mark.parametrize('late', [None, {}, {'role': 'assistant'}, {'role': None}, {'content': ''}, {'refusal': ''}])
@pytest.mark.parametrize('with_usage', [False, True])
async def test_f4_post_terminal_choice_cannot_normalize_away(late, with_usage):
    values = [choice({'role': 'assistant'}), choice({'content': 'hello'}), choice(reason='stop')]
    if late is not None:
        event = choice(late)
        if with_usage: event['usage'] = usage()['usage']
        values.append(event)
    values.append(usage())
    await response_case('openai_compatible', 'stream', values, late is None)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream', 'alias'])
@pytest.mark.parametrize('model', ['gpt-5.1', 'gpt-5.2', 'gateway-model'])
@pytest.mark.parametrize('temperature,valid', [(-1, False), (2.01, False), (float('nan'), False), (float('inf'), False), (True, False), (0, True), (.37, True), (2, True), (None, True)])
async def test_f5_supported_temperature_range_before_http(operation, model, temperature, valid):
    calls = []
    payload = body(); payload['model'] = model; payload.pop('usage')
    if operation == 'stream':
        payload['object'] = 'chat.completion.chunk'
        payload['usage'] = None
        payload['choices'][0]['delta'] = payload['choices'][0].pop('message')
    trailer = usage(); trailer['model'] = model
    raw = openai_wire([payload, trailer]) if operation == 'stream' else json.dumps(payload).encode()
    def handle(request):
        calls.append(json.loads(request.content)); return httpx.Response(200, content=raw)
    kind = 'openai_compatible' if model == 'gateway-model' else 'openai'
    async with adapter(kind, config(kind, chat_model=model), transport=httpx.MockTransport(handle)) as provider:
        async def invoke():
            if operation == 'stream': return [c async for c in provider.chat_completion_stream(messages=MESSAGES, temperature=temperature)]
            if operation == 'alias': return await provider.chat(MESSAGES, temperature=temperature)
            return await provider.chat_completion(messages=MESSAGES, temperature=temperature)
        if valid:
            await invoke()
            assert len(calls) == 1
            if temperature is None: assert 'temperature' not in calls[0]
            else: assert calls[0]['temperature'] == temperature
        else:
            with pytest.raises(ProviderError) as caught: await invoke()
            assert caught.value.code == 'malformed_response' and caught.value.attempts == 0 and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,operation', [('openai', 'chat'), ('openai', 'stream'), ('openai', 'embed'), ('anthropic', 'chat'), ('anthropic', 'stream')])
@pytest.mark.parametrize('sleeper', ['stalled', 'healthy', 'cancel', 'normal_delay'])
async def test_f7_retry_sleeper_has_owned_deadline(kind, operation, sleeper):
    calls, delays, finalizers = [], [], []
    entered = asyncio.Event()
    delay = .06 if sleeper == 'normal_delay' else .001
    async def sleep(value):
        delays.append(value); entered.set()
        try:
            if sleeper in ('stalled', 'cancel'): await asyncio.Event().wait()
            elif sleeper == 'normal_delay': await asyncio.sleep(value)
        finally:
            await asyncio.sleep(.003)
            finalizers.append(True)
    def handle(request):
        calls.append(request)
        if len(calls) == 1: return httpx.Response(503)
        if operation == 'embed': return httpx.Response(200, json={'model': 'text-embedding-3-small', 'data': [{'index': 0, 'embedding': [1., 2., 3.]}]})
        if operation == 'stream':
            if kind == 'anthropic':
                values = anthropic_events(); values[0]['message']['model'] = 'chat-model'; raw = anthropic_wire(values)
            else: raw = openai_wire([choice({'content': 'hello'}, 'stop'), usage()])
            return httpx.Response(200, content=raw)
        return httpx.Response(200, json=body(kind))
    async with adapter(kind, config(kind, max_attempts=2, timeout=.02, retry_base_delay=delay, max_backoff_delay=delay), transport=httpx.MockTransport(handle), sleep=sleep) as provider:
        async def invoke():
            if operation == 'stream': return [c async for c in provider.chat_completion_stream(messages=MESSAGES)]
            if operation == 'embed': return await provider.get_embedding('hello')
            return await provider.chat_completion(messages=MESSAGES)
        started = time.monotonic()
        task = asyncio.create_task(invoke())
        try:
            if sleeper == 'cancel':
                await asyncio.wait_for(entered.wait(), .2); task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
            elif sleeper == 'stalled':
                # Host bound distinguishes the original unbounded wait. Provider
                # must return its own typed timeout and join the sleeper first.
                with pytest.raises(ProviderError) as caught: await asyncio.wait_for(task, .15)
                assert caught.value.code == 'timeout' and caught.value.attempts == 1
                assert time.monotonic() - started < .1
            else:
                await asyncio.wait_for(task, .3)
                if sleeper == 'normal_delay': assert time.monotonic() - started >= delay
            assert len(calls) == (1 if sleeper in ('stalled', 'cancel') else 2)
            assert delays == [delay] and finalizers == [True]
        finally:
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
