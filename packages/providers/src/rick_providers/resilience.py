"""Provider resilience policy kept outside the HTTP adapter.

The wrapper applies bounded input budgets and a small circuit breaker without
logging or retaining prompts. It is intentionally dependency-free and can wrap
either the live OpenAI-compatible client or a deterministic test double.
"""

from __future__ import annotations

import asyncio
import time
import uuid
import inspect
from collections.abc import AsyncIterator, Mapping, Sequence
from threading import RLock
from typing import Any, Callable

from rick_contracts.providers import ChatCompletionChunk, ChatCompletionResult, EmbeddingResult, ProviderMessage
from rick_providers.errors import ProviderError, provider_error
from rick_providers.protocols import AsyncProvider


class ProviderBudgetError(ValueError):
    """Raised only at the local policy boundary for an over-budget request."""


class ResilientProvider:
    """Bounded async provider facade with finite failure isolation."""

    def __init__(
        self,
        provider: AsyncProvider,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        max_messages: int = 64,
        max_prompt_chars: int = 100_000,
        max_embedding_chars: int = 1_000_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if provider is None or not callable(getattr(provider, "chat_completion", None)) or not callable(getattr(provider, "get_embedding", None)):
            raise ValueError("provider is invalid")
        if type(failure_threshold) is not int or not 1 <= failure_threshold <= 32:
            raise ValueError("failure_threshold is out of range")
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or not 0.1 <= float(cooldown_seconds) <= 86_400:
            raise ValueError("cooldown_seconds is out of range")
        for name, value, maximum in (
            ("max_messages", max_messages, 1_024),
            ("max_prompt_chars", max_prompt_chars, 1_000_000),
            ("max_embedding_chars", max_embedding_chars, 1_000_000),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} is out of range")
        if not callable(clock):
            raise ValueError("clock is invalid")
        self.provider = provider
        self.provider_kind = getattr(provider, "provider_kind", "resilient")
        self.is_test_provider = getattr(provider, "is_test_provider", False)
        self.production_safe = getattr(provider, "production_safe", self.is_test_provider is not True)
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = float(cooldown_seconds)
        self.max_messages = max_messages
        self.max_prompt_chars = max_prompt_chars
        self.max_embedding_chars = max_embedding_chars
        self._clock = clock
        self._lock = RLock()
        self._consecutive_failures = 0
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._is_open_locked()

    def readiness_check(self) -> bool:
        """Report local circuit state without performing provider I/O."""

        return not self.is_open

    def _is_open_locked(self) -> bool:
        if self._open_until <= 0:
            return False
        if float(self._clock()) >= self._open_until:
            self._open_until = 0.0
            self._consecutive_failures = 0
            return False
        return True

    def _correlation(self, requested: str | None) -> str:
        if isinstance(requested, str) and requested and len(requested) <= 128 and all(ord(char) >= 0x20 and ord(char) != 0x7F for char in requested):
            return requested
        return str(uuid.uuid4())

    def _guard(self, operation: str, correlation_id: str | None) -> str:
        correlation = self._correlation(correlation_id)
        with self._lock:
            if self._is_open_locked():
                raise provider_error("unavailable", operation, correlation, 0)
        return correlation

    def _record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._open_until = 0.0

    def _record_failure(self, error: ProviderError) -> None:
        if not error.retryable:
            return
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._open_until = float(self._clock()) + self.cooldown_seconds

    def _validate_prompt(self, model_or_messages: object, messages: object) -> None:
        candidate = messages
        if candidate is None and not isinstance(model_or_messages, str):
            candidate = model_or_messages
        if isinstance(candidate, (str, bytes)) or not isinstance(candidate, Sequence) or len(candidate) > self.max_messages:
            raise ProviderBudgetError("provider message budget exceeded")
        total = 0
        for item in candidate:
            content = item.content if isinstance(item, ProviderMessage) else item.get("content") if isinstance(item, Mapping) else None
            if not isinstance(content, str):
                continue
            total += len(content)
            if total > self.max_prompt_chars:
                raise ProviderBudgetError("provider prompt budget exceeded")

    async def chat_completion(
        self,
        model_or_messages: str | Sequence[ProviderMessage | Mapping[str, object]] | None = None,
        messages: Sequence[ProviderMessage | Mapping[str, object]] | None = None,
        temperature: int | float | None = 0.2,
        response_format: Mapping[str, object] | None = None,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> ChatCompletionResult:
        self._validate_prompt(model_or_messages, messages)
        correlation = self._guard("chat_completion", correlation_id)
        try:
            result = await self.provider.chat_completion(
                model_or_messages,
                messages,
                temperature,
                response_format,
                model=model,
                correlation_id=correlation,
            )
        except ProviderError as exc:
            self._record_failure(exc)
            raise
        else:
            self._record_success()
            return result

    async def get_embedding(
        self,
        text: str,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> EmbeddingResult:
        if not isinstance(text, str) or not text.strip() or len(text) > self.max_embedding_chars:
            raise ProviderBudgetError("provider embedding budget exceeded")
        correlation = self._guard("embeddings", correlation_id)
        try:
            result = await self.provider.get_embedding(text, model=model, correlation_id=correlation)
        except ProviderError as exc:
            self._record_failure(exc)
            raise
        else:
            self._record_success()
            return result

    def chat_completion_stream(
        self,
        model_or_messages: str | Sequence[ProviderMessage | Mapping[str, object]] | None = None,
        messages: Sequence[ProviderMessage | Mapping[str, object]] | None = None,
        temperature: int | float | None = 0.2,
        response_format: Mapping[str, object] | None = None,
        *, model: str | None = None, correlation_id: str | None = None,
    ) -> AsyncIterator[ChatCompletionChunk]:
        return self._chat_completion_stream(
            model_or_messages, messages, temperature, response_format,
            model=model, correlation_id=correlation_id,
        )

    async def _chat_completion_stream(
        self,
        model_or_messages: str | Sequence[ProviderMessage | Mapping[str, object]] | None,
        messages: Sequence[ProviderMessage | Mapping[str, object]] | None,
        temperature: int | float | None,
        response_format: Mapping[str, object] | None,
        *, model: str | None, correlation_id: str | None,
    ) -> AsyncIterator[ChatCompletionChunk]:
        self._validate_prompt(model_or_messages, messages)
        correlation = self._guard("chat_completion", correlation_id)
        target = getattr(self.provider, "chat_completion_stream", None)
        if not callable(target):
            result = await self.chat_completion(
                model_or_messages, messages, temperature, response_format,
                model=model, correlation_id=correlation,
            )
            yield ChatCompletionChunk(
                model=result.model, delta=result.content, finish_reason=result.finish_reason,
                correlation_id=result.correlation_id, usage=result.usage,
            )
            return
        try:
            stream = target(
                model_or_messages, messages, temperature, response_format,
                model=model, correlation_id=correlation,
            )
            if inspect.isawaitable(stream):
                stream = await stream
            async for chunk in stream:
                if not isinstance(chunk, ChatCompletionChunk):
                    chunk = ChatCompletionChunk.model_validate(chunk)
                yield chunk
        except asyncio.CancelledError:
            raise
        except ProviderError as exc:
            self._record_failure(exc)
            raise
        else:
            self._record_success()

    async def aclose(self) -> None:
        closer = getattr(self.provider, "aclose", None)
        if callable(closer):
            await closer()


__all__ = ["ProviderBudgetError", "ResilientProvider"]
