"""Focused tests for the Redis production boundary and resilience policy."""

from __future__ import annotations

import asyncio
from types import ModuleType
import sys

import pytest

from rick_locking import (
    LeaseError,
    InMemoryLeaseStore,
    ManualClock,
    RedisCircuitBreaker,
    RedisConfigurationError,
    RedisLeaseStore,
    RedisNamespace,
    RedisRetryPolicy,
    RedisSettings,
    RedisUnavailableError,
    create_redis_client,
    create_redis_rate_limiter,
    create_redis_lease_store,
    require_redis_ready,
    validate_production_capability,
)


class _FactoryClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.set_calls: list[tuple[object, ...]] = []
        self.closed = False

    async def set(self, name, value, *, nx, px):
        self.set_calls.append((name, value, nx, px))
        return "OK"

    async def eval(self, script, numkeys, *args):
        return 1

    async def ping(self):
        return True

    async def aclose(self):
        self.closed = True


class _FakePool:
    calls: list[tuple[str, dict[str, object]]] = []

    @classmethod
    def from_url(cls, url: str, **kwargs: object):
        cls.calls.append((url, kwargs))
        return object()


def _install_redis_module(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    class Redis(_FactoryClient):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            captured["client"] = self

    asyncio_module = ModuleType("redis.asyncio")
    asyncio_module.BlockingConnectionPool = _FakePool  # type: ignore[attr-defined]
    asyncio_module.Redis = Redis  # type: ignore[attr-defined]
    redis_module = ModuleType("redis")
    redis_module.asyncio = asyncio_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", asyncio_module)
    return captured


def _production_settings(**overrides: object) -> RedisSettings:
    values: dict[str, object] = {
        "url": "rediss://redis.example/0",
        "environment": "production",
        "password": "secret-password",
        "max_connections": 8,
        "pool_timeout": 0.2,
        "socket_connect_timeout": 0.2,
        "socket_timeout": 0.2,
        "operation_timeout": 0.5,
        "retry_max_attempts": 3,
        "retry_base_delay_seconds": 0.0,
        "retry_max_delay_seconds": 0.0,
    }
    values.update(overrides)
    return RedisSettings(**values)  # type: ignore[arg-type]


def test_production_settings_require_tls_auth_and_bound_the_pool() -> None:
    settings = _production_settings()
    assert settings.effective_require_tls is True
    assert settings.effective_require_auth is True
    assert settings.max_connections == 8
    assert settings._connection_options()["retry_on_timeout"] is False  # noqa: SLF001
    assert settings._connection_options()["ssl_cert_reqs"] is not None  # noqa: SLF001
    assert "secret-password" not in repr(settings)

    with pytest.raises(RedisConfigurationError):
        RedisSettings(url="redis://redis.example/0", password="secret-password")
    with pytest.raises(RedisConfigurationError):
        RedisSettings(url="rediss://redis.example/0")
    with pytest.raises(RedisConfigurationError):
        _production_settings(verify_tls=False)
    with pytest.raises(RedisConfigurationError):
        _production_settings(require_tls=False)
    with pytest.raises(RedisConfigurationError):
        _production_settings(require_auth=False)
    with pytest.raises(RedisConfigurationError):
        _production_settings(max_connections=257)


def test_settings_from_env_is_explicit_and_redacts_credentials() -> None:
    settings = RedisSettings.from_env(
        {
            "RICK_ENV": "production",
            "RICK_REDIS_URL": "rediss://redis.example/2",
            "RICK_REDIS_PASSWORD": "env-secret",
            "RICK_REDIS_MAX_CONNECTIONS": "12",
            "RICK_REDIS_RETRY_ATTEMPTS": "2",
            "RICK_REDIS_REQUIRE_TLS": "true",
            "RICK_REDIS_VERIFY_TLS": "true",
        }
    )
    assert settings.max_connections == 12
    assert settings.retry_max_attempts == 2
    assert "env-secret" not in repr(settings)

    with pytest.raises(RedisConfigurationError):
        RedisSettings.from_env({"RICK_ENV": "production", "RICK_REDIS_URL": "redis://localhost"})


def test_factory_uses_real_client_shape_with_bounded_tls_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_redis_module(monkeypatch)
    _FakePool.calls.clear()

    client = create_redis_client(_production_settings())

    assert isinstance(client, _FactoryClient)
    assert _FakePool.calls
    url, options = _FakePool.calls[-1]
    assert url == "rediss://redis.example/0"
    assert options["max_connections"] == 8
    assert options["timeout"] == 0.2
    assert options["socket_connect_timeout"] == 0.2
    assert options["socket_timeout"] == 0.2
    assert options["retry_on_timeout"] is False
    assert options["password"] == "secret-password"
    assert options["ssl_cert_reqs"] is not None
    assert options["ssl_check_hostname"] is True
    assert captured["client"].kwargs["decode_responses"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_factory_marks_only_real_production_composition_and_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_redis_module(monkeypatch)
    namespace = RedisNamespace.for_tenant("tenant-a", prefix="rick")
    store = create_redis_lease_store(_production_settings(), namespace)
    assert store.production_safe is True
    assert store.backend_kind == "redis"
    assert await require_redis_ready(store) is store
    handle_result = await store.acquire("work", "owner-a", 100)
    assert handle_result is True
    client = store._client  # noqa: SLF001
    assert client.set_calls[0][0] != "work"
    assert "tenant-a" not in client.set_calls[0][0]
    await store.close()
    assert client.closed is True


@pytest.mark.asyncio
async def test_managed_client_can_be_shared_without_double_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_redis_module(monkeypatch)
    settings = _production_settings()
    namespace = RedisNamespace.for_tenant("tenant-a")
    client = create_redis_client(settings)
    store = create_redis_lease_store(settings, namespace, client=client)
    limiter = create_redis_rate_limiter(settings, namespace, client=client)

    assert store.production_safe is True
    assert limiter.production_safe is True
    await store.close()
    await limiter.close()
    assert client.closed is False
    await client.aclose()
    assert client.closed is True


def test_local_managed_client_cannot_cross_the_production_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_redis_module(monkeypatch)
    local = create_redis_client(
        RedisSettings(url="redis://localhost/0", environment="local")
    )

    with pytest.raises(RedisConfigurationError):
        create_redis_lease_store(
            _production_settings(), RedisNamespace.for_tenant("tenant-a"), client=local
        )
    with pytest.raises(RedisConfigurationError):
        create_redis_rate_limiter(
            _production_settings(), RedisNamespace.for_tenant("tenant-a"), client=local
        )


@pytest.mark.asyncio
async def test_transient_lease_failures_retry_within_a_finite_budget() -> None:
    class RetryRedis(_FactoryClient):
        def __init__(self) -> None:
            super().__init__()
            self.failures = 2

        async def set(self, name, value, *, nx, px):
            self.set_calls.append((name, value, nx, px))
            if self.failures:
                self.failures -= 1
                raise ConnectionError("secret redis endpoint")
            return "OK"

    redis = RetryRedis()
    store = RedisLeaseStore(
        redis,
        timeout=0.2,
        retry_policy=RedisRetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
        ),
    )
    assert await store.acquire("lease", "owner-a", 100) is True
    assert len(redis.set_calls) == 3


@pytest.mark.asyncio
async def test_lost_acquire_response_is_reconciled_by_owner_before_replay() -> None:
    class LostResponseRedis(_FactoryClient):
        def __init__(self) -> None:
            super().__init__()
            self.value: object | None = None
            self.get_calls = 0

        async def set(self, name, value, *, nx, px):
            self.set_calls.append((name, value, nx, px))
            self.value = value
            raise TimeoutError("response lost")

        async def get(self, name):
            self.get_calls += 1
            return self.value

    redis = LostResponseRedis()
    store = RedisLeaseStore(
        redis,
        timeout=0.2,
        retry_policy=RedisRetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
        ),
    )
    assert await store.acquire("lease", "owner-a", 100) is True
    assert len(redis.set_calls) == 1
    assert redis.get_calls == 1


