"""Focused deterministic tests for lease ownership, races, and expiry."""

import asyncio

import pytest

from rick_locking import (
    InMemoryLeaseClient,
    InMemoryLeaseStore,
    LeaseError,
    LeaseClient,
    ManualClock,
)


@pytest.mark.asyncio
async def test_same_key_race_has_exactly_one_winner() -> None:
    store = InMemoryLeaseStore()
    owners = [f"owner-{number}" for number in range(64)]

    results = await asyncio.gather(
        *(store.acquire("same-key", owner, 10_000) for owner in owners)
    )

    assert sum(results) == 1
    winner = owners[results.index(True)]
    assert await store.release("same-key", winner) is True
    assert len(store) == 0


@pytest.mark.asyncio
async def test_expiry_and_wrong_owner_operations_are_safe() -> None:
    clock = ManualClock()
    store = InMemoryLeaseStore(clock=clock)

    assert await store.acquire("k", "owner-a", 100) is True
    assert await store.acquire("k", "owner-b", 100) is False
    assert await store.renew("k", "owner-b", 100) is False
    assert await store.release("k", "owner-b") is False
    assert store.is_active("k") is True

    # The old owner cannot remove or renew a replacement acquired after expiry.
    clock.advance_ms(100)
    assert await store.renew("k", "owner-a", 100) is False
    assert await store.acquire("k", "owner-b", 100) is True
    assert await store.release("k", "owner-a") is False
    assert await store.renew("k", "owner-a", 100) is False
    assert store.is_active("k") is True

    assert await store.release("k", "owner-b") is True
    assert await store.release("k", "owner-b") is False
    assert store.is_active("k") is False


@pytest.mark.asyncio
async def test_client_generates_owner_bound_handle_and_context_releases() -> None:
    store = InMemoryLeaseStore()
    client = InMemoryLeaseClient(store=store)

    first = await client.acquire("k", 10_000, correlation_id="req-1")
    second = await client.acquire("k", 10_000, correlation_id="req-2")
    assert first is not None
    assert second is None
    assert first.owner and len(first.owner) <= 256
    assert first.owner not in repr(first)
    assert await first.renew() is True
    assert await first.release() is True
    assert await first.release() is False

    async with client.lease("k", 10_000) as lease:
        assert lease is not None
        assert store.is_active("k")
    assert store.is_active("k") is False


@pytest.mark.asyncio
async def test_cancelled_context_waits_for_owner_bound_release() -> None:
    store = InMemoryLeaseStore()
    client = InMemoryLeaseClient(store=store)
    entered = asyncio.Event()

    async def worker() -> None:
        handle = await client.acquire("cancelled", 10_000)
        assert handle is not None
        async with handle:
            entered.set()
            await asyncio.sleep(60)

    task = asyncio.create_task(worker())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The context manager completed its release before cancellation escaped.
    assert store.is_active("cancelled") is False
    assert await store.acquire("cancelled", "replacement", 100) is True
    assert await store.release("cancelled", "replacement") is True


@pytest.mark.asyncio
async def test_backend_failures_are_typed_and_redacted() -> None:
    class FailingStore(InMemoryLeaseStore):
        async def release(self, key, owner, *, correlation_id=None):
            raise RuntimeError(
                "https://user:password@example.test/secret "
                f"owner={owner}"
            )

    secret_url = "https://user:password@example.test/secret"
    client = LeaseClient(FailingStore())
    handle = await client.acquire("k", 100, correlation_id="safe-correlation")
    assert handle is not None

    with pytest.raises(LeaseError) as caught:
        await handle.release()
    error = caught.value
    assert error.code.value == "internal_error"
    assert error.operation == "release"
    assert secret_url not in str(error)
    assert secret_url not in repr(error)
    assert handle.owner not in str(error)
    assert handle.owner not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.to_dto().code == "internal_error"


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_mask_body_failure() -> None:
    class FailingStore(InMemoryLeaseStore):
        async def release(self, key, owner, *, correlation_id=None):
            raise RuntimeError("backend failure")

    client = LeaseClient(FailingStore())
    handle = await client.acquire("k", 100)
    assert handle is not None
    with pytest.raises(ValueError, match="body failure"):
        async with handle:
            raise ValueError("body failure")


@pytest.mark.asyncio
async def test_context_cleanup_is_bounded_and_drains_release_task() -> None:
    class BlockingReleaseStore(InMemoryLeaseStore):
        async def release(self, key, owner, *, correlation_id=None):
            await asyncio.Event().wait()

    client = LeaseClient(BlockingReleaseStore(), cleanup_timeout=0.01)
    handle = await client.acquire("k", 100)
    assert handle is not None

    with pytest.raises(LeaseError) as caught:
        async with handle:
            pass
    assert caught.value.code.value == "timeout"
    assert not [
        task
        for task in asyncio.all_tasks()
        if task.get_name() == "rick-lock-release" and not task.done()
    ]


@pytest.mark.asyncio
async def test_handle_from_another_client_cannot_be_passed_to_client() -> None:
    store = InMemoryLeaseStore()
    first_client = InMemoryLeaseClient(store=store)
    second_client = InMemoryLeaseClient(store=store)
    handle = await first_client.acquire("k", 100)
    assert handle is not None

    with pytest.raises(LeaseError) as caught:
        await second_client.release(handle)
    assert caught.value.code.value == "invalid_request"
    assert await handle.release() is True
