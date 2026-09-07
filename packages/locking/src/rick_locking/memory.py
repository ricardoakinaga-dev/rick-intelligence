"""Deterministic race-safe in-memory lease backend."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from rick_locking.client import LeaseClient, OwnerFactory
from rick_locking.errors import LeaseError, LeaseOperation
from rick_locking.validation import (
    correlation_id_for,
    validate_key,
    validate_owner,
    validate_ttl,
)

Clock = Callable[[], float]


@dataclass(slots=True)
class _Entry:
    owner: str
    expires_at: float


class ManualClock:
    """A monotonic clock useful for deterministic expiry tests."""

    def __init__(self, initial: float = 0.0) -> None:
        if not isinstance(initial, (int, float)) or initial < 0:
            raise ValueError("invalid clock value")
        self._value = float(initial)
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._value

    @property
    def value(self) -> float:
        return self()

    def advance(self, seconds: float) -> float:
        if not isinstance(seconds, (int, float)) or seconds < 0:
            raise ValueError("invalid clock increment")
        with self._lock:
            self._value += float(seconds)
            return self._value

    def advance_ms(self, milliseconds: int) -> float:
        if isinstance(milliseconds, bool) or not isinstance(milliseconds, int) or milliseconds < 0:
            raise ValueError("invalid clock increment")
        return self.advance(milliseconds / 1000.0)


class InMemoryLeaseStore:
    """Atomic owner-safe backend with monotonic expiry.

    The critical sections contain no await points and use a thread lock, so
    concurrent tasks and callers from different threads cannot win the same
    key or delete a replacement owner's lease.
    """

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or time.monotonic
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.RLock()

    def _now(self, operation: LeaseOperation, correlation_id: str) -> float:
        failure = False
        value = 0.0
        try:
            value = float(self._clock())
            if value != value or value in {float("inf"), float("-inf")}:
                failure = True
        except Exception:
            failure = True
        if failure:
            raise LeaseError("internal_error", operation, correlation_id)
        return value

    def _validate(
        self,
        operation: LeaseOperation,
        key: str,
        owner: str,
        ttl_ms: int | None,
        correlation_id: str | None,
    ) -> tuple[str, str, int | None, str]:
        corr = correlation_id_for(operation, correlation_id)
        checked_key = validate_key(key, operation, corr)
        checked_owner = validate_owner(owner, operation, corr)
        checked_ttl = (
            None if ttl_ms is None else validate_ttl(ttl_ms, operation, corr)
        )
        return checked_key, checked_owner, checked_ttl, corr

    def _expired(self, entry: _Entry, now: float) -> bool:
        return entry.expires_at <= now

    async def acquire(
        self,
        key: str,
        owner: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        checked_key, checked_owner, checked_ttl, corr = self._validate(
            "acquire", key, owner, ttl_ms, correlation_id
        )
        assert checked_ttl is not None
        with self._lock:
            now = self._now("acquire", corr)
            current = self._entries.get(checked_key)
            if current is not None and not self._expired(current, now):
                return False
            if current is not None:
                self._entries.pop(checked_key, None)
            self._entries[checked_key] = _Entry(
                owner=checked_owner,
                expires_at=now + checked_ttl / 1000.0,
            )
            return True

    async def renew(
        self,
        key: str,
        owner: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        checked_key, checked_owner, checked_ttl, corr = self._validate(
            "renew", key, owner, ttl_ms, correlation_id
        )
        assert checked_ttl is not None
        with self._lock:
            now = self._now("renew", corr)
            current = self._entries.get(checked_key)
            if current is None:
                return False
            if self._expired(current, now):
                self._entries.pop(checked_key, None)
                return False
            if current.owner != checked_owner:
                return False
            current.expires_at = now + checked_ttl / 1000.0
            return True

    async def release(
        self,
        key: str,
        owner: str,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        checked_key, checked_owner, _, corr = self._validate(
            "release", key, owner, None, correlation_id
        )
        with self._lock:
            now = self._now("release", corr)
            current = self._entries.get(checked_key)
            if current is None:
                return False
            if self._expired(current, now):
                self._entries.pop(checked_key, None)
                return False
            if current.owner != checked_owner:
                return False
            self._entries.pop(checked_key, None)
            return True

    def is_active(self, key: str) -> bool:
        """Return whether a key has a non-expired lease, without its owner."""

        corr = correlation_id_for("acquire", None)
        checked_key = validate_key(key, "acquire", corr)
        with self._lock:
            now = self._now("acquire", corr)
            current = self._entries.get(checked_key)
            if current is None:
                return False
            if self._expired(current, now):
                self._entries.pop(checked_key, None)
                return False
            return True

    def remaining_ttl_ms(self, key: str) -> int | None:
        """Return bounded remaining TTL for diagnostics, never the owner."""

        corr = correlation_id_for("acquire", None)
        checked_key = validate_key(key, "acquire", corr)
        with self._lock:
            now = self._now("acquire", corr)
            current = self._entries.get(checked_key)
            if current is None or self._expired(current, now):
                if current is not None:
                    self._entries.pop(checked_key, None)
                return None
            return max(0, int((current.expires_at - now) * 1000))

    def __len__(self) -> int:
        # Purge expired entries without exposing their values.
        with self._lock:
            now = self._now("acquire", correlation_id_for("acquire", None))
            for key, entry in tuple(self._entries.items()):
                if self._expired(entry, now):
                    self._entries.pop(key, None)
            return len(self._entries)


class InMemoryLeaseClient(LeaseClient):
    """High-level owner-generating client backed by :class:`InMemoryLeaseStore`."""

    def __init__(
        self,
        store: InMemoryLeaseStore | None = None,
        *,
        clock: Clock | None = None,
        owner_factory: OwnerFactory | None = None,
        cleanup_timeout: float = 2.0,
    ) -> None:
        actual_store = store if store is not None else InMemoryLeaseStore(clock=clock)
        kwargs: dict[str, object] = {"cleanup_timeout": cleanup_timeout}
        if owner_factory is not None:
            kwargs["owner_factory"] = owner_factory
        super().__init__(actual_store, **kwargs)
        self.store = actual_store


InMemoryClient = InMemoryLeaseClient


__all__ = ["InMemoryClient", "InMemoryLeaseClient", "InMemoryLeaseStore", "ManualClock"]
