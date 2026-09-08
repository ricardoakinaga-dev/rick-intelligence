"""Focused coverage for local and injectable distributed rate limiting."""

from __future__ import annotations

import threading

import pytest

import core.rate_limit as rate_limit
from core.rate_limit import (
    DistributedRateLimiter,
    InMemoryRateLimiter,
    check_rate_limit,
)


class _Clock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _SharedWindowBackend:
    """Test-only atomic counter shared by multiple adapter instances."""

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[float, int]] = {}

    def increment(self, key: str, *, window_seconds: float) -> int:
        now = self._clock()
        with self._lock:
            started, count = self._windows.get(key, (now, 0))
            if now - started >= window_seconds:
                started, count = now, 0
            count += 1
            self._windows[key] = (started, count)
            return count


class _UnavailableBackend:
    def __init__(self) -> None:
        self.calls = 0

    def increment(self, key: str, *, window_seconds: float) -> int:
        self.calls += 1
        raise ConnectionError("redis://user:secret@example.invalid is unavailable")


def test_distributed_limiter_shares_a_window_between_instances() -> None:
    clock = _Clock()
    backend = _SharedWindowBackend(clock)
    first_instance = DistributedRateLimiter(backend, window_seconds=60)
    second_instance = DistributedRateLimiter(backend, window_seconds=60)

    assert first_instance.check("tenant-a:user-a", limit_per_min=2)
    assert check_rate_limit(second_instance, "tenant-a:user-a", limit_per_min=2)
    assert first_instance.check("tenant-a:user-a", limit_per_min=2) is False

    clock.advance(60)

    assert second_instance.check("tenant-a:user-a", limit_per_min=2)


def test_distributed_limiter_fails_closed_when_backend_is_unavailable() -> None:
    backend = _UnavailableBackend()
    limiter = DistributedRateLimiter(backend)

    assert limiter.check("tenant-a:user-a", limit_per_min=30) is False
    assert backend.calls == 1


@pytest.mark.parametrize("count", [None, 0, -1, True, "1"])
def test_distributed_limiter_rejects_invalid_backend_counts(count: object) -> None:
    class Backend:
        def increment(self, key: str, *, window_seconds: float) -> object:
            return count

    limiter = DistributedRateLimiter(Backend())

    assert limiter.check("tenant-a:user-a", limit_per_min=30) is False


def test_distributed_limiter_rejects_invalid_configuration() -> None:
    class Backend:
        def increment(self, key: str, *, window_seconds: float) -> int:
            return 1

    with pytest.raises(ValueError):
        DistributedRateLimiter(Backend(), window_seconds=0)
    with pytest.raises(ValueError):
        DistributedRateLimiter(Backend(), window_seconds=float("inf"))


def test_in_memory_limiter_remains_the_local_windowed_fallback(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(rate_limit.time, "monotonic", clock)
    limiter = InMemoryRateLimiter(window_seconds=60)

    assert limiter.check("tenant-a:user-a", limit_per_min=1)
    assert limiter.check("tenant-a:user-a", limit_per_min=1) is False

    clock.advance(60)

    assert limiter.check("tenant-a:user-a", limit_per_min=1)
