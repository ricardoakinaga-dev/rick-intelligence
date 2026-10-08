"""Public cancellation contracts for the resilience facade, without provider I/O."""
from __future__ import annotations

import asyncio
from collections import Counter

import httpx
import pytest

from rick_contracts.providers import ChatCompletionChunk, ChatCompletionResult, EmbeddingResult
from rick_providers import (
    OpenAICompatibleClient, ProviderBudgetError, ProviderConfig, ProviderError, ResilientProvider,
)


class CallerTask(asyncio.Task):
    """Observe accidental cancellation count manipulation by the boundary."""

    def __init__(self, coroutine):
        super().__init__(coroutine)
        self.cancel_calls = 0
        self.uncancel_calls = 0

    def cancel(self, msg=None):
        self.cancel_calls += 1
        return super().cancel(msg)

    def uncancel(self):
        self.uncancel_calls += 1
        return super().uncancel()


class Delegate:
    def __init__(self, behavior="healthy"):
        self.behavior = behavior
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.effects = Counter()
        self.calls = Counter()
        self.closes = 0
        self.result = None

    async def complete(self, operation, result):
        self.calls[operation] += 1
        if self.behavior == "failure":
            raise ProviderError("server_error", "chat_completion", "facade13", 1)
        if self.behavior != "healthy":
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                if self.behavior == "cooperative":
                    raise
                if self.behavior == "acknowledged":
                    assert asyncio.current_task().uncancel() == 0
        self.effects[operation] += 1
        self.result = result
        return result

    async def chat_completion(self, *args, **kwargs):
        return await self.complete("chat", ChatCompletionResult(
            model="facade-test", content="completed", finish_reason="stop", correlation_id="facade13",
        ))

    async def get_embedding(self, *args, **kwargs):
        return await self.complete("embedding", EmbeddingResult(
            model="facade-test", vector=[1.0], dimensions=1, correlation_id="facade13",
        ))

    async def health_check(self):
        return await self.complete("health", True)

    async def aclose(self):
        self.closes += 1


async def invoke(facade, operation, chunks=None):
    if operation == "chat":
        return await facade.chat_completion(messages=[{"role": "user", "content": "hello"}])
    if operation == "embedding":
        return await facade.get_embedding("hello")
    if operation == "health":
        return await facade.health_check()
    async for chunk in facade.chat_completion_stream(messages=[{"role": "user", "content": "hello"}]):
        chunks.append(chunk)


async def cancel_when_entered(delegate, coroutine):
    task = CallerTask(coroutine)
    entered = asyncio.create_task(delegate.entered.wait())
    try:
        done, _ = await asyncio.wait({task, entered}, timeout=2, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
            pytest.fail("delegate returned before reaching the cancellation barrier")
        assert entered in done, "delegate did not reach the cancellation barrier"
    finally:
        entered.cancel()
        try:
            await entered
        except asyncio.CancelledError:
            pass
    assert task.cancel("caller stopped")
    return task


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["chat", "embedding", "health", "fallback_stream"])
@pytest.mark.parametrize("behavior", ["swallowed", "cooperative", "acknowledged", "healthy"])
async def test_public_delegate_cancellation_and_success_controls(operation, behavior):
    delegate = Delegate(behavior)
    facade = ResilientProvider(delegate)
    chunks = []
    if behavior == "healthy":
        task = CallerTask(invoke(facade, operation, chunks))
    else:
        task = await cancel_when_entered(delegate, invoke(facade, operation, chunks))
    if behavior in ("swallowed", "cooperative"):
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert task.cancelling() == 1
        assert chunks == []
    else:
        result = await task
        assert not task.cancelled()
        assert task.cancelling() == 0
        if operation == "fallback_stream":
            assert len(chunks) == 1
            assert chunks[0].delta == "completed"
            assert chunks[0].finish_reason == "stop"
        else:
            assert result is delegate.result
    assert task.cancel_calls == (behavior != "healthy")
    assert task.uncancel_calls == (behavior == "acknowledged")
    actual_operation = "chat" if operation == "fallback_stream" else operation
    assert delegate.calls == {actual_operation: 1}
    assert delegate.effects == ({} if behavior == "cooperative" else {actual_operation: 1})
    assert facade.readiness_check()
    assert delegate.closes == 0


