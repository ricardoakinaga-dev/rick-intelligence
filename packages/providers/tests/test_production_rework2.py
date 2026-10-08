"""Fresh socket-free negative reproductions for confirmed critic v2 defects."""
import asyncio
import copy
import json
import time

import httpx
import pytest

from rick_providers import ProviderError, ProviderConfigurationError, ResilientProvider
from rick_providers.client import _normalize_openai_usage
from rick_providers.anthropic import _usage
from test_critic_remediation import config, adapter, body, wire, MESSAGES, invoke, openai_completion_wire


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'stream', 'alias'])
@pytest.mark.parametrize('kind,model,temperature,supported', [
    ('anthropic', 'claude-sonnet-4-5-20250929', .7, True),
    ('anthropic', 'claude-opus-4-6', .7, True),
    ('anthropic', 'claude-sonnet-5-5', .7, False),
    ('anthropic', 'claude-sonnet-5-5', 1, True),
    ('openai', 'gpt-5', .7, False),
    ('openai', 'gpt-6-astra', .2, False),
    ('openai_compatible', 'gpt-5', .7, True),
])
async def test_f2_explicit_sampling_before_io(operation, kind, model, temperature, supported):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        raw = wire(kind).replace(b'chat-model', model.encode()) if operation == 'stream' else json.dumps(body(kind)).replace('chat-model', model).encode()
        return httpx.Response(200, content=raw)
    async with adapter(kind, config(kind, chat_model=model, timeout=1), transport=httpx.MockTransport(handle)) as provider:
        async def call():
            if operation == 'stream':
                return [x async for x in provider.chat_completion_stream(messages=MESSAGES, temperature=temperature)]
            if operation == 'alias':
                return await provider.chat(MESSAGES, temperature=temperature)
            return await provider.chat_completion(messages=MESSAGES, temperature=temperature)
        if supported:
            await call()
            assert requests[0]['temperature'] == temperature
        else:
            with pytest.raises(ProviderError) as exc:
                await call()
            assert exc.value.code == 'invalid_configuration' and exc.value.attempts == 0
            assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,model', [('openai', 'gpt-5'), ('anthropic', 'claude-sonnet-5-5')])
@pytest.mark.parametrize('operation', ['chat', 'stream'])
async def test_f2_facade_implicit_sampling_is_usable(kind, model, operation):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        raw = wire(kind) if operation == 'stream' else json.dumps(body(kind)).encode()
        return httpx.Response(200, content=raw.replace(b'chat-model', model.encode()))
    async with adapter(kind, config(kind, chat_model=model, timeout=1), transport=httpx.MockTransport(handle)) as provider:
        await invoke(ResilientProvider(provider), operation)
        assert 'temperature' not in requests[0]


@pytest.mark.parametrize('details', [
    {'prompt_tokens_details': {'text_tokens': 2, 'image_tokens': 0, 'cache_write_tokens': 2, 'cached_tokens': None, 'audio_tokens': None}},
    {'completion_tokens_details': {'text_tokens': 3, 'reasoning_tokens': None, 'accepted_prediction_tokens': None}},
])
def test_f3_current_openai_schema_optional_native_details(details):
    value = {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5, **details}
    assert _normalize_openai_usage(value, 'chat_completion', 'probe', 1).total_tokens == 5


