"""Deterministic, explicitly non-production provider for tests and dev."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence

from pydantic import ValidationError

from rick_contracts.providers import ChatCompletionChunk, ChatCompletionResult, EmbeddingResult

from rick_providers.client import (
    CorrelationIdFactory,
    MessageInput,
    _resolve_correlation_id,
    _serialize_messages,
    _serialize_response_format,
    _validate_model,
    _validate_temperature,
)
from rick_providers.config import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    ProviderConfig,
    ProviderConfigurationError,
)
from rick_providers.errors import ProviderError, ProviderOperation, provider_error


class DeterministicProvider:
    """Hermetic provider double; never valid for a production environment.

    The generated answer and vector are deterministic functions of their
    inputs.  They are useful for plumbing and contract tests only, not for
    semantic or live-provider quality claims.
    """

    is_test_provider = True
    non_production = True
    production_safe = False
    provider_kind = "deterministic"
    label = "deterministic-test-dev"

    def __init__(
        self,
        config: ProviderConfig | None = None,
        *,
        chat_model: str = DEFAULT_CHAT_MODEL,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
        dimensions: int | None = None,
        environment: str = "test",
        correlation_id_factory: CorrelationIdFactory | None = None,
    ) -> None:
        if config is None:
            config = ProviderConfig(
                base_url="http://deterministic.invalid",
                chat_model=chat_model,
                embedding_model=embedding_model,
                embedding_dimensions=dimensions if dimensions is not None else embedding_dimensions,
                environment=environment,
                provider_kind="deterministic",
            )
        elif dimensions is not None:
            # A caller-supplied config remains authoritative unless it asks
            # explicitly for the convenience dimensions override.
            config = ProviderConfig(
                base_url=config.base_url,
                api_key=config.api_key,
                chat_model=config.chat_model,
                embedding_model=config.embedding_model,
                embedding_dimensions=dimensions,
                timeout=config.timeout,
                max_attempts=config.max_attempts,
                retry_base_delay=config.retry_base_delay,
                max_backoff_delay=config.max_backoff_delay,
                environment=config.environment,
                provider_kind="deterministic",
            )
        try:
            config.validate()
        except ProviderConfigurationError:
            raise
        if not config.is_test_or_dev:
            raise ProviderConfigurationError()
        self.config = config
        self._correlation_id_factory = correlation_id_factory or (lambda: str(uuid.uuid4()))

    async def __aenter__(self) -> "DeterministicProvider":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def chat_completion(
        self,
        model_or_messages: str | Sequence[MessageInput] | None = None,
        messages: Sequence[MessageInput] | None = None,
        temperature: int | float | None = 0.2,
        response_format: Mapping[str, object] | None = None,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> ChatCompletionResult:
        operation: ProviderOperation = "chat_completion"
        correlation = self._prepare(operation, correlation_id)
        if model is not None:
            if model_or_messages is not None:
                if messages is None and not isinstance(model_or_messages, str):
                    messages = model_or_messages
                else:
                    raise provider_error("invalid_model", operation, correlation, 0)
            selected_model: object = model
        elif messages is None and model_or_messages is not None and not isinstance(model_or_messages, str):
            messages = model_or_messages
            selected_model = None
        else:
            selected_model = model_or_messages
        normalized_model = _validate_model(
            self.config.chat_model if selected_model is None else selected_model,
            operation,
            correlation,
        )
        serialized_messages = _serialize_messages(messages, operation, correlation)
        normalized_temperature = _validate_temperature(temperature, operation, correlation)
        normalized_format = _serialize_response_format(response_format, operation, correlation)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "messages": serialized_messages,
                    "temperature": normalized_temperature,
                    "response_format": normalized_format,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        evidence_ids = re.findall(r"\bSOURCE\s+([A-Za-z0-9][A-Za-z0-9_.:-]{0,127})\b", serialized_messages[0]["content"] if serialized_messages else "")
        citation = f" [cite:{evidence_ids[0]}]" if evidence_ids else ""
        try:
            return ChatCompletionResult(
                model=normalized_model,
                content=f"Deterministic provider response ({fingerprint}).{citation}",
                finish_reason="stop",
                correlation_id=correlation,
                usage=None,
            )
        except ValidationError:
            # Constants above make this unreachable, but keep the public
            # failure safe if the shared DTO changes.
            raise provider_error("malformed_response", operation, correlation, 1) from None

    async def get_embedding(
        self,
        text: str,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> EmbeddingResult:
        operation: ProviderOperation = "embeddings"
        correlation = self._prepare(operation, correlation_id)
        normalized_model = _validate_model(
            self.config.embedding_model if model is None else model,
            operation,
            correlation,
        )
        if not isinstance(text, str) or not text.strip() or len(text) > 1_000_000:
            raise provider_error("malformed_response", operation, correlation, 0)
        seed = hashlib.sha256(f"{normalized_model}\0{text}".encode("utf-8")).digest()
        vector = [
            (seed[index % len(seed)] / 255.0) * 2.0 - 1.0
            for index in range(self.config.embedding_dimensions)
        ]
        try:
            return EmbeddingResult(
                model=normalized_model,
                dimensions=self.config.embedding_dimensions,
                vector=vector,
                correlation_id=correlation,
            )
        except ValidationError:
            raise provider_error("malformed_response", operation, correlation, 1) from None

    def chat_completion_stream(
        self,
        model_or_messages: str | Sequence[MessageInput] | None = None,
        messages: Sequence[MessageInput] | None = None,
        temperature: int | float | None = 0.2,
        response_format: Mapping[str, object] | None = None,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> AsyncIterator[ChatCompletionChunk]:
        async def stream() -> AsyncIterator[ChatCompletionChunk]:
            result = await self.chat_completion(
                model_or_messages, messages, temperature, response_format,
                model=model, correlation_id=correlation_id,
            )
            # This is a deterministic test transport. It still emits through
            # the same async delta contract as the network provider, allowing
            # cancellation and ordering tests without a paid API call.
            for index in range(0, len(result.content), 48):
                await asyncio.sleep(0)
                yield ChatCompletionChunk(
                    model=result.model, delta=result.content[index:index + 48],
                    correlation_id=result.correlation_id,
                )
            yield ChatCompletionChunk(
                model=result.model, delta="", finish_reason=result.finish_reason,
                correlation_id=result.correlation_id, usage=result.usage,
            )
        return stream()

    async def embeddings(
        self,
        text: str | None = None,
        *,
        input: str | None = None,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> EmbeddingResult:
        if text is not None and input is not None:
            correlation = self._prepare("embeddings", correlation_id)
            raise provider_error("malformed_response", "embeddings", correlation, 0)
        value = text if text is not None else input
        return await self.get_embedding(value, model=model, correlation_id=correlation)  # type: ignore[arg-type]

    async def embed(
        self,
        text: str,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> EmbeddingResult:
        return await self.get_embedding(text, model=model, correlation_id=correlation_id)

    async def embedding(
        self,
        text: str,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> EmbeddingResult:
        return await self.get_embedding(text, model=model, correlation_id=correlation_id)

    async def chat(
        self,
        messages: Sequence[MessageInput],
        *,
        model: str | None = None,
        temperature: int | float | None = 0.2,
        response_format: Mapping[str, object] | None = None,
        correlation_id: str | None = None,
    ) -> ChatCompletionResult:
        return await self.chat_completion(
            model,
            messages,
            temperature,
            response_format,
            correlation_id=correlation_id,
        )

    async def embed_batch(
        self,
        texts: Sequence[str],
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> list[EmbeddingResult]:
        """Deterministically embed a batch under one caller-supplied ID."""

        if not isinstance(texts, Sequence) or isinstance(texts, (str, bytes)):
            correlation = self._prepare("embeddings", correlation_id)
            raise provider_error("malformed_response", "embeddings", correlation, 0)
        correlation = self._prepare("embeddings", correlation_id)
        return [
            await self.get_embedding(text, model=model, correlation_id=correlation)
            for text in texts
        ]

    def _prepare(self, operation: ProviderOperation, requested: str | None) -> str:
        correlation, valid = _resolve_correlation_id(requested, self._correlation_id_factory)
        if not valid:
            raise provider_error("invalid_configuration", operation, correlation, 0)
        if not self.config.is_test_or_dev:
            raise provider_error("invalid_configuration", operation, correlation, 0)
        return correlation


DeterministicDevProvider = DeterministicProvider
DeterministicTestProvider = DeterministicProvider


__all__ = [
    "DeterministicDevProvider",
    "DeterministicProvider",
    "DeterministicTestProvider",
]
