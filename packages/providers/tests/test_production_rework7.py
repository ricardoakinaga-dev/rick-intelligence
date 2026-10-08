"""Memory-only public-boundary discriminators for the provider v7 findings."""
import copy
import json

import httpx
import pytest

from rick_providers import AnthropicMessagesClient, OpenAICompatibleClient, ProviderConfig, ProviderError

MESSAGES = [{'role': 'user', 'content': 'Reply'}]
MODEL = 'chat-model'
CLAUDE = 'claude-sonnet-4-5-20250929'
SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'string'}},
          'required': ['answer'], 'additionalProperties': False}

def fmt(schema=SCHEMA, strict=True):
    return {'type': 'json_schema', 'json_schema': {'name': 'reply', 'schema': copy.deepcopy(schema), 'strict': strict}}

def config(kind, model=None):
    return ProviderConfig(provider_kind=kind, environment='test',
                          base_url='https://provider.invalid/v1', api_key='synthetic-test-key',
                          chat_model=model or (CLAUDE if kind == 'anthropic' else MODEL),
                          max_attempts=3, retry_base_delay=0, timeout=1)

def body(kind, text, model=None, **metadata):
    model = model or (CLAUDE if kind == 'anthropic' else MODEL)
    if kind == 'anthropic':
        return dict(id='msg_1', type='message', role='assistant', model=model,
                    content=[dict(type='text', text=text, **metadata)], stop_reason='end_turn',
                    stop_sequence=None, usage={'input_tokens': 2, 'output_tokens': 3})
    return dict(id='chatcmpl_1', object='chat.completion', created=123, model=model,
                choices=[dict(index=0, logprobs=None, message={'role': 'assistant', 'content': text}, finish_reason='stop')],
                usage={'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5})

def stream_events(kind, text, model=None, **metadata):
    value = body(kind, text, model, **metadata)
    if kind == 'anthropic':
        value.update(content=[], stop_reason=None, usage={'input_tokens': 2, 'output_tokens': 0})
        return [dict(type='message_start', message=value),
                dict(type='content_block_start', index=0, content_block=dict(type='text', text='', **metadata)),
                dict(type='content_block_delta', index=0, delta={'type': 'text_delta', 'text': text}),
                dict(type='content_block_stop', index=0),
                dict(type='message_delta', delta={'stop_reason': 'end_turn', 'stop_sequence': None}, usage={'output_tokens': 3}),
                dict(type='message_stop')]
    base = {k: value[k] for k in ('id', 'created', 'model')}
    base.update(object='chat.completion.chunk')
    return [dict(base, usage=None, choices=[dict(index=0, delta={'content': text}, finish_reason=None)]),
            dict(base, usage=None, choices=[dict(index=0, delta={}, finish_reason='stop')]),
            dict(base, choices=[], usage=value['usage'])]

def wire(kind, events):
    if kind == 'anthropic':
        return b''.join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)
    return b''.join(f'data: {json.dumps(e)}\n\n'.encode() for e in events) + b'data: [DONE]\n\n'

class Delivery(httpx.AsyncByteStream):
    def __init__(self, raw): self.raw, self.closes = raw, 0
    async def __aiter__(self): yield self.raw
    async def aclose(self): self.closes += 1

async def exercise(kind, mode, text, response_format=None, error=None, *, model=None,
                   actual_model=None, events=None, accepted=False, **metadata):
    chunks, calls = [], []
    raw = wire(kind, events if events is not None else stream_events(kind, text, actual_model, **metadata)) if mode == 'stream' else json.dumps(body(kind, text, actual_model, **metadata)).encode()
    delivery = Delivery(raw)
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, stream=delivery)
    cls = AnthropicMessagesClient if kind == 'anthropic' else OpenAICompatibleClient
    async with cls(config(kind, model), transport=httpx.MockTransport(handle)) as provider:
        async def invoke():
            if mode == 'chat':
                return await provider.chat_completion(messages=MESSAGES, response_format=response_format)
            async for chunk in provider.chat_completion_stream(messages=MESSAGES, response_format=response_format):
                chunks.append(chunk)
            return chunks[-1]
        if error:
            with pytest.raises(ProviderError) as caught: await invoke()
            assert caught.value.code == error
            assert not caught.value.retryable
            assert caught.value.attempts == 1
            assert not any(c.finish_reason for c in chunks)
            if accepted: assert any(c.delta == text for c in chunks)
        else:
            result = await invoke()
            assert result.finish_reason == 'stop'
            assert result.model == (actual_model or model or (CLAUDE if kind == 'anthropic' else MODEL))
            if mode == 'stream':
                assert ''.join(c.delta for c in chunks) == text
                assert sum(c.finish_reason is not None for c in chunks) == 1
                assert all(c.model == result.model for c in chunks)
    assert len(calls) == delivery.closes == 1
    assert calls[0]['model'] == (model or (CLAUDE if kind == 'anthropic' else MODEL))