@pytest.mark.parametrize('details', [
    {'prompt_tokens_details': {'cached_tokens': 200}},
    {'prompt_tokens_details': {'text_tokens': True}},
    {'prompt_tokens_details': {'image_tokens': -1}},
    {'prompt_tokens_details': {'cache_write_tokens': '2'}},
    {'prompt_tokens_details': {'audio_tokens': 1, 'image_tokens': 1, 'text_tokens': 1}},
    {'completion_tokens_details': {'text_tokens': 3, 'reasoning_tokens': 1}},
    {'completion_tokens_details': {'rejected_prediction_tokens': 4}},
])
def test_f4_openai_detail_relationships(details):
    with pytest.raises(ProviderError):
        _normalize_openai_usage({'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5, **details}, 'chat_completion', 'probe', 1)


def native_usage():
    return {'input_tokens': 2, 'output_tokens': 3, 'cache_creation_input_tokens': 4,
            'cache_read_input_tokens': 5, 'cache_creation': {'ephemeral_1h_input_tokens': 1, 'ephemeral_5m_input_tokens': 3},
            'output_tokens_details': {'thinking_tokens': 2}, 'server_tool_use': {'web_fetch_requests': 0, 'web_search_requests': 1},
            'inference_geo': 'global', 'service_tier': 'standard'}


def test_f4_native_envelope_and_nullable_optional_counters():
    assert _usage(native_usage(), 'probe', 1).model_dump() == {'prompt_tokens': 11, 'completion_tokens': 3, 'total_tokens': 14}
    assert _usage({'input_tokens': 2, 'output_tokens': 3, 'cache_creation_input_tokens': None,
                   'cache_read_input_tokens': None, 'cache_creation': None, 'output_tokens_details': None}, 'probe', 1).total_tokens == 5


@pytest.mark.parametrize('replacement', [
    {'cache_creation': {'ephemeral_1h_input_tokens': -1, 'ephemeral_5m_input_tokens': 5}},
    {'cache_creation': {'ephemeral_1h_input_tokens': True, 'ephemeral_5m_input_tokens': 3}},
    {'cache_creation': {'ephemeral_1h_input_tokens': 1, 'ephemeral_5m_input_tokens': 4}},
    {'cache_creation': {'ephemeral_1h_input_tokens': 1}},
    {'cache_creation': {'ephemeral_1h_input_tokens': 1, 'ephemeral_5m_input_tokens': 3, 'invented_tokens': 0}},
    {'output_tokens_details': {'thinking_tokens': True}},
    {'output_tokens_details': {'thinking_tokens': -1}},
    {'output_tokens_details': {'thinking_tokens': 4}},
    {'output_tokens_details': {'thinking_tokens': '2'}},
    {'server_tool_use': {'web_fetch_requests': True, 'web_search_requests': 0}},
])
def test_f4_anthropic_nested_detail_relationships(replacement):
    with pytest.raises(ProviderError):
        _usage({**native_usage(), **replacement}, 'probe', 1)


def tool_wire(calls, *, split=False):
    base = {'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, 'usage': None, 'model': 'chat-model', 'choices': [{'logprobs': None, 'index': 0, 'delta': {'tool_calls': calls}, 'finish_reason': None}]}
    values = [base]
    if split:
        values.append({'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, 'usage': None, 'model': 'chat-model', 'choices': [{'logprobs': None, 'index': 0, 'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '}'}}]}, 'finish_reason': None}]})
    values.append({'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, 'usage': None, 'model': 'chat-model', 'choices': [{'logprobs': None, 'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})
    values.append({'id': 'chatcmpl_fixture', 'object': 'chat.completion.chunk', 'created': 123, 'model': 'chat-model', 'choices': [], 'usage': {'prompt_tokens': 8, 'completion_tokens': 4, 'total_tokens': 12}})
    return ''.join('data: '+json.dumps(x)+'\n\n' for x in values).encode()+b'data: [DONE]\n\n'


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['duplicate', 'outer', 'function', 'valid_split'])
async def test_f5_exact_tool_mappings_and_per_event_indices(fault):
    calls = [{'index': 0, 'id': 'call_1', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{}'}}]
    if fault == 'duplicate':
        calls.append(copy.deepcopy(calls[0]))
    if fault == 'outer':
        calls[0]['refusal'] = 'lost'
    if fault == 'function':
        calls[0]['function']['refusal'] = 'lost'
    if fault == 'valid_split':
        calls[0]['function']['arguments'] = '{'
    chunks = []
    async with adapter('openai', config(timeout=1), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=tool_wire(calls, split=fault=='valid_split')))) as provider:
        try:
            async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                chunks.append(chunk)
        except ProviderError as exc:
            assert fault != 'valid_split' and exc.code == 'malformed_response'
        else:
            assert fault == 'valid_split'
        assert any(c.finish_reason for c in chunks) == (fault == 'valid_split')