class Stream:
    def __init__(self, delegate, stage):
        self.delegate, self.stage = delegate, stage
        self.reads = 0
        self.closes = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.reads += 1
        if self.reads > 2:
            raise StopAsyncIteration
        chunk = ChatCompletionChunk(
            model="facade-test", delta="completed" if self.reads == 1 else "",
            finish_reason=None if self.reads == 1 else "stop", correlation_id="facade13",
        )
        if (self.stage == "content" and self.reads == 1) or (self.stage == "terminal" and self.reads == 2):
            return await self.delegate.complete("stream_read", chunk)
        return chunk

    async def aclose(self):
        self.closes += 1


class StreamingDelegate(Delegate):
    def __init__(self, behavior, stage):
        super().__init__(behavior)
        self.stage = stage
        self.stream = Stream(self, stage)

    async def chat_completion_stream(self, *args, **kwargs):
        self.calls["stream"] += 1
        if self.stage == "setup":
            return await self.complete("stream_setup", self.stream)
        return self.stream


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["setup", "content", "terminal"])
@pytest.mark.parametrize("behavior", ["swallowed", "cooperative", "healthy"])
async def test_public_stream_cancellation_never_yields_cancelled_work(stage, behavior):
    delegate = StreamingDelegate(behavior, stage)
    facade = ResilientProvider(delegate)
    chunks = []
    if behavior == "healthy":
        task = CallerTask(invoke(facade, "stream", chunks))
        await task
        assert [chunk.delta for chunk in chunks] == ["completed", ""]
        assert [chunk.finish_reason for chunk in chunks] == [None, "stop"]
    else:
        task = await cancel_when_entered(delegate, invoke(facade, "stream", chunks))
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert task.cancelling() == 1
        assert [chunk.delta for chunk in chunks] == (["completed"] if stage == "terminal" else [])
        assert not any(chunk.finish_reason for chunk in chunks)
    assert task.cancel_calls == (behavior != "healthy")
    assert task.uncancel_calls == 0
    assert delegate.calls["stream"] == 1
    assert delegate.closes == 0
    assert delegate.stream.closes == (0 if stage == "setup" and behavior == "cooperative" else 1)
    if stage == "setup" and behavior == "swallowed":
        assert delegate.stream.reads == 0
    assert delegate.effects == ({} if behavior == "cooperative" else {
        "stream_setup" if stage == "setup" else "stream_read": 1,
    })
    assert facade.readiness_check()


@pytest.mark.asyncio
async def test_stream_setup_explicit_uncancel_allows_content_and_terminal():
    delegate = StreamingDelegate("acknowledged", "setup")
    chunks = []
    task = await cancel_when_entered(delegate, invoke(ResilientProvider(delegate), "stream", chunks))
    await task
    assert task.cancelling() == 0
    assert task.cancel_calls == task.uncancel_calls == 1
    assert [chunk.finish_reason for chunk in chunks] == [None, "stop"]
    assert delegate.stream.closes == 1
    assert delegate.closes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["chat", "embedding", "health", "fallback_stream", "stream"])
async def test_cancelled_success_does_not_reset_or_increment_public_circuit(operation):
    delegate = StreamingDelegate("failure", "setup") if operation == "stream" else Delegate("failure")
    facade = ResilientProvider(delegate, failure_threshold=2)
    with pytest.raises(ProviderError):
        await invoke(facade, "chat")
    delegate.behavior = "swallowed"
    task = await cancel_when_entered(delegate, invoke(facade, operation, []))
    with pytest.raises(asyncio.CancelledError):
        await task
    assert facade.readiness_check()  # Cancellation did not increment the failure count.
    delegate.behavior = "failure"
    with pytest.raises(ProviderError) as caught:
        await invoke(facade, "chat")
    assert caught.value.code == "server_error"
    assert facade.is_open  # Cancellation did not erase the preceding failure.
    calls = delegate.calls.copy()
    with pytest.raises(ProviderError) as opened:
        await invoke(facade, "chat")
    assert opened.value.code == "unavailable"
    assert await facade.health_check() is False
    assert delegate.calls == calls
    assert delegate.closes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["healthy", "acknowledged"])
