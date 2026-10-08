"""Refusal must not disappear when selecting content from JSON or SSE."""
import json

import httpx
import pytest
from test_critic_remediation import openai_completion_wire, USAGE

from rick_providers import OpenAICompatibleClient, ProviderConfig, ProviderError


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("refusal", ["declined", " ", False, [], {}, 1, None, ""])
async def test_explicit_refusal_cannot_become_successful_content(streaming, refusal):
    message = {"role": "assistant", "content": "otherwise complete", "refusal": refusal}
    body = {'id': 'chatcmpl_fixture', 'object': 'chat.completion', 'created': 123, "model": "refusal-test", "choices": [{'index': 0, 'logprobs': None,
        "delta" if streaming else "message": message, "finish_reason": "stop",
    }]}
    wire = json.dumps(body).encode()
    if streaming:
        body["usage"] = USAGE
        wire = openai_completion_wire(body)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=wire, request=request)

    provider = OpenAICompatibleClient(
        ProviderConfig(base_url="http://refusal.invalid/v1", chat_model="refusal-test",
                       environment="test", max_attempts=3, timeout=1),
        transport=httpx.MockTransport(handle),
    )

    async def complete():
        messages = [{"role": "user", "content": "request"}]
        if streaming:
            return [chunk async for chunk in provider.chat_completion_stream(messages=messages)]
        return await provider.chat_completion(messages=messages)

    async with provider:
        if refusal is None or refusal == "":
            result = await complete()
            assert (result[-1].delta if streaming else result.content) == "otherwise complete"
        else:
            with pytest.raises(ProviderError) as caught:
                await complete()
            assert caught.value.code == "malformed_response"
            assert not caught.value.retryable and caught.value.attempts == 1
            assert "declined" not in str(caught.value)
    assert len(calls) == 1
