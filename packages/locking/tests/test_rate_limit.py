"""Focused tests for atomic Redis and explicit local rate limiters."""

from __future__ import annotations

import pytest

from rick_locking import (
    InMemoryRateLimiter,
    RedisCircuitBreaker,
    RedisNamespace,
    RedisRateLimiter,
    RedisRetryPolicy,
    validate_production_capability,
    RedisConfigurationError,
)
from rick_locking.rate_limit import RATE_LIMIT_SCRIPT


class FakeRateRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.decisions: dict[str, int] = {}
        self.eval_calls: list[tuple[str, int, tuple[object, ...]]] = []
        self.closed = False

    async def eval(self, script: str, numkeys: int, *args: object) -> int:
        self.eval_calls.append((script, numkeys, args))
        assert script == RATE_LIMIT_SCRIPT
        assert numkeys == 2
        bucket, request, _window_ms, limit = args[:4]
        bucket_key = str(bucket)
        request_key = str(request)
        if request_key in self.decisions:
            return self.decisions[request_key]
        count = self.counts.get(bucket_key, 0) + 1
        self.counts[bucket_key] = count
        decision = 1 if count <= int(limit) else 0
        self.decisions[request_key] = decision
        return decision

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.closed = True


def _limiter(redis: FakeRateRedis, tenant: str) -> RedisRateLimiter:
    return RedisRateLimiter(
        redis,
        namespace=RedisNamespace.for_tenant(tenant),
        timeout=0.2,
        retry_policy=RedisRetryPolicy.single_attempt(),
        circuit_breaker=RedisCircuitBreaker(failure_threshold=2, cooldown_seconds=1.0),
    )


@pytest.mark.asyncio
async def test_atomic_bucket_and_request_replay_are_tenant_isolated() -> None:
    redis = FakeRateRedis()
    first = _limiter(redis, "tenant-a")
    second = _limiter(redis, "tenant-b")

    assert await first.allow("chat", limit=2, window_seconds=60, request_id="a-1") is True
    assert await first.allow("chat", limit=2, window_seconds=60, request_id="a-2") is True
    assert await first.allow("chat", limit=2, window_seconds=60, request_id="a-3") is False
    # A retry with the same request ID reads the decision marker and does not
    # increment the bucket again.
    assert await first.allow("chat", limit=2, window_seconds=60, request_id="a-3") is False
    assert await second.allow("chat", limit=1, window_seconds=60, request_id="b-1") is True

    bucket_keys = [call[2][0] for call in redis.eval_calls]
    assert bucket_keys[0] != bucket_keys[-1]
    assert all("tenant-a" not in str(key) and "tenant-b" not in str(key) for key in bucket_keys)
    assert len(redis.counts) == 2


@pytest.mark.asyncio
async def test_rate_limiter_fails_closed_and_does_not_retry_counter_mutation() -> None:
    class Failing(FakeRateRedis):
        async def eval(self, script, numkeys, *args):
            self.eval_calls.append((script, numkeys, args))
            raise ConnectionError("redis outage")

    redis = Failing()
    limiter = RedisRateLimiter(
        redis,
        namespace=RedisNamespace.for_tenant("tenant-a"),
        timeout=0.2,
        retry_policy=RedisRetryPolicy(max_attempts=5, base_delay_seconds=0, max_delay_seconds=0),
        circuit_breaker=RedisCircuitBreaker(failure_threshold=1, cooldown_seconds=1.0),
    )
    assert await limiter.allow("login", limit=3) is False
    assert await limiter.allow("login", limit=3) is False
    assert len(redis.eval_calls) == 1


@pytest.mark.asyncio
async def test_in_memory_limiter_is_explicit_local_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = InMemoryRateLimiter(mode="test", window_seconds=60)
    assert await limiter.allow("key", limit=1) is True
    assert await limiter.allow("key", limit=1) is False
    assert limiter.production_safe is False

    with pytest.raises(ValueError):
        InMemoryRateLimiter(mode="production")
    monkeypatch.setenv("RICK_ENV", "staging")
    with pytest.raises(ValueError):
        InMemoryRateLimiter()
    with pytest.raises(RedisConfigurationError):
        validate_production_capability(limiter)
