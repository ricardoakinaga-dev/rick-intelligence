from __future__ import annotations

import pytest

from rick_contracts.providers import (
    ChatCompletionResult,
    EmbeddingResult,
    ProviderToolCall,
    ProviderToolCallFunction,
)
from rick_providers import ProviderError, ProviderMessage, ProviderBudgetError, ResilientProvider


class FakeProvider:
    def __init__(self, failures: int = 0, tool_calls: int = 0):
        self.failures = failures
        self.tool_calls = tool_calls
        self.calls = 0

    async def chat_completion(self, *args, correlation_id=None, **kwargs):
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise ProviderError("server_error", "chat_completion", correlation_id or "corr", 1)
        calls = [
            ProviderToolCall(
                id=f"call-{index}",
                type="function",
                function=ProviderToolCallFunction(name="report_status", arguments='{"status":"ok"}'),
            )
            for index in range(self.tool_calls)
        ]
        return ChatCompletionResult(
            model="test",
            content="ok" if not calls else "",
            tool_calls=calls or None,
            correlation_id=correlation_id or "corr",
        )

    async def get_embedding(self, text, *, model=None, correlation_id=None):
        return EmbeddingResult(model="test", dimensions=1, vector=[1.0], correlation_id=correlation_id or "corr")


class HealthAwareProvider(FakeProvider):
    def __init__(self, available: bool = True):
        super().__init__()
        self.available = available

    async def health_check(self):
        return self.available


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
    assert await provider.health_check() is False
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
async def test_resilient_provider_rejects_oversized_tool_definitions_before_backend() -> None:
    fake = FakeProvider()
    provider = ResilientProvider(fake, max_tool_calls=1)
    tools = [
        {"type": "function", "function": {"name": "first"}},
        {"type": "function", "function": {"name": "second"}},
    ]

    with pytest.raises(ProviderBudgetError, match="tool budget"):
        await provider.chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            tools=tools,
        )

    assert fake.calls == 0


@pytest.mark.asyncio
async def test_resilient_provider_rejects_oversized_tool_response_at_boundary() -> None:
    fake = FakeProvider(tool_calls=2)
    provider = ResilientProvider(fake, max_tool_calls=1)

    with pytest.raises(ProviderBudgetError, match="tool-call budget"):
        await provider.chat_completion(messages=[{"role": "user", "content": "hello"}])

    assert fake.calls == 1


@pytest.mark.asyncio
async def test_resilient_provider_preserves_correlation_and_embedding_contract():
    fake = FakeProvider()
    provider = ResilientProvider(fake)
    result = await provider.get_embedding("ok", correlation_id="corr-fixed")
    assert result.correlation_id == "corr-fixed"


@pytest.mark.asyncio
async def test_resilient_provider_delegates_live_health_and_fails_closed() -> None:
    fake = HealthAwareProvider()
    provider = ResilientProvider(fake)

    assert await provider.health_check() is True
    fake.available = False
    assert await provider.health_check() is False


@pytest.mark.asyncio
async def test_resilient_provider_fails_closed_without_a_live_probe() -> None:
    """A port with no probe is not healthy — circuit state is not reachability."""
    provider = ResilientProvider(FakeProvider())

    assert await provider.health_check() is False
    assert provider.readiness_check() is True


class DeclaredProvider(FakeProvider):
    """A port that declares its own production decision but exposes no probe."""

    def __init__(self, *, production_safe: bool) -> None:
        super().__init__()
        self.production_safe = production_safe


class NonProductionPort(HealthAwareProvider):
    """A test port with a working probe: still never production-safe."""

    is_test_provider = True


def test_production_safe_requires_a_probe_or_an_explicit_declaration() -> None:
    # Synthetic port: no probe and no declaration => fail closed.
    bare = ResilientProvider(FakeProvider())
    assert bare.production_safe is False
    assert getattr(FakeProvider, "health_check", None) is None

    # The same class of port with a live probe is admitted.
    probed = ResilientProvider(HealthAwareProvider())
    assert probed.production_safe is True

    # An explicit declaration is an owned decision and does not need a probe.
    assert ResilientProvider(DeclaredProvider(production_safe=True)).production_safe is True
    assert ResilientProvider(DeclaredProvider(production_safe=False)).production_safe is False

    # A test port is never production-safe, probe or not.
    assert ResilientProvider(NonProductionPort()).production_safe is False


def test_the_official_client_is_admitted_through_its_own_probe() -> None:
    from rick_providers import ProviderConfig, create_provider
    from rick_providers.client import OpenAICompatibleClient

    provider = create_provider(ProviderConfig(
        base_url="https://provider.example/v1",
        api_key="test-only-key",
        chat_model="chat-test-model",
        embedding_model="embedding-test-model",
        embedding_dimensions=3,
        environment="test",
    ))
    try:
        assert isinstance(provider, OpenAICompatibleClient)
        assert callable(provider.health_check)
        assert ResilientProvider(provider).production_safe is True
    finally:
        import asyncio

        asyncio.run(provider.aclose())