async def test_completed_success_still_resets_public_circuit(behavior):
    delegate = Delegate("failure")
    facade = ResilientProvider(delegate, failure_threshold=2)
    with pytest.raises(ProviderError):
        await invoke(facade, "chat")
    delegate.behavior = behavior
    if behavior == "healthy":
        await invoke(facade, "chat")
    else:
        task = await cancel_when_entered(delegate, invoke(facade, "chat"))
        await task
    delegate.behavior = "failure"
    with pytest.raises(ProviderError):
        await invoke(facade, "chat")
    assert facade.readiness_check()
    with pytest.raises(ProviderError):
        await invoke(facade, "chat")
    assert facade.is_open


@pytest.mark.asyncio
async def test_outer_timeout_still_expires_when_delegate_swallows_cancellation():
    delegate = Delegate("swallowed")
    facade = ResilientProvider(delegate)
    limit = asyncio.timeout(0.01)
    with pytest.raises(TimeoutError):
        async with limit:
            await invoke(facade, "chat")
    assert limit.expired()
    assert asyncio.current_task().cancelling() == 0
    assert delegate.calls == {"chat": 1}
    assert delegate.effects == {"chat": 1}
    assert delegate.closes == 0
    assert facade.readiness_check()


@pytest.mark.asyncio
async def test_input_budgets_still_reject_before_delegate_effects():
    delegate = Delegate()
    facade = ResilientProvider(delegate, max_prompt_chars=3, max_embedding_chars=3)
    with pytest.raises(ProviderBudgetError):
        await invoke(facade, "chat")
    with pytest.raises(ProviderBudgetError):
        await invoke(facade, "embedding")
    with pytest.raises(ProviderBudgetError):
        await invoke(facade, "stream", [])
    assert delegate.calls == delegate.effects == {}
    assert delegate.closes == 0


class BorrowedClientDelegate(Delegate):
    """Complete real adapter I/O before a cancellable delegate postprocessing step."""

    def __init__(self, behavior, adapter):
        super().__init__(behavior)
        self.adapter = adapter

    async def chat_completion(self, *args, **kwargs):
        result = await self.adapter.chat_completion(*args, **kwargs)
        return await self.complete("chat", result)

    async def get_embedding(self, *args, **kwargs):
        result = await self.adapter.get_embedding(*args, **kwargs)
        return await self.complete("embedding", result)

    async def health_check(self):
        return await self.complete("health", await self.adapter.health_check())

    async def aclose(self):
        self.closes += 1
        await self.adapter.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["chat", "embedding", "health"])
@pytest.mark.parametrize("behavior", ["healthy", "swallowed", "acknowledged"])
async def test_completed_adapter_effects_are_not_replayed_and_borrowed_client_is_not_closed(operation, behavior):
    requests = []
    responses = []

    def handle(request):
        requests.append(request)
        if operation == "health":
            payload = {"data": [{"id": "facade-test"}]}
        elif operation == "embedding":
            payload = {"model": "facade-embedding", "data": [{"index": 0, "embedding": [1.0]}]}
        else:
            payload = {"model": "facade-test", "choices": [{
                "message": {"role": "assistant", "content": "completed"}, "finish_reason": "stop",
            }]}
        response = httpx.Response(200, json=payload)
        responses.append(response)
        return response

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter = OpenAICompatibleClient(ProviderConfig(
        provider_kind="openai_compatible", environment="test", base_url="https://facade.invalid/v1",
        chat_model="facade-test", embedding_model="facade-embedding", embedding_dimensions=1,
        timeout=1, max_attempts=3, retry_base_delay=0,
    ), client=client)
    delegate = BorrowedClientDelegate(behavior, adapter)
    facade = ResilientProvider(delegate)
    try:
        if behavior == "healthy":
            task = CallerTask(invoke(facade, operation))
        else:
            task = await cancel_when_entered(delegate, invoke(facade, operation))
        if behavior == "swallowed":
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelling() == 1
        else:
            assert await task is delegate.result
            assert task.cancelling() == 0
        assert task.cancel_calls == (behavior != "healthy")
        assert task.uncancel_calls == (behavior == "acknowledged")
        assert len(requests) == 1
        assert all(response.is_closed for response in responses)
        assert delegate.effects == {operation: 1}
        assert delegate.closes == 0
        assert not client.is_closed
        await facade.aclose()
        assert delegate.closes == 1
        assert not client.is_closed
    finally:
        await client.aclose()
