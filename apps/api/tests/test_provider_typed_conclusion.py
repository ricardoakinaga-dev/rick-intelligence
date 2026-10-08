"""AUD03-14 public termination regressions from the independent I1 probes.

All HTTP calls use MockTransport; publication uses in-memory canonical knowledge.
"""
import hashlib
import json
import re
from contextlib import aclosing

import httpx
import pytest

from rick_contracts.providers import ChatCompletionResult, ChatCompletionChunk
from rick_knowledge import InMemoryKnowledgeStore, Collection, Document, Chunk
from rick_professor import ProfessorLimits
from rick_providers import OpenAICompatibleClient, ProviderConfig, ProviderError
from services.professor_backend import ProfessorChatBackend, ProfessorBackendError

CTX = {
    'tenant_id': 'tenant-i1', 'workspace_id': 'workspace-i1', 'user_id': 'user-i1',
    'permissions': ['chat.query'], 'allowed_collection_ids': ['collection-i1'],
}
QUERY = 'How do I upload a document?'
TEXT = 'To upload a document, select a collection, choose the file, then submit the upload.'
CHECKSUM = hashlib.sha256(TEXT.encode()).hexdigest()
MISSING = object()

def config():
    return ProviderConfig(base_url='https://i1.invalid/v1', chat_model='model-i1', embedding_model='embed-i1', embedding_dimensions=2, environment='test', max_attempts=1, timeout=1)

def make_provider(body, stream=False):
    calls = []

    def handle(req):
        calls.append(str(req.url))
        return httpx.Response(200, content=body, headers={'content-type': 'text/event-stream' if stream else 'application/json'}, request=req)
    return (OpenAICompatibleClient(config(), transport=httpx.MockTransport(handle)), calls)

def result_bytes(reason='stop', content='complete'):
    c = {'index': 0, 'logprobs': None, 'message': {'role': 'assistant', 'content': content}}
    if reason is not MISSING:
        c['finish_reason'] = reason
    return json.dumps({'id': 'chatcmpl_typed', 'object': 'chat.completion', 'created': 123, 'model': 'model-i1', 'choices': [c]}).encode()

def event(delta='', reason=None):
    c = {'index': 0, 'delta': {'content': delta}}
    if reason is not MISSING:
        c['finish_reason'] = reason
    return {'id': 'chatcmpl_typed', 'object': 'chat.completion.chunk', 'created': 123, 'model': 'model-i1', 'choices': [c], 'usage': None}