class CleanupStream(httpx.AsyncByteStream):
    def __init__(self, raw, *, wait=False, stall_close=False, finalizer_delay=0, stall_finalizer=False):
        self.raw, self.wait, self.stall_close = raw, wait, stall_close
        self.finalizer_delay, self.stall_finalizer = finalizer_delay, stall_finalizer
        self.finalized = self.close_started = self.close_cancelled = self.finalizer_cancelled = False
        self.waiting = asyncio.Event()
        self.closed = 0
    async def __aiter__(self):
        try:
            if self.raw:
                yield self.raw
            if self.wait:
                self.waiting.set()
                await asyncio.Event().wait()
        finally:
            try:
                if self.stall_finalizer:
                    await asyncio.Event().wait()
                await asyncio.sleep(self.finalizer_delay)
                self.finalized = True
            except asyncio.CancelledError:
                self.finalizer_cancelled = True
                raise
    async def aclose(self):
        self.close_started = True
        self.closed += 1
        try:
            if self.stall_close:
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.close_cancelled = True
            raise


def pending():
    return {t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()}


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'anthropic'])
@pytest.mark.parametrize('operation', ['chat', 'stream', 'embed', 'health'])
async def test_f6_timeout_with_hanging_response_close_is_finite(kind, operation):
    stream = CleanupStream(b'', wait=True, stall_close=True)
    tasks = pending()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as client:
        provider = adapter(kind, config(kind, timeout=.02), client=client)
        started = time.monotonic()
        if operation == 'health':
            assert await asyncio.wait_for(invoke(provider, operation), .8) is False
        else:
            with pytest.raises(ProviderError) as caught:
                await asyncio.wait_for(invoke(provider, operation), .8)
            assert caught.value.code == 'internal_error' and not caught.value.retryable
        assert time.monotonic()-started < .65
        assert stream.close_started and stream.close_cancelled and stream.closed == 1
        assert stream.finalized
        assert pending() == tasks


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'anthropic'])
@pytest.mark.parametrize('stop', ['parser_error', 'close', 'cancel'])
async def test_f7_original_iterator_finalizer_awaited(kind, stop):
    raw = b'data: not-json\n\n' if kind == 'openai' else b'event: message_start\ndata: not-json\n\n'
    if stop != 'parser_error':
        raw = wire(kind)
        # Emit a nonterminal piece before the suspended read.
        raw = raw[:raw.index(b'\n\n')+2]
        if kind == 'openai':
            raw = raw.replace(b'"finish_reason": "stop"', b'"finish_reason": null')
    stream = CleanupStream(raw, wait=True, finalizer_delay=.02)
    tasks = pending()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as client:
        provider = adapter(kind, config(kind, timeout=.5), client=client)
        iterator = ResilientProvider(provider).chat_completion_stream(messages=MESSAGES)
        if stop == 'parser_error':
            with pytest.raises(ProviderError) as exc:
                await anext(iterator)
            assert exc.value.code == 'invalid_json'
        elif stop == 'close':
            await anext(iterator)
            await iterator.aclose()
        else:
            await anext(iterator)
            task = asyncio.create_task(anext(iterator))
            await stream.waiting.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert stream.finalized and stream.closed == 1
        assert pending() == tasks


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'anthropic'])
@pytest.mark.parametrize('fault', ['response_close', 'finalizer'])
async def test_f6_successful_body_cleanup_failure_has_no_terminal(kind, fault):
    stream = CleanupStream(wire(kind), stall_close=fault=='response_close', stall_finalizer=fault=='finalizer')
    chunks, tasks = [], pending()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as client:
        provider = adapter(kind, config(kind, timeout=.5), client=client)
        with pytest.raises(ProviderError) as exc:
            async for chunk in provider.chat_completion_stream(messages=MESSAGES):
                chunks.append(chunk)
        assert exc.value.code == ('internal_error' if fault == 'response_close' else 'timeout')
        assert not any(c.finish_reason for c in chunks)
        assert pending() == tasks
        assert stream.closed == 1


@pytest.mark.parametrize('kind', ['openai', 'openai_compatible', 'anthropic'])
@pytest.mark.parametrize('host', ['127.0.0.1', 'localhost', '[::1]', 'remote.invalid'])
@pytest.mark.parametrize('environment', ['production', 'prod', 'live'])
def test_f9_all_production_endpoints_require_https(kind, host, environment):
    with pytest.raises(ProviderConfigurationError):
        config(kind, environment=environment, base_url=f'http://{host}:8080/v1', api_key=None).validate()


