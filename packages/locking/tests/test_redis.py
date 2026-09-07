"""Deterministic tests for the optional Redis lease adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from rick_locking import (
    LeaseError,
    ManualClock,
    RedisLeaseClient,
    RedisLeaseStore,
)
from rick_locking.redis import RELEASE_SCRIPT, RENEW_SCRIPT


@dataclass(slots=True)
class _Entry:
    owner: str
    expires_at: float


class FakeRedis:
    """Small async Redis-like double with deterministic SET/EVAL semantics."""

    def __init__(self, clock: ManualClock | None = None) -> None:
        self.clock = clock or ManualClock()
        self.values: dict[str, _Entry] = {}
        self.set_calls: list[tuple[str, str, bool, int]] = []
        self.eval_calls: list[tuple[str, int, tuple[object, ...]]] = []

    def _purge(self, key: str) -> None:
        entry = self.values.get(key)
        if entry is not None and entry.expires_at <= self.clock():
            self.values.pop(key, None)

    async def set(
        self,
        key: str,
        owner: str,
        *,
        nx: bool,
        px: int,
    ) -> str | None:
        self.set_calls.append((key, owner, nx, px))
        self._purge(key)
        if nx and key in self.values:
            return None
        self.values[key] = _Entry(owner, self.clock() + px / 1000.0)
        return "OK"

    async def eval(self, script: str, numkeys: int, *args: object) -> int:
        self.eval_calls.append((script, numkeys, args))
        key = str(args[0])
        owner = str(args[1])
        self._purge(key)
        entry = self.values.get(key)
        if script == RELEASE_SCRIPT:
            if entry is None or entry.owner != owner:
                return 0
            self.values.pop(key, None)
            return 1
        if script == RENEW_SCRIPT:
            ttl_ms = int(args[2])
            if entry is None or entry.owner != owner:
                return 0
            entry.expires_at = self.clock() + ttl_ms / 1000.0
            return 1
        raise RuntimeError("unexpected script")


@pytest.mark.asyncio
async def test_wrong_owner_release_and_renew_cannot_delete_or_extend() -> None:
    clock = ManualClock()
    redis = FakeRedis(clock)
    store = RedisLeaseStore(redis)

    assert await store.acquire("lease", "owner-a", 100) is True
    original_expiry = redis.values["lease"].expires_at

    assert await store.release("lease", "owner-b") is False
    assert redis.values["lease"].owner == "owner-a"
    assert redis.values["lease"].expires_at == original_expiry

    assert await store.renew("lease", "owner-b", 10_000) is False
    assert redis.values["lease"].owner == "owner-a"
    assert redis.values["lease"].expires_at == original_expiry
    assert redis.eval_calls[0][0] == RELEASE_SCRIPT
    assert redis.eval_calls[1][0] == RENEW_SCRIPT


@pytest.mark.asyncio
async def test_expiry_allows_replacement_and_stale_owner_cannot_touch_it() -> None:
    clock = ManualClock()
    redis = FakeRedis(clock)
    store = RedisLeaseStore(redis)

    assert await store.acquire("lease", "owner-a", 100) is True
    clock.advance_ms(100)
    assert await store.renew("lease", "owner-a", 100) is False
    assert await store.acquire("lease", "owner-b", 200) is True

    assert await store.release("lease", "owner-a") is False
    assert await store.renew("lease", "owner-a", 10_000) is False
    assert redis.values["lease"].owner == "owner-b"
    assert redis.values["lease"].expires_at == 0.2 + clock.value


@pytest.mark.asyncio
async def test_matching_owner_can_renew_then_expiry_returns_false() -> None:
    clock = ManualClock()
    redis = FakeRedis(clock)
    store = RedisLeaseStore(redis)

    assert await store.acquire("lease", "owner-a", 100) is True
    clock.advance_ms(90)
    assert await store.renew("lease", "owner-a", 200) is True
    clock.advance_ms(200)
    assert await store.renew("lease", "owner-a", 200) is False


@pytest.mark.asyncio
async def test_client_uses_owner_bound_handle_without_connecting_at_import() -> None:
    redis = FakeRedis()
    client = RedisLeaseClient(redis, owner_factory=lambda: "owner-token")

    handle = await client.acquire("lease", 1_000)
    assert handle is not None
    assert handle.owner == "owner-token"
    assert await handle.release() is True
    assert redis.set_calls == [("lease", "owner-token", True, 1_000)]


@pytest.mark.asyncio
async def test_timeout_is_classified() -> None:
    class SlowRedis(FakeRedis):
        async def set(self, key, owner, *, nx, px):
            await asyncio.sleep(60)
            return await super().set(key, owner, nx=nx, px=px)

    store = RedisLeaseStore(SlowRedis(), timeout=0.01)
    with pytest.raises(LeaseError) as caught:
        await store.acquire("lease", "owner-a", 100, correlation_id="corr")
    assert caught.value.code.value == "timeout"
    assert caught.value.operation == "acquire"
    assert caught.value.correlation_id == "corr"


@pytest.mark.asyncio
async def test_cancelled_operation_propagates() -> None:
    started = asyncio.Event()

    class BlockingRedis(FakeRedis):
        async def set(self, key, owner, *, nx, px):
            started.set()
            await asyncio.Event().wait()

    store = RedisLeaseStore(BlockingRedis(), timeout=5.0)
    task = asyncio.create_task(store.acquire("lease", "owner-a", 100))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ConnectionError("redis://user:password@host/0"), "unavailable"),
        (RuntimeError("owner=owner-secret"), "internal_error"),
    ],
)
async def test_backend_errors_are_classified_and_redacted(
    error: Exception, code: str
) -> None:
    class FailingRedis(FakeRedis):
        async def set(self, key, owner, *, nx, px):
            raise error

    secret_key = "key-secret"
    secret_owner = "owner-secret"
    store = RedisLeaseStore(FailingRedis())
    with pytest.raises(LeaseError) as caught:
        await store.acquire(secret_key, secret_owner, 100, correlation_id="safe-corr")

    public_error = caught.value
    assert public_error.code.value == code
    assert secret_key not in str(public_error)
    assert secret_owner not in str(public_error)
    assert secret_key not in repr(public_error)
    assert secret_owner not in repr(public_error)
    assert secret_owner not in public_error.to_json()
    assert public_error.__cause__ is None
    assert public_error.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_key", ["", "x" * 513, "bad\nkey", None, 42])
async def test_key_validation_rejects_unbounded_or_invalid_values(bad_key: object) -> None:
    redis = FakeRedis()
    store = RedisLeaseStore(redis)

    with pytest.raises(LeaseError) as caught:
        await store.acquire(bad_key, "owner-a", 100, correlation_id="corr")  # type: ignore[arg-type]
    assert caught.value.code.value == "invalid_request"
    assert redis.set_calls == []


@pytest.mark.asyncio
async def test_invalid_ttl_and_owner_are_rejected_before_redis_call() -> None:
    redis = FakeRedis()
    store = RedisLeaseStore(redis)

    with pytest.raises(LeaseError) as ttl_error:
        await store.acquire("lease", "owner-a", 3_600_001, correlation_id="corr")
    with pytest.raises(LeaseError) as owner_error:
        await store.acquire("lease", "x" * 257, 100, correlation_id="corr")

    assert ttl_error.value.code.value == "invalid_request"
    assert owner_error.value.code.value == "invalid_request"
    assert redis.set_calls == []
