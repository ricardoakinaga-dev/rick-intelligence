"""Typed dependency seams for the root Professor lane.

The package deliberately does not implement a retrieval backend, LLM client,
or lock service. Those concerns are injected at this boundary and can be
replaced by deterministic test doubles.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol, TypeAlias

from rick_contracts.providers import ChatCompletionResult, ProviderMessage


RetrievalPayload: TypeAlias = object
RetrievalCallable: TypeAlias = Callable[..., object]


class ChatProvider(Protocol):
    """Typed chat-provider seam.

    Implementations should return ``ChatCompletionResult`` and must not put
    credentials, prompts, or raw provider responses in that DTO.
    """

    async def complete(
        self,
        *,
        messages: Sequence[ProviderMessage],
        conversation_id: str,
    ) -> ChatCompletionResult:
        ...


class LeaseManager(Protocol):
    """Optional low-level owner-checked lease seam."""

    async def acquire(self, *, key: str, owner: str, ttl_ms: int) -> object:
        ...

    async def renew(self, *, key: str, owner: str, ttl_ms: int) -> object:
        ...

    async def release(self, *, key: str, owner: str) -> object:
        ...


class LeasePort(Protocol):
    """Optional high-level lease seam with an owner-bound handle."""

    async def acquire(self, key: str, ttl_ms: int) -> object | None:
        ...

    async def renew(self, handle: object, ttl_ms: int | None = None) -> object:
        ...

    async def release(self, handle: object) -> object:
        ...


class RetrievalProvider(Protocol):
    """Optional object form of the retrieval callable seam.

    ``context`` is the serialized ``RetrievalContext`` mapping because the
    extracted root retrieval engine consumes mappings.
    """

    def retrieve(self, *, query: str, context: Mapping[str, object]) -> RetrievalPayload | Awaitable[RetrievalPayload]:
        ...


__all__ = ["ChatProvider", "LeaseManager", "LeasePort", "RetrievalCallable", "RetrievalProvider"]