@pytest.mark.parametrize('environment', ['dev', 'development', 'test', 'testing', 'local'])
def test_f9_explicit_development_loopback_http(environment):
    config('openai_compatible', environment=environment, base_url='http://127.0.0.1:8080/v1', api_key=None).validate()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'anthropic'])
@pytest.mark.parametrize('stop', ['parser_error', 'close', 'cancel'])
@pytest.mark.parametrize('stall', ['iterator', 'response'])
async def test_f6_stalled_finalizer_or_response_on_all_exit_paths(kind, stop, stall):
    raw = b'data: bad\n\n' if kind == 'openai' else b'event: message_start\ndata: bad\n\n'
    if stop != 'parser_error':
        raw = wire(kind)
        raw = raw[:raw.index(b'\n\n')+2]
        if kind == 'openai':
            raw = raw.replace(b'"finish_reason": "stop"', b'"finish_reason": null')
    stream = CleanupStream(raw, wait=True, stall_finalizer=stall=='iterator', stall_close=stall=='response')
    tasks, started = pending(), time.monotonic()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as client:
        provider = adapter(kind, config(kind, timeout=.5), client=client)
        iterator = ResilientProvider(provider).chat_completion_stream(messages=MESSAGES)
        if stop == 'parser_error':
            with pytest.raises(ProviderError) as exc:
                await asyncio.wait_for(anext(iterator), .8)
            assert exc.value.code == 'internal_error'
        elif stop == 'close':
            await anext(iterator)
            with pytest.raises(ProviderError) as exc:
                await asyncio.wait_for(iterator.aclose(), .8)
            assert exc.value.code == 'internal_error'
        else:
            await anext(iterator)
            task = asyncio.create_task(anext(iterator))
            await stream.waiting.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, .8)
        assert time.monotonic()-started < .75
        assert pending() == tasks
        assert stream.closed == 1
        assert stream.finalizer_cancelled if stall == 'iterator' else stream.close_cancelled


class CustomCloseIterator:
    def __init__(self, *, stall=True):
        self.sent = False
        self.cancelled = self.closed = False
        self.stall = stall
    def __aiter__(self):
        return self
    async def __anext__(self):
        from rick_contracts.providers import ChatCompletionChunk
        if self.sent:
            raise StopAsyncIteration
        self.sent = True
        return ChatCompletionChunk(model='custom', delta='ok', finish_reason='stop', correlation_id='custom')
    async def aclose(self):
        try:
            if self.stall:
                await asyncio.Event().wait()
            self.closed = True
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
@pytest.mark.parametrize('stall', [True, False])
async def test_f6_facade_custom_close_is_bounded_before_terminal(stall):
    from types import SimpleNamespace
    source = CustomCloseIterator(stall=stall)
    provider = ResilientProvider(SimpleNamespace(chat_completion=lambda *a, **kw: None, get_embedding=lambda *a, **kw: None, chat_completion_stream=lambda *a, **kw: source))
    chunks, tasks, started = [], pending(), time.monotonic()
    async def consume():
        async for chunk in provider.chat_completion_stream(messages=MESSAGES):
            chunks.append(chunk)
    if stall:
        with pytest.raises(ProviderError) as exc:
            await asyncio.wait_for(consume(), .8)
        assert exc.value.code == 'internal_error' and source.cancelled and not chunks
    else:
        await consume()
        assert source.closed and chunks[-1].finish_reason == 'stop'
    assert time.monotonic()-started < .75 and pending() == tasks


@pytest.mark.asyncio
async def test_f6_owned_client_close_is_bounded_without_leaving_tasks():
    from types import SimpleNamespace
    async def close():
        await asyncio.Event().wait()
    provider = adapter('openai', config())
    provider._client = SimpleNamespace(aclose=close)
    tasks, started = pending(), time.monotonic()
    with pytest.raises(RuntimeError, match='cleanup failed'):
        await asyncio.wait_for(provider.aclose(), .8)
    assert time.monotonic()-started < .65 and pending() == tasks
    assert provider._client is not None  # Failed close never clears ownership.


