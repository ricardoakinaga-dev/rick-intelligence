"""Async protocols for lease implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rick_locking.client import LeaseHandle


@runtime_checkable
class LeaseBackend(Protocol):
    """Atomic owner-aware storage operations.

    A backend returns ``False`` for contention, expiry, or an owner mismatch;
    it raises :class:`LeaseError` only for typed operational failures.
    """

    async def acquire(
        self,
        key: str,
        owner: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> bool: ...

    async def renew(
        self,
        key: str,
        owner: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> bool: ...

    async def release(
        self,
        key: str,
        owner: str,
        *,
        correlation_id: str | None = None,
    ) -> bool: ...


@runtime_checkable
class LeasePort(Protocol):
    """High-level lease port that creates owner-bound handles."""

    async def acquire(
        self,
        key: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> LeaseHandle | None: ...

    async def renew(
        self,
        handle: LeaseHandle,
        ttl_ms: int | None = None,
        *,
        correlation_id: str | None = None,
    ) -> bool: ...

    async def release(
        self,
        handle: LeaseHandle,
        *,
        correlation_id: str | None = None,
    ) -> bool: ...


# A store is the same low-level protocol under a name that reads naturally in
# dependency injection declarations.
LeaseStore = LeaseBackend


__all__ = ["LeaseBackend", "LeasePort", "LeaseStore"]