@pytest.mark.asyncio
async def test_circuit_opens_after_bounded_failures_and_allows_one_probe() -> None:
    class FailingRedis(_FactoryClient):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        async def set(self, name, value, *, nx, px):
            self.set_calls.append((name, value, nx, px))
            if self.fail:
                raise ConnectionError("redis failure")
            return "OK"

    clock = ManualClock()
    redis = FailingRedis()
    breaker = RedisCircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=0.1,
        clock=clock,
    )
    store = RedisLeaseStore(
        redis,
        timeout=0.2,
        retry_policy=RedisRetryPolicy.single_attempt(),
        circuit_breaker=breaker,
    )
    for _ in range(2):
        with pytest.raises(LeaseError) as caught:
            await store.acquire("lease", "owner-a", 100)
        assert caught.value.code.value == "unavailable"
    with pytest.raises(LeaseError) as caught:
        await store.acquire("lease", "owner-a", 100)
    assert caught.value.code.value == "unavailable"
    assert len(redis.set_calls) == 2

    clock.advance(0.1)
    redis.fail = False
    assert await store.acquire("lease", "owner-a", 100) is True
    assert breaker.state == "closed"


def test_stale_circuit_generations_cannot_complete_a_new_probe() -> None:
    clock = ManualClock()
    breaker = RedisCircuitBreaker(
        failure_threshold=1,
        cooldown_seconds=0.1,
        clock=clock,
    )
    stale_generation = breaker.begin_call()
    assert stale_generation is not None
    breaker.record_failure(stale_generation)
    clock.advance(0.1)
    probe_generation = breaker.begin_call()
    assert probe_generation is not None
    breaker.record_success(stale_generation)
    assert breaker.state == "half_open"
    assert breaker.begin_call() is None
    breaker.release_call(probe_generation)
    assert breaker.begin_call() is not None