def sse(events, done=True):
    core = {'id': 'chatcmpl_typed', 'object': 'chat.completion.chunk', 'created': 123, 'model': 'model-i1', 'usage': None}
    events = [{**core, **e} for e in events]
    if not any(e.get('usage') is not None for e in events):
        events.append({**core, 'choices': [], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
    return (''.join(('data: ' + json.dumps(e) + '\n\n' for e in events)) + ('data: [DONE]\n\n' if done else '')).encode()

@pytest.mark.asyncio
@pytest.mark.parametrize(
    'reason', [MISSING, None, '', 'unrecognized', 'unknown', False, 123, [], {}],
    ids=['missing', 'null', 'empty', 'unrecognized', 'unknown', 'bool', 'number', 'array', 'object'],
)
async def test_json_requires_typed_explicit_valid_finish(reason):
    p, calls = make_provider(result_bytes(reason))
    try:
        with pytest.raises(ProviderError) as caught:
            await p.chat_completion(messages=[{'role': 'user', 'content': 'independent'}])
        assert not caught.value.retryable and len(calls) == 1
        assert caught.value.code in {'missing_field', 'malformed_response'}
    finally:
        await p.aclose()

STREAM_BAD = [
    ('missing', [event('prefix', MISSING)], True),
    ('null', [event('prefix', None)], True),
    ('unknown', [event('prefix', 'unknown')], True),
    ('invalid', [event('prefix', 'invented')], True),
    ('invalid_type', [event('prefix', [])], True),
    ('usage_only', [{'model': 'model-i1', 'choices': [],
                     'usage': {'prompt_tokens': 1, 'completion_tokens': 0, 'total_tokens': 1}}], True),
    ('eof_no_terminal', [event('prefix', None)], False),
    ('stop_no_done', [event('complete', 'stop')], False),
    ('postterminal_content', [event('complete', 'stop'), event('extra', None)], True),
    ('duplicate_terminal', [event('complete', 'stop'), event('', 'stop')], True),
]

@pytest.mark.asyncio
@pytest.mark.parametrize('name,events,done', STREAM_BAD, ids=[x[0] for x in STREAM_BAD])
async def test_sse_rejects_invalid_full_response(name, events, done):
    p, calls = make_provider(sse(events, done), True)
    try:
        with pytest.raises(ProviderError) as caught:
            async with aclosing(p.chat_completion_stream(messages=[{'role': 'user', 'content': 'independent'}])) as source:
                [c async for c in source]
        assert len(calls) == 1 and (not caught.value.retryable)
        assert caught.value.code in {'missing_field', 'malformed_response'}
    finally:
        await p.aclose()

@pytest.mark.asyncio
async def test_sse_valid_split_and_terminal_then_usage():
    p, _ = make_provider(sse([event('split ', None), event('answer', 'stop'), {'model': 'model-i1', 'choices': [], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}]), True)
    try:
        chunks = [c async for c in p.chat_completion_stream(messages=[{'role': 'user', 'content': 'hi'}])]
        assert ''.join((c.delta for c in chunks)) == 'split answer' and chunks[-1].finish_reason == 'stop'
    finally:
        await p.aclose()

@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['json', 'stream'])
@pytest.mark.parametrize('content', ['{"ok":true}', '{"incomplete":', '{"x":1} trailing', '{"x":NaN}', '{"x":1,"x":2}', '[1,2]', ''], ids=['valid', 'truncated', 'trailing', 'nan', 'duplicates', 'array', 'empty'])
async def test_json_object_completion_full_content(path, content):
    raw = result_bytes('stop', content) if path == 'json' else sse([event(content[:3], None), event(content[3:], 'stop')])
    p, _ = make_provider(raw, path == 'stream')
    try:

        async def invoke():
            kw = {'messages': [{'role': 'user', 'content': 'hi'}], 'response_format': {'type': 'json_object'}}
            if path == 'json':
                return await p.chat_completion(**kw)
            async with aclosing(p.chat_completion_stream(**kw)) as source:
                return [c async for c in source]
        if content == '{"ok":true}':
            await invoke()
        else:
            with pytest.raises(ProviderError):
                await invoke()
    finally:
        await p.aclose()

@pytest.mark.parametrize('reason', ['stop', 'length', 'content_filter', 'tool_calls'])
@pytest.mark.asyncio
async def test_json_preserves_recognized_finish_distinction(reason):
    payload = json.loads(result_bytes(reason))
    if reason == 'tool_calls':
        payload['choices'][0]['message']['tool_calls'] = [{
            'id': 'valid-finish-call', 'type': 'function',
            'function': {'name': 'status', 'arguments': '{}'},
        }]
    p, _ = make_provider(json.dumps(payload).encode())
    try:
        r = await p.chat_completion(messages=[{'role': 'user', 'content': 'hi'}])
        assert r.finish_reason == reason
    finally:
        await p.aclose()

def world():
    k = InMemoryKnowledgeStore()
    k.upsert_collection(Collection(tenant_id=CTX['tenant_id'], workspace_id=CTX['workspace_id'], collection_id='collection-i1'))
    k.upsert_document(Document(tenant_id=CTX['tenant_id'], workspace_id=CTX['workspace_id'], collection_id='collection-i1', document_id='doc-i1', document_version='v1', status='published', content_checksum=CHECKSUM, title='I1 upload', filename='i1.txt'))
    k.replace_document_chunks('doc-i1', [Chunk(tenant_id=CTX['tenant_id'], document_id='doc-i1', chunk_id='chunk-i1', text=TEXT, checksum=CHECKSUM)])
    return k

class Retrieval:

    async def retrieve(self, **kw):
        return {'evidence': [{**{k: CTX[k] for k in ['tenant_id', 'workspace_id']}, 'collection_id': 'collection-i1', 'document_id': 'doc-i1', 'chunk_id': 'chunk-i1', 'text': 'untrusted', 'retrieval_quality_score': 0.99}]}

class TypedGeneration:

    def __init__(self, reason='stop', mutation=None, stream_kind='normal'):
        self.reason = reason
        self.mutation = mutation
        self.stream_kind = stream_kind

    def answer(self, messages):
        source = re.search('SOURCE (ev_[a-f0-9]{32})', messages[0].content).group(1)
        assert TEXT in messages[0].content
        return f'{TEXT} [cite:{source}]'

    async def chat_completion(self, *, messages, correlation_id):
        text = self.answer(messages)
        if self.mutation:
            self.mutation()
        kw = {'model': 'typed-i1', 'content': text, 'correlation_id': correlation_id}
        if self.reason is not MISSING:
            kw['finish_reason'] = self.reason
        return ChatCompletionResult(**kw)

    async def chat_completion_stream(self, *, messages, correlation_id):
        yield ChatCompletionChunk(model='typed-i1', delta=self.answer(messages), correlation_id=correlation_id)
        if self.mutation:
            self.mutation()
        if self.stream_kind != 'no_terminal':
            yield ChatCompletionChunk(model='typed-i1', finish_reason=self.reason, correlation_id=correlation_id)
        if self.stream_kind == 'post_content':
            yield ChatCompletionChunk(model='typed-i1', delta='extra', correlation_id=correlation_id)
        if self.stream_kind == 'post_tool':
            yield ChatCompletionChunk(model='typed-i1', tool_calls=[{'index': 0, 'id': 'tool-i1', 'type': 'function', 'function': {'name': 'after_stop', 'arguments': '{}'}}], correlation_id=correlation_id)

async def delivered(b, path, context):
    if path == 'json':
        return await b.generate(message=QUERY, context=context, conversation_id='publication-i1')
    async with aclosing(b.generate_stream(message=QUERY, context=context, conversation_id='publication-i1')) as source:
        events = [e async for e in source]
    return events[-1]['result']

@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['json', 'stream', 'buffered'])
@pytest.mark.parametrize('reason', ['stop', 'length', 'content_filter', 'tool_calls', 'unknown', MISSING], ids=['stop', 'length', 'content_filter', 'tool_calls', 'unknown', 'missing_typed_finish'])
async def test_approved_requires_explicit_successful_finish(path, reason):
    p = TypedGeneration(reason)
    if path == 'buffered':
        p.chat_completion_stream = None
    b = ProfessorChatBackend(retrieval=Retrieval(), knowledge=world(), provider=p)
    if reason == 'stop':
        r = await delivered(b, path, CTX)
        assert r['metadata']['evidence_status'] == 'APPROVED_EVIDENCE' and r['metadata']['publication_validation'] == 'verified'
    else:
        with pytest.raises(ProfessorBackendError):
            await delivered(b, path, CTX)

