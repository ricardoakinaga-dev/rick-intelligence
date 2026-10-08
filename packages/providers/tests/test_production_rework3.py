"""Regressions for the nine confirmed provider critic v3 findings."""
import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from rick_contracts.providers import ChatCompletionChunk
from rick_providers import ProviderError, ResilientProvider
from rick_providers.cleanup import CleanupError
from test_critic_remediation import config, adapter, body, MESSAGES, openai_completion_wire


class RetryTransport(httpx.MockTransport):
    def __init__(self, *, failures=1, stall=False):
        super().__init__(lambda _: httpx.Response(200, json=body()))
        self.failures, self.stall = failures, stall
        self.calls = 0
        self.loops = []

    async def aclose(self):
        self.calls += 1
        self.loops.append(asyncio.get_running_loop())
        if self.calls <= self.failures:
            if self.stall:
                await asyncio.Event().wait()
            raise RuntimeError('synthetic transport close failure')


@pytest.mark.asyncio
@pytest.mark.parametrize('stall', [False, True])
@pytest.mark.parametrize('kind', ['openai', 'anthropic'])
async def test_f2_owned_transport_close_retries_after_httpx_closed(kind, stall):
    transport = RetryTransport(failures=2, stall=stall)
    provider = adapter(kind, config(kind), transport=transport)
    # Both native adapters inherit the same lazy transport ownership boundary.
    client = provider._ensure_client()
    async def bounded_close():
        await asyncio.wait_for(provider.aclose(), .7)
    for attempt in (1, 2):
        with pytest.raises(CleanupError):
            await bounded_close()
        assert client.is_closed and provider._client is client
        assert transport.calls == attempt
    await bounded_close()
    await bounded_close()
    assert transport.calls == 3 and provider._client is None
    assert len(set(transport.loops)) == 1
    with pytest.raises(RuntimeError, match='closed'):
        provider._ensure_client()


@pytest.mark.asyncio
async def test_f2_caller_owned_httpx_client_and_transport_remain_open():
    transport = RetryTransport(failures=0)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = adapter('openai', config(), client=client)
        await provider.chat_completion(messages=MESSAGES)
        await provider.aclose()
        await provider.aclose()
        assert not client.is_closed and transport.calls == 0
    assert transport.calls == 1