@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['chat', 'stream'])
@pytest.mark.parametrize('text,error', [('not JSON', 'invalid_json'), ('{"answer":7}', 'malformed_response'),
                                         ('{"different":"ok"}', 'malformed_response'), ('{"answer":"ok"}', None)])
async def test_confirmed_schema(mode, text, error):
    await exercise('openai', mode, text, fmt(), error, accepted=mode == 'stream' and error is not None)

@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['chat', 'stream'])
@pytest.mark.parametrize('citations,valid', [(None, True), ([], True), (False, False), (0, False), ('', False), ({}, False), ([{'type': 'unsupported'}], False)])
async def test_confirmed_citations(mode, citations, valid):
    await exercise('anthropic', mode, 'healthy', error=None if valid else 'malformed_response', citations=citations)

@pytest.mark.asyncio
@pytest.mark.parametrize('error', [None, False, 0, '', {}, {'message': 'private-payload'}])
async def test_confirmed_health_error(error):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={'type': 'model', 'id': CLAUDE, 'error': error})
    async with AnthropicMessagesClient(config('anthropic'), transport=httpx.MockTransport(handle)) as provider:
        assert await provider.health_check() is False
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_health_and_absent_citation_controls():
    async with AnthropicMessagesClient(config('anthropic'), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'type': 'model', 'id': CLAUDE,
        'display_name': 'Claude Sonnet 4.5', 'created_at': '2025-09-29T00:00:00Z'}))) as provider:
        assert await provider.health_check() is True
    for mode in ('chat', 'stream'): await exercise('anthropic', mode, 'healthy')

@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['chat', 'stream'])
@pytest.mark.parametrize('schema', [
    {'type': 'unsupported'}, {'required': 'answer'}, {'additionalProperties': 0},
    {'type': 'string', 'minLength': -1}, {'type': 'number', 'multipleOf': 0},
    {'unknownConstraint': True}, {'$schema': 'http://json-schema.org/draft-07/schema#'},
    {'$schema': 'https://unreachable.invalid/meta'}, {'$ref': 'https://unreachable.invalid/schema'},
    {'$ref': 'file:///etc/passwd'}, {'$ref': '#/properties/answer'},
    {'properties': {'answer': {'$dynamicRef': 'https://unreachable.invalid/schema'}}},
    {'properties': {'answer': {'format': 'email'}}}, {'properties': {'answer': {'pattern': '(a+)+$'}}},
    {'allOf': [{'type': 'object'}]}, {'items': [{'type': 'string'}]},
    {'properties': {'answer': {'$schema': 'http://json-schema.org/draft-07/schema#'}}},
    {'properties': {1: {'type': 'string'}}},
])
async def test_schema_configuration_rejected_before_io(mode, schema):
    calls = []
    def handle(request):
        calls.append(request)
        raise AssertionError('invalid configuration reached I/O')
    async with OpenAICompatibleClient(config('openai'), transport=httpx.MockTransport(handle)) as provider:
        with pytest.raises(ProviderError) as caught:
            if mode == 'chat': await provider.chat_completion(messages=MESSAGES, response_format=fmt(schema))
            else:
                async for _ in provider.chat_completion_stream(messages=MESSAGES, response_format=fmt(schema)): pass
        assert caught.value.code == 'malformed_response' and caught.value.attempts == 0
        assert not caught.value.retryable
        assert 'unreachable' not in str(caught.value) and '/etc' not in str(caught.value)
    assert not calls

@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['chat', 'stream'])
@pytest.mark.parametrize('schema,good,bad', [
    ({'type': 'string', 'minLength': 2, 'maxLength': 3}, '"ok"', '"long"'),
    ({'type': ['string', 'null'], 'enum': ['ok', None]}, 'null', '"different"'),
    ({'type': 'integer', 'minimum': 2, 'maximum': 4, 'multipleOf': 2}, '4', '3'),
    ({'type': 'number', 'exclusiveMinimum': 2, 'exclusiveMaximum': 4}, '3', '4'),
    ({'type': 'integer'}, '1', 'true'),
    ({'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 2, 'uniqueItems': True}, '["ok"]', '["ok","ok"]'),
    ({'type': 'array', 'prefixItems': [{'type': 'string'}, {'type': 'integer'}], 'items': False}, '["ok",1]', '["ok",1,2]'),
    ({'type': 'object', 'additionalProperties': {'type': 'integer'}, 'minProperties': 1, 'maxProperties': 2}, '{"a":1}', '{"a":"wrong"}'),
    ({'type': 'object', 'properties': {'answer': False}, 'additionalProperties': False}, '{}', '{"answer":"no"}'),
    ({'const': {'answer': 'ok'}, 'title': 'Reply', 'description': 'metadata', 'default': {}, 'examples': [], 'deprecated': False, 'readOnly': True, 'writeOnly': False}, '{"answer":"ok"}', '{}'),
    ({'$schema': 'https://json-schema.org/draft/2020-12/schema', **SCHEMA}, '{"answer":"ok"}', '{"answer":"ok","extra":1}'),
])
async def test_supported_schema_constraints(mode, schema, good, bad):
    await exercise('openai', mode, good, fmt(schema, strict=False))
    await exercise('openai', mode, bad, fmt(schema), 'malformed_response', accepted=mode == 'stream')

@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['chat', 'stream'])
@pytest.mark.parametrize('text,error', [('{"answer":"a","answer":"b"}', 'invalid_json'),
                                      ('{"answer":NaN}', 'invalid_json'),
                                      ('{"answer":Infinity}', 'invalid_json'),
                                      ('{"answer":1e999}', 'malformed_response')])
async def test_schema_strict_json_syntax(mode, text, error):
    await exercise('openai', mode, text, fmt(), error, accepted=mode == 'stream')

@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'openai_compatible', 'anthropic'])
@pytest.mark.parametrize('mode', ['chat', 'stream'])
async def test_json_object_and_text_policy_retained(kind, mode):
    await exercise(kind, mode, 'not JSON')
    await exercise(kind, mode, '{"answer":"ok"}', {'type': 'json_object'})
    await exercise(kind, mode, 'not JSON', {'type': 'json_object'}, 'invalid_json', accepted=mode == 'stream')
    await exercise(kind, mode, '[]', {'type': 'json_object'}, 'malformed_response', accepted=mode == 'stream')