@pytest.mark.asyncio
@pytest.mark.parametrize('stream_kind', ['no_terminal', 'post_content', 'post_tool'])
async def test_professor_typed_stream_rejects_incomplete_and_postterminal(stream_kind):
    b = ProfessorChatBackend(retrieval=Retrieval(), knowledge=world(), provider=TypedGeneration(stream_kind=stream_kind))
    with pytest.raises(ProfessorBackendError):
        await delivered(b, 'stream', CTX)

@pytest.mark.asyncio
async def test_professor_typed_postterminal_tool_within_budget_still_rejected():
    b = ProfessorChatBackend(retrieval=Retrieval(), knowledge=world(), provider=TypedGeneration(stream_kind='post_tool'), limits=ProfessorLimits(max_tool_calls=1))
    with pytest.raises(ProfessorBackendError):
        await delivered(b, 'stream', CTX)

@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['json', 'stream'])
@pytest.mark.parametrize('mode', ['valid', 'missing', 'null', 'unknown', 'length', 'stop_no_done', 'postterminal'])
async def test_http_typed_transport_through_professor_publication(path, mode):

    def handle(req):
        messages = json.loads(req.content)['messages']
        source = re.search('SOURCE (ev_[a-f0-9]{32})', messages[0]['content']).group(1)
        answer = f'{TEXT} [cite:{source}]'
        reason = {'valid': 'stop', 'missing': MISSING, 'null': None, 'unknown': 'unknown', 'length': 'length', 'stop_no_done': 'stop', 'postterminal': 'stop'}[mode]
        if path == 'json':
            raw = result_bytes(reason, answer)
        else:
            events = [event(answer, reason)]
            if mode == 'postterminal':
                events.append(event('extra', None))
            raw = sse(events, mode != 'stop_no_done')
        return httpx.Response(200, content=raw, headers={'content-type': 'text/event-stream' if path == 'stream' else 'application/json'}, request=req)
    p = OpenAICompatibleClient(config(), transport=httpx.MockTransport(handle))
    b = ProfessorChatBackend(retrieval=Retrieval(), knowledge=world(), provider=p)
    try:
        if mode == 'valid' or (path == 'json' and mode in ['stop_no_done', 'postterminal']):
            r = await delivered(b, path, CTX)
            assert r['metadata']['evidence_status'] == 'APPROVED_EVIDENCE' and r['metadata']['publication_validation'] == 'verified'
        else:
            with pytest.raises(ProfessorBackendError):
                await delivered(b, path, CTX)
    finally:
        await p.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('split', [False, True])