@pytest.mark.asyncio
async def test_f6_first_failure_safe_log_is_preserved(caplog):
    stream = CleanupStream(b'data: bad\n\n', stall_close=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))) as client:
        provider = adapter('openai', config(), client=client)
        with pytest.raises(ProviderError) as exc:
            await anext(provider.chat_completion_stream(messages=MESSAGES))
        assert exc.value.code == 'internal_error'
    assert 'provider_cleanup_after_failure code=invalid_json' in caplog.text
    assert 'chat-secret' not in caplog.text and 'data: bad' not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'anthropic'])
@pytest.mark.parametrize('operation', ['chat', 'stream'])
@pytest.mark.parametrize('fault', ['healthy', 'bool', 'exceeds_total', 'negative', 'wrong_type'])
async def test_f3_f4_native_usage_envelopes_through_mock_transport(kind, operation, fault):
    if kind == 'anthropic':
        usage = native_usage()
        target, field = usage['output_tokens_details'], 'thinking_tokens'
    else:
        usage = {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5,
                 'prompt_tokens_details': {'text_tokens': 2, 'image_tokens': 0, 'cache_write_tokens': 2, 'cached_tokens': None},
                 'completion_tokens_details': {'text_tokens': 1, 'reasoning_tokens': 2}}
        target, field = usage['completion_tokens_details'], 'reasoning_tokens'
    if fault != 'healthy':
        target[field] = {'bool': True, 'exceeds_total': 100, 'negative': -1, 'wrong_type': '2'}[fault]
    payload = body(kind)
    payload['usage'] = usage
    if operation == 'chat':
        raw = json.dumps(payload).encode()
    elif kind == 'openai':
        payload['choices'][0]['delta'] = payload['choices'][0].pop('message')
        raw = openai_completion_wire(payload)
    else:
        lines = wire(kind).decode().splitlines()
        first = json.loads(lines[1][6:])
        first['message']['usage'] = usage
        lines[1] = 'data: '+json.dumps(first)
        raw = ('\n'.join(lines)+'\n').encode()
    async with adapter(kind, config(kind, timeout=1), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw))) as provider:
        if fault == 'healthy':
            result = await invoke(provider, operation)
            actual = result[-1].usage if operation == 'stream' else result.usage
            assert actual.prompt_tokens == (11 if kind == 'anthropic' else 2)
        else:
            with pytest.raises(ProviderError) as exc:
                await invoke(provider, operation)
            assert exc.value.code == 'malformed_response'


@pytest.mark.parametrize('kind', ['openai', 'openai_compatible', 'anthropic'])
@pytest.mark.parametrize('host', ['127.0.0.1', 'remote.invalid'])
def test_f9_independent_production_embedding_endpoint_also_requires_https(kind, host):
    with pytest.raises(ProviderConfigurationError):
        config(kind, embedding_provider_kind='openai_compatible', embedding_api_key=None,
               embedding_base_url=f'http://{host}:8080/v1').validate()


@pytest.mark.asyncio
async def test_f6_facade_cancellation_awaits_stalled_original_generator_finalizer():
    from types import SimpleNamespace
    from rick_contracts.providers import ChatCompletionChunk
    waiting = asyncio.Event()
    finalizer_cancelled = asyncio.Event()
    async def stream(*a, **kw):
        try:
            yield ChatCompletionChunk(model='custom', delta='ok', correlation_id='custom')
            waiting.set()
            await asyncio.Event().wait()
        finally:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                finalizer_cancelled.set()
                raise
    provider = ResilientProvider(SimpleNamespace(chat_completion=lambda *a, **kw: None, get_embedding=lambda *a, **kw: None, chat_completion_stream=stream))
    iterator = provider.chat_completion_stream(messages=MESSAGES)
    await anext(iterator)
    tasks = pending()
    task = asyncio.create_task(anext(iterator))
    await waiting.wait()
    task.cancel()
    started = time.monotonic()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, .8)
    assert finalizer_cancelled.is_set() and time.monotonic()-started < .75
    assert pending() == tasks


@pytest.mark.asyncio
async def test_f6_close_swallowing_cancellation_cannot_report_success():
    from rick_providers.cleanup import CleanupError, bounded_cleanup
    async def close():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return
    tasks = pending()
    with pytest.raises(CleanupError):
        await bounded_cleanup([close], budget=.01)
    assert pending() == tasks
