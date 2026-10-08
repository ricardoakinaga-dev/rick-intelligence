import asyncio

import pytest

from rick_providers.cleanup import CleanupError
from rick_providers.resilience import ResilientProvider
import rick_providers.resilience as resilience


class ClosingProvider:
    def __init__(self, first="ok"):
        self.first = first
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = self.effects = 0

    async def chat_completion(self, *args, **kwargs):
        raise AssertionError("not used by close")

    async def get_embedding(self, *args, **kwargs):
        raise AssertionError("not used by close")

    async def aclose(self):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        if self.calls == 1 and self.first == "error":
            raise RuntimeError("synthetic unfinished close")
        if self.calls == 1 and self.first == "false":
            return False
        self.effects += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["ok", "error", "false"])
@pytest.mark.parametrize("cancellations", [0, 1, 2])
async def test_close_retains_completed_effect_and_retries_only_unfinished(first, cancellations):
    provider = ClosingProvider(first)
    facade = ResilientProvider(provider)
    caller = asyncio.create_task(facade.aclose())
    await asyncio.wait_for(provider.entered.wait(), 2)
    for _ in range(cancellations):
        assert caller.cancel()
        await asyncio.sleep(0)
    provider.release.set()
    if cancellations:
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert caller.cancelling() == cancellations
    elif first != "ok":
        with pytest.raises(CleanupError):
            await caller
    else:
        await caller
    assert provider.calls == 1
    assert provider.effects == (1 if first == "ok" else 0)
    await facade.aclose()
    await facade.aclose()
    assert provider.calls == (1 if first == "ok" else 2)
    assert provider.effects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_first", [False, True])
async def test_concurrent_close_joins_one_effect(cancel_first):
    provider = ClosingProvider()
    facade = ResilientProvider(provider)
    first = asyncio.create_task(facade.aclose())
    await asyncio.wait_for(provider.entered.wait(), 2)
    second = asyncio.create_task(facade.aclose())
    for _ in range(8):
        await asyncio.sleep(0)
    if cancel_first:
        assert first.cancel()
    provider.release.set()
    outcomes = await asyncio.gather(first, second, return_exceptions=True)
    assert isinstance(outcomes[0], asyncio.CancelledError) if cancel_first else outcomes[0] is None
    assert outcomes[1] is None
    await facade.aclose()
    assert (provider.calls, provider.effects) == (1, 1)


@pytest.mark.asyncio
async def test_cooperative_close_timeout_remains_retryable(monkeypatch):
    monkeypatch.setattr(resilience, "FACADE_CLEANUP_SECONDS", .01)
    provider = ClosingProvider()
    facade = ResilientProvider(provider)
    with pytest.raises(CleanupError):
        await facade.aclose()
    assert (provider.calls, provider.effects) == (1, 0)
    provider.release.set()
    await facade.aclose()
    await facade.aclose()
    assert (provider.calls, provider.effects) == (2, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["healthy", "pending", "acknowledged"])
async def test_sync_health_preserves_pending_caller_cancellation(behavior):
    provider = ClosingProvider()

    def health():
        if behavior == "acknowledged":
            asyncio.current_task().uncancel()
        return True

    provider.health_check = health
    facade = ResilientProvider(provider)

    async def invoke():
        if behavior != "healthy":
            asyncio.current_task().cancel()
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                pass
        return await facade.health_check()

    caller = asyncio.create_task(invoke())
    if behavior == "pending":
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert caller.cancelling() == 1
    else:
        assert await caller is True
        assert caller.cancelling() == 0
