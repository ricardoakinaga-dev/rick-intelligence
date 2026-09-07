from __future__ import annotations

import pytest

from rick_contracts.providers import ChatCompletionResult, EmbeddingResult
from rick_providers import ProviderError, ProviderMessage, ProviderBudgetError, ResilientProvider


class FakeProvider:
    def __init__(self, failures: int = 0):
        self.failures = failures
        self.calls = 0

    async def chat_completion(self, *args, correlation_id=None, **kwargs):
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise ProviderError("server_error", "chat_completion", correlation_id or "corr", 1)
        return ChatCompletionResult(model="test", content="ok", correlation_id=correlation_id or "corr")

    async def get_embedding(self, text, *, model=None, correlation_id=None):
        return EmbeddingResult(model="test", dimensions=1, vector=[1.0], correlation_id=correlation_id or "corr")


@pytest.mark.asyncio
async def test_resilient_provider_opens_after_finite_transient_failures_and_recovers():
    now = [10.0]
    fake = FakeProvider(failures=3)
    provider = ResilientProvider(fake, failure_threshold=2, cooldown_seconds=5, clock=lambda: now[0])

    for _ in range(2):
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(messages=[{"role": "user", "content": "hello"}])
        assert caught.value.code == "server_error"
    assert provider.is_open is True
    with pytest.raises(ProviderError) as opened:
        await provider.chat_completion(messages=[{"role": "user", "content": "hello"}])
    assert opened.value.code == "unavailable"
    assert fake.calls == 2

    now[0] = 16.0
    fake.failures = 0
    result = await provider.chat_completion(messages=[{"role": "user", "content": "hello"}])
    assert result.content == "ok"
    assert provider.is_open is False


@pytest.mark.asyncio
async def test_resilient_provider_enforces_budgets_without_calling_backend():
    fake = FakeProvider()
    provider = ResilientProvider(fake, max_messages=1, max_prompt_chars=5, max_embedding_chars=4)
    with pytest.raises(ProviderBudgetError):
        await provider.chat_completion(messages=[{"role": "user", "content": "too long"}])
    with pytest.raises(ProviderBudgetError):
        await provider.get_embedding("too long")
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_resilient_provider_preserves_correlation_and_embedding_contract():
    fake = FakeProvider()
    provider = ResilientProvider(fake)
    result = await provider.get_embedding("ok", correlation_id="corr-fixed")
    assert result.correlation_id == "corr-fixed"
