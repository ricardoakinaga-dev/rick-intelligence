"""Dependency-injection protocols for provider consumers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Protocol

from rick_contracts.providers import ChatCompletionChunk, ChatCompletionResult, EmbeddingResult, ProviderMessage


class AsyncProvider(Protocol):
    """The one async provider boundary used by root orchestration."""

    async def chat_completion(
        self,
        model_or_messages: str | Sequence[ProviderMessage | Mapping[str, object]] | None = None,
        messages: Sequence[ProviderMessage | Mapping[str, object]] | None = None,
        temperature: int | float | None = 0.2,
        response_format: Mapping[str, object] | None = None,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> ChatCompletionResult: ...

    async def get_embedding(
        self,
        text: str,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> EmbeddingResult: ...

    def chat_completion_stream(
        self,
        model_or_messages: str | Sequence[ProviderMessage | Mapping[str, object]] | None = None,
        messages: Sequence[ProviderMessage | Mapping[str, object]] | None = None,
        temperature: int | float | None = 0.2,
        response_format: Mapping[str, object] | None = None,
        *, model: str | None = None, correlation_id: str | None = None,
    ) -> AsyncIterator[ChatCompletionChunk]: ...


Provider = AsyncProvider


__all__ = ["AsyncProvider", "Provider"]