@pytest.mark.parametrize('tail', ['content', 'tools', 'terminal', 'invalid_json', 'usage'])
async def test_http_post_done_data_fails_before_public_professor_final(split, tail):
    def handle(req):
        messages = json.loads(req.content)['messages']
        source = re.search(r'SOURCE (ev_[a-f0-9]{32})', messages[0]['content']).group(1)
        answer = f'{TEXT} [cite:{source}]'
        extras = {
            'content': event('contradictory tail'),
            'tools': {'model': 'model-i1', 'choices': [{'delta': {'tool_calls': [{
                'index': 0, 'id': 'after', 'type': 'function',
                'function': {'name': 'after_stop', 'arguments': '{}'},
            }]}}]},
            'terminal': event('', 'stop'),
            'invalid_json': '{truncated',
            'usage': {'model': 'model-i1', 'choices': [],
                      'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}},
        }
        extra = extras[tail]
        encoded = extra if isinstance(extra, str) else json.dumps(extra)
        events = [event(answer[:3]), event(answer[3:], 'stop')] if split else [event(answer, 'stop')]
        raw = sse(events) + ('data: ' + encoded + '\n\n').encode()
        return httpx.Response(200, content=raw, request=req)

    provider = OpenAICompatibleClient(config(), transport=httpx.MockTransport(handle))
    backend = ProfessorChatBackend(retrieval=Retrieval(), knowledge=world(), provider=provider)
    seen = []
    try:
        with pytest.raises(ProfessorBackendError) as caught:
            async with aclosing(backend.generate_stream(
                message=QUERY, context=CTX, conversation_id='post-done-publication',
            )) as source:
                async for output in source:
                    seen.append(output)
        assert caught.value.stage == 'provider_failed'
        assert all(output['type'] == 'delta' and output['provisional'] for output in seen)
        assert bool(seen) is split
    finally:
        await provider.aclose()