@pytest.mark.asyncio
@pytest.mark.parametrize('kind,requested,actual,valid', [
    ('openai', 'gpt-4o-mini', 'gpt-4o-mini-2024-07-18', True),
    ('openai', 'gpt-4o-mini', 'gpt-4o-mini-2099-01-01', False),
    ('openai', 'gpt-4o-mini', 'gpt-4o-2024-08-06', False),
    ('openai', 'gpt-4o-mini-2024-07-18', 'gpt-4o-mini', False),
    ('openai_compatible', 'gpt-4o-mini', 'gpt-4o-mini-2024-07-18', False),
    ('anthropic', 'claude-sonnet-4-5', CLAUDE, True),
    ('anthropic', 'claude-haiku-4-5', 'claude-haiku-4-5-20251001', True),
    ('anthropic', 'claude-sonnet-4-5', 'claude-sonnet-4-5-20250230', False),
    ('anthropic', 'claude-sonnet-4-5', 'claude-sonnet-4-6', False),
    ('anthropic', 'claude-sonnet-4-5', 'claude-haiku-4-5-20251001', False),
    ('anthropic', CLAUDE, 'claude-sonnet-4-5', False),
    ('anthropic', 'claude-sonnet-4-6', 'claude-sonnet-4-6-20260101', False),
    ('anthropic', 'claude-sonnet-5', 'claude-sonnet-5-20260101', False),
])
@pytest.mark.parametrize('mode', ['chat', 'stream'])
async def test_documented_aliases_only(kind, requested, actual, valid, mode):
    await exercise(kind, mode, 'healthy', model=requested, actual_model=actual,
                   error=None if valid else 'invalid_model')

@pytest.mark.asyncio
@pytest.mark.parametrize('frame', [1, 2])
@pytest.mark.parametrize('field', ['model', 'id', 'created'])
async def test_alias_stream_identity_cannot_change(frame, field):
    events = stream_events('openai', 'healthy', 'gpt-4o-mini-2024-07-18')
    events[frame][field] = {'model': 'gpt-4o-mini', 'id': 'different', 'created': 124}[field]
    await exercise('openai', 'stream', 'healthy', model='gpt-4o-mini', events=events,
                   error='invalid_model' if field == 'model' else 'malformed_response', accepted=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['chat', 'stream'])
async def test_schema_resource_limits(mode):
    schema = {'type': 'string', 'description': 'x' * 65_536}
    calls = []
    async with OpenAICompatibleClient(config('openai'), transport=httpx.MockTransport(lambda request: calls.append(request))) as provider:
        with pytest.raises(ProviderError) as caught:
            if mode == 'chat': await provider.chat_completion(messages=MESSAGES, response_format=fmt(schema))
            else:
                async for _ in provider.chat_completion_stream(messages=MESSAGES, response_format=fmt(schema)): pass
        assert caught.value.code == 'malformed_response' and caught.value.attempts == 0
    assert not calls
    await exercise('openai', mode, json.dumps(list(range(257))), fmt({'type': 'array'}), 'malformed_response', accepted=mode == 'stream')
    await exercise('openai', mode, '[' * 33 + '0' + ']' * 33, fmt({}), 'malformed_response', accepted=mode == 'stream')

def test_reference_registry_denies_retrieval():
    from referencing.exceptions import NoSuchResource
    from rick_providers.structured import OFFLINE_REGISTRY
    for uri in ['https://unreachable.invalid/schema', 'file:///etc/passwd']:
        with pytest.raises(NoSuchResource): OFFLINE_REGISTRY.get_or_retrieve(uri)