@pytest.mark.asyncio
async def test_cancelled_half_open_probe_does_not_stick_the_circuit() -> None:
    started = asyncio.Event()

    class BlockingRedis(_FactoryClient):
        async def set(self, name, value, *, nx, px):
            started.set()
            await asyncio.Event().wait()
            return "OK"

    clock = ManualClock()
    breaker = RedisCircuitBreaker(
        failure_threshold=1,
        cooldown_seconds=0.1,
        clock=clock,
    )
    redis = BlockingRedis()
    store = RedisLeaseStore(
        redis,
        timeout=1.0,
        retry_policy=RedisRetryPolicy.single_attempt(),
        circuit_breaker=breaker,
    )

    # Open the circuit, then reserve its recovery probe.
    class FailingRedis(BlockingRedis):
        async def set(self, name, value, *, nx, px):
            raise ConnectionError("redis outage")

    failing_store = RedisLeaseStore(
        FailingRedis(),
        timeout=0.2,
        retry_policy=RedisRetryPolicy.single_attempt(),
        circuit_breaker=breaker,
    )
    with pytest.raises(LeaseError):
        await failing_store.acquire("lease", "owner-a", 100)
    clock.advance(0.1)

    task = asyncio.create_task(store.acquire("lease", "owner-a", 100))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert breaker.state == "half_open"
    probe_generation = breaker.begin_call()
    assert probe_generation is not None
    breaker.release_call(probe_generation)


@pytest.mark.asyncio
async def test_release_is_single_attempt_even_when_retry_policy_allows_more() -> None:
    class FailingRedis(_FactoryClient):
        def __init__(self) -> None:
            super().__init__()
            self.eval_calls = 0

        async def eval(self, script, numkeys, *args):
            self.eval_calls += 1
            raise ConnectionError("redis endpoint")

    redis = FailingRedis()
    store = RedisLeaseStore(
        redis,
        retry_policy=RedisRetryPolicy(
            max_attempts=5,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
        ),
    )
    with pytest.raises(LeaseError):
        await store.release("lease", "owner-a")
    assert redis.eval_calls == 1


@pytest.mark.asyncio
async def test_production_validation_rejects_direct_and_local_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FactoryClient()
    direct = RedisLeaseStore(redis)
    with pytest.raises(RedisConfigurationError):
        validate_production_capability(direct)

    with pytest.raises(ValueError):
        InMemoryLeaseStore(mode="production")
    local_store = InMemoryLeaseStore(mode="test")
    monkeypatch.setenv("RICK_ENV", "production")
    with pytest.raises(ValueError):
        InMemoryLeaseStore()
    with pytest.raises(RedisConfigurationError):
        validate_production_capability(local_store)

    with pytest.raises(RedisConfigurationError):
        await require_redis_ready(direct)

    with pytest.raises(RedisUnavailableError):
        # A production mark without a live readiness result cannot pass the
        # final startup gate.
        class MarkedButUnavailable:
            backend_kind = "redis"
            production_safe = True

            async def health_check(self) -> bool:
                return False

            async def readiness_check(self) -> bool:
                return False

        await require_redis_ready(MarkedButUnavailable())