def completion_wire(payload):
    return openai_completion_wire(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream'])
@pytest.mark.parametrize('fault', ['outer_unknown', 'choice_unknown', 'message_unknown', 'wrong_index', 'bool_index', 'duplicate', 'additional_refusal'])
async def test_f4_single_choice_unknown_field_rejection_through_transport(operation, fault):
    payload = body()
    choice = payload['choices'][0]
    if operation == 'stream':
        choice['delta'] = choice.pop('message')
    field = 'delta' if operation == 'stream' else 'message'
    if fault == 'outer_unknown':
        payload['unknown_field'] = 1
    elif fault == 'choice_unknown':
        choice['unknown_field'] = 1
    elif fault == 'message_unknown':
        choice[field]['unknown_field'] = 1
    elif fault == 'wrong_index':
        choice['index'] = 7
    elif fault == 'bool_index':
        choice['index'] = False
    else:
        other = copy.deepcopy(choice)
        if fault == 'additional_refusal':
            other[field]['refusal'] = 'blocked'
        payload['choices'].append(other)
    raw = completion_wire(payload) if operation == 'stream' else json.dumps(payload).encode()
    chunks = []
    async with adapter('openai', config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))) as provider:
        with pytest.raises(ProviderError) as caught:
            if operation == 'stream':
                async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                    chunks.append(chunk)
            else:
                await provider.chat_completion(messages=MESSAGES)
        assert caught.value.code == 'malformed_response'
        assert not any(chunk.finish_reason for chunk in chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream'])
async def test_f4_documented_native_metadata_remains_compatible(operation):
    payload = body()
    payload.update(id='chatcmpl-test', created=1, object='chat.completion' if operation=='chat' else 'chat.completion.chunk',
                   service_tier='default', system_fingerprint=None, metadata={'request': 'test'}, moderation=None)
    choice = payload['choices'][0]
    choice['logprobs'] = {'content': [], 'refusal': None}
    choice['message'].update(refusal=None, function_call=None, audio=None, annotations=[
        {'type': 'url_citation', 'url_citation': {'start_index': 0, 'end_index': 2, 'title': 'source', 'url': 'https://source.invalid'}}])
    if operation == 'stream':
        choice['delta'] = choice.pop('message')
        payload['obfuscation'] = 'random padding'
        choice['delta']['role'] = None
    raw = completion_wire(payload) if operation == 'stream' else json.dumps(payload).encode()
    async with adapter('openai', config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))) as provider:
        if operation == 'stream':
            chunks = [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
            assert sum(chunk.finish_reason is not None for chunk in chunks) == 1
        else:
            assert (await provider.chat_completion(messages=MESSAGES)).content == 'hello'


@pytest.mark.asyncio
@pytest.mark.parametrize('late', ['content', 'tool', 'terminal', 'usage'])
async def test_f5_facade_withholds_terminal_on_post_terminal_events(late):
    finalized = []
    async def stream(*args, **kwargs):
        try:
            yield ChatCompletionChunk(model='chat-model', delta='ok', correlation_id='probe')
            yield ChatCompletionChunk(model='chat-model', finish_reason='stop', correlation_id='probe')
            values = {'content': {'delta': 'late'}, 'tool': {'tool_calls': [{'index': 0, 'function': {'arguments': '{}'}}]},
                      'terminal': {'finish_reason': 'stop'}, 'usage': {'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}}
            yield ChatCompletionChunk(model='chat-model', correlation_id='probe', **values[late])
        finally:
            finalized.append(True)
    facade = ResilientProvider(SimpleNamespace(chat_completion=lambda *a, **kw: None,
        get_embedding=lambda *a, **kw: None, chat_completion_stream=stream))
    chunks = []
    with pytest.raises(ProviderError) as caught:
        async for chunk in facade.chat_completion_stream(messages=MESSAGES):
            chunks.append(chunk)
    assert caught.value.code == 'malformed_response'
    assert [chunk.delta for chunk in chunks] == ['ok']
    assert not any(chunk.finish_reason for chunk in chunks) and finalized == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream'])
@pytest.mark.parametrize('cache,write,valid', [(8,8,False),(8,2,True),(None,10,True)])
async def test_f6_combined_cache_subsets_are_bounded_by_prompt(operation, cache, write, valid):
    payload = body()
    payload['usage'] = {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12,
                        'prompt_tokens_details': {'cached_tokens': cache, 'cache_write_tokens': write}}
    if operation == 'stream':
        payload['choices'][0]['delta'] = payload['choices'][0].pop('message')
    raw = completion_wire(payload) if operation == 'stream' else json.dumps(payload).encode()
    async with adapter('openai', config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))) as provider:
        async def call():
            if operation == 'stream':
                return [chunk async for chunk in provider.chat_completion_stream(messages=MESSAGES)]
            return await provider.chat_completion(messages=MESSAGES)
        if valid:
            await call()
        else:
            with pytest.raises(ProviderError) as caught:
                await call()
            assert caught.value.code == 'malformed_response'


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream', 'alias'])
@pytest.mark.parametrize('model,supported', [('gpt-5.1',True),('gpt-5.2',True),('gpt-5.1-2025-11-13',True),
    ('gpt-5.2-2025-12-11',True),('gpt-5',False),('gpt-5.2-pro',False),('gpt-5.3',False),('gpt-5.4',False),('gpt-6-astra',False)])
async def test_f7_explicit_sampling_model_matrix_and_no_io_rejection(operation, model, supported):
    requests = []
    payload = body(); payload['model'] = model
    if operation == 'stream':
        payload['choices'][0]['delta'] = payload['choices'][0].pop('message')
    raw = completion_wire(payload) if operation == 'stream' else json.dumps(payload).encode()
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=raw)
    async with adapter('openai', config(chat_model=model), transport=httpx.MockTransport(handle)) as provider:
        async def call():
            if operation == 'stream':
                return [x async for x in provider.chat_completion_stream(messages=MESSAGES, temperature=.7)]
            if operation == 'alias':
                return await provider.chat(MESSAGES, temperature=.7)
            return await provider.chat_completion(messages=MESSAGES, temperature=.7)
        if supported:
            await call()
            assert requests[0]['temperature'] == .7
            assert 'reasoning_effort' not in requests[0]
        else:
            with pytest.raises(ProviderError) as caught:
                await call()
            assert caught.value.code == 'invalid_configuration' and caught.value.attempts == 0
            assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('usage,valid', [({'prompt_tokens': 2,'total_tokens': 2},True),
    ({'prompt_tokens': -1,'total_tokens': False,'unknown_field': 1},False),
    ({'prompt_tokens': 1,'total_tokens': True},False),({'prompt_tokens': 2,'total_tokens': 3},False),
    ({'prompt_tokens': 2,'total_tokens': 2,'unknown_field': 1},False),({'total_tokens': 2},False)])
async def test_f9_embedding_usage_validated_without_changing_dto(usage, valid):
    payload = {'object': 'list','model': 'text-embedding-3-small', 'data': [{'object': 'embedding','index': 0,'embedding': [1.,2.,3.]}], 'usage': usage}
    async with adapter('openai', config(embedding_model=payload['model']), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as provider:
        if valid:
            result = await provider.get_embedding('input')
            assert set(result.model_dump()) == {'contract_version','model','dimensions','vector','correlation_id'}
        else:
            with pytest.raises(ProviderError) as caught:
                await provider.get_embedding('input')
            assert caught.value.code == 'malformed_response'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['raises', 'false'])
async def test_facade_close_retries_failures_and_closes_success_once(failure):
    calls = []
    async def close():
        calls.append(asyncio.get_running_loop())
        if len(calls) <= 2:
            if failure == 'false':
                return False
            raise RuntimeError('synthetic failure')
    facade = ResilientProvider(SimpleNamespace(chat_completion=lambda *a, **kw: None,
        get_embedding=lambda *a, **kw: None, aclose=close))
    for _ in range(2):
        with pytest.raises(CleanupError):
            await facade.aclose()
    await facade.aclose()
    await facade.aclose()
    assert len(calls) == 3 and set(calls) == {asyncio.get_running_loop()}
