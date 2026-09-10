"""Async OpenAI-compatible provider boundary.

Only this module knows about HTTP. Chat and embedding calls share the same
request, classification, retry, timeout, and correlation path, while the
health probe uses the same bounded client and redaction boundary so readiness
cannot be inferred from object construction.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any

import httpx
from pydantic import ValidationError

from rick_contracts.providers import (
    ChatCompletionChunk,
    ChatCompletionResult,
    EmbeddingResult,
    ProviderMessage,
)

from rick_providers.config import ProviderConfig, ProviderConfigurationError
from rick_providers.config import (
    DEFAULT_BASE_URL,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
)
from rick_providers.errors import (
    ProviderError,
    ProviderOperation,
    provider_error,
)


MAX_RESPONSE_BYTES = 1_000_000
_ALLOWED_FINISH_REASONS = frozenset({"stop", "length", "content_filter", "unknown"})
_CORRELATION_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

SleepFunction = Callable[[float], Awaitable[object] | object]
CorrelationIdFactory = Callable[[], str]
MessageInput = ProviderMessage | Mapping[str, object]


class OpenAICompatibleClient:
    """Typed async client for chat, embedding, and provider health requests.

    The client is lazy: constructing it does not perform I/O.  ``transport``
    can be an ``httpx.AsyncBaseTransport`` (for example ``MockTransport``) and
    ``sleep`` can be an async or synchronous test hook.  A supplied
    ``httpx.AsyncClient`` is treated as caller-owned and is never closed by
    this object.
    """

    is_test_provider = False
    provider_kind = "openai_compatible"

    def __init__(
        self,
        config: ProviderConfig | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        chat_model: str | None = None,
        embedding_model: str | None = None,
        embedding_dimensions: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        timeout_seconds: float | httpx.Timeout | None = None,
        timeout_ms: float | None = None,
        max_attempts: int | None = None,
        retry_base_delay: float | None = None,
        retry_delay_seconds: float | None = None,
        retry_delay: float | None = None,
        max_backoff_delay: float | None = None,
        environment: str | None = None,
        provider_kind: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFunction | None = None,
        sleep_fn: SleepFunction | None = None,
        client: httpx.AsyncClient | None = None,
        http_client: httpx.AsyncClient | None = None,
        correlation_id_factory: CorrelationIdFactory | None = None,
    ) -> None:
        configured_fields = {
            "base_url": base_url,
            "api_key": api_key,
            "chat_model": chat_model,
            "embedding_model": embedding_model,
            "embedding_dimensions": embedding_dimensions,
            "timeout": timeout,
            "timeout_seconds": timeout_seconds,
            "timeout_ms": timeout_ms,
            "max_attempts": max_attempts,
            "retry_base_delay": retry_base_delay,
            "retry_delay_seconds": retry_delay_seconds,
            "retry_delay": retry_delay,
            "max_backoff_delay": max_backoff_delay,
            "environment": environment,
            "provider_kind": provider_kind,
        }
        if config is None:
            self.config = ProviderConfig(
                base_url=base_url if base_url is not None else DEFAULT_BASE_URL,
                api_key=api_key,
                chat_model=chat_model if chat_model is not None else DEFAULT_CHAT_MODEL,
                embedding_model=embedding_model if embedding_model is not None else DEFAULT_EMBEDDING_MODEL,
                embedding_dimensions=(
                    embedding_dimensions if embedding_dimensions is not None else DEFAULT_EMBEDDING_DIMENSIONS
                ),
                timeout=timeout if timeout is not None else DEFAULT_TIMEOUT_SECONDS,
                timeout_seconds=timeout_seconds,
                timeout_ms=timeout_ms,
                max_attempts=max_attempts if max_attempts is not None else 3,
                retry_base_delay=retry_base_delay if retry_base_delay is not None else 0.25,
                retry_delay_seconds=retry_delay_seconds,
                retry_delay=retry_delay,
                max_backoff_delay=max_backoff_delay if max_backoff_delay is not None else 30.0,
                environment=environment if environment is not None else "production",
                provider_kind=provider_kind if provider_kind is not None else "openai",
            )
        elif any(value is not None for value in configured_fields.values()):
            self.config = ProviderConfig(
                base_url=config.base_url if base_url is None else base_url,
                api_key=config.api_key if api_key is None else api_key,
                chat_model=config.chat_model if chat_model is None else chat_model,
                embedding_model=config.embedding_model if embedding_model is None else embedding_model,
                embedding_dimensions=(
                    config.embedding_dimensions if embedding_dimensions is None else embedding_dimensions
                ),
                timeout=config.timeout if timeout is None else timeout,
                timeout_seconds=timeout_seconds,
                timeout_ms=timeout_ms,
                max_attempts=config.max_attempts if max_attempts is None else max_attempts,
                retry_base_delay=config.retry_base_delay if retry_base_delay is None else retry_base_delay,
                retry_delay_seconds=retry_delay_seconds,
                retry_delay=retry_delay,
                max_backoff_delay=config.max_backoff_delay if max_backoff_delay is None else max_backoff_delay,
                environment=config.environment if environment is None else environment,
                provider_kind=config.provider_kind if provider_kind is None else provider_kind,
            )
        else:
            self.config = config
        self._transport = transport
        self._sleep: SleepFunction = sleep or sleep_fn or asyncio.sleep
        self._client = client or http_client
        self._owns_client = self._client is None
        self._correlation_id_factory = correlation_id_factory or (lambda: str(uuid.uuid4()))

    async def __aenter__(self) -> "OpenAICompatibleClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> bool:
        """Perform one bounded, authenticated provider reachability probe.

        Readiness must not be inferred from construction or from a local
        circuit state.  The models endpoint is part of the OpenAI-compatible
        surface and verifies that the configured endpoint and credential can
        answer without sending a paid chat or embedding request.
        """

        operation: ProviderOperation = "chat_completion"
        try:
            correlation = self._prepare_operation(operation, None)
            model = _validate_model(self.config.chat_model, operation, correlation)
            return await asyncio.wait_for(
                self._health_request(correlation, model),
                timeout=_request_timeout_seconds(self.config.timeout),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # A readiness probe is a boolean port.  The public health route
            # must not expose provider URLs, response bodies, or exception
            # details when the probe fails.
            return False

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
        """Request one chat completion and return the shared result DTO.

        ``model`` is optional and defaults to ``config.chat_model``.  For
        ergonomic use, ``chat_completion(messages=[...])`` and
        ``chat_completion([...])`` are both accepted.
        """

        operation: ProviderOperation = "chat_completion"
        correlation = self._prepare_operation(operation, correlation_id)
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
        payload: dict[str, object] = {
            "model": normalized_model,
            "messages": serialized_messages,
            "temperature": normalized_temperature,
            "response_format": normalized_format,
        }

        async def attempt_request(attempt: int) -> ChatCompletionResult:
            body = await self._post_json(
                operation,
                "/chat/completions",
                payload,
                correlation,
                attempt,
            )
            return _extract_chat_result(body, normalized_model, correlation, attempt)

        return await self._with_retry(operation, correlation, attempt_request)

    async def get_embedding(
        self,
        text: str,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> EmbeddingResult:
        """Request one embedding and return a finite, dimension-checked DTO."""

        operation: ProviderOperation = "embeddings"
        correlation = self._prepare_operation(operation, correlation_id)
        normalized_model = _validate_model(
            self.config.embedding_model if model is None else model,
            operation,
            correlation,
        )
        if not isinstance(text, str) or not text.strip() or len(text) > 1_000_000:
            raise provider_error("malformed_response", operation, correlation, 0)
        payload: dict[str, object] = {"model": normalized_model, "input": text}

        async def attempt_request(attempt: int) -> EmbeddingResult:
            body = await self._post_json(
                operation,
                "/embeddings",
                payload,
                correlation,
                attempt,
            )
            return _extract_embedding_result(
                body,
                normalized_model,
                correlation,
                attempt,
                self.config.embedding_dimensions,
            )

        return await self._with_retry(operation, correlation, attempt_request)

    async def embeddings(
        self,
        text: str | None = None,
        *,
        input: str | None = None,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> EmbeddingResult:
        """Endpoint-named alias for :meth:`get_embedding`."""

        if text is not None and input is not None:
            # The raw values are intentionally not included in the error.
            correlation = self._prepare_operation("embeddings", correlation_id)
            raise provider_error("malformed_response", "embeddings", correlation, 0)
        value = text if text is not None else input
        return await self.get_embedding(value, model=model, correlation_id=correlation_id)  # type: ignore[arg-type]

    async def embed(
        self,
        text: str,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> EmbeddingResult:
        """Short alias used by provider consumers."""

        return await self.get_embedding(text, model=model, correlation_id=correlation_id)

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
        """Return an iterator over provider SSE deltas.

        The HTTP response remains open only while the caller consumes the
        iterator. Cancellation closes it through ``httpx``'s async context
        manager. Retries are allowed before the first delta; after output has
        escaped, the stream fails closed instead of duplicating a prefix.
        """
        return self._chat_completion_stream(
            model_or_messages, messages, temperature, response_format,
            model=model, correlation_id=correlation_id,
        )

    async def _chat_completion_stream(
        self,
        model_or_messages: str | Sequence[MessageInput] | None,
        messages: Sequence[MessageInput] | None,
        temperature: int | float | None,
        response_format: Mapping[str, object] | None,
        *,
        model: str | None,
        correlation_id: str | None,
    ) -> AsyncIterator[ChatCompletionChunk]:
        operation: ProviderOperation = "chat_completion"
        correlation = self._prepare_operation(operation, correlation_id)
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
            operation, correlation,
        )
        serialized_messages = _serialize_messages(messages, operation, correlation)
        normalized_temperature = _validate_temperature(temperature, operation, correlation)
        normalized_format = _serialize_response_format(response_format, operation, correlation)
        payload: dict[str, object] = {
            "model": normalized_model, "messages": serialized_messages,
            "temperature": normalized_temperature, "response_format": normalized_format,
            "stream": True,
        }

        for attempt in range(1, self.config.max_attempts + 1):
            emitted = False
            try:
                url = f"{self.config.base_url.rstrip('/')}/chat/completions"
                headers = {
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                    "X-Correlation-ID": correlation,
                }
                if self.config.api_key:
                    headers["Authorization"] = f"Bearer {self.config.api_key}"
                async with self._ensure_client().stream(
                    "POST", url, headers=headers, json=payload,
                ) as response:
                    status = response.status_code
                    if not 200 <= status <= 299:
                        raw = await _read_bounded_response(response)
                        raise _classify_http_status(status, raw or b"", operation, correlation, attempt)
                    total_bytes = 0
                    saw_done = False
                    async for line in response.aiter_lines():
                        total_bytes += len(line.encode("utf-8", errors="replace")) + 1
                        if total_bytes > MAX_RESPONSE_BYTES:
                            raise provider_error("malformed_response", operation, correlation, attempt)
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            saw_done = True
                            break
                        try:
                            decoded = json.loads(data, parse_constant=_reject_json_constant)
                        except (TypeError, ValueError, RecursionError):
                            raise provider_error("invalid_json", operation, correlation, attempt) from None
                        chunk = _extract_chat_chunk(decoded, normalized_model, correlation, attempt)
                        if chunk is None:
                            continue
                        if chunk.delta:
                            emitted = True
                        yield chunk
                    if not saw_done:
                        raise provider_error("malformed_response", operation, correlation, attempt)
                    return
            except asyncio.CancelledError:
                raise
            except ProviderError as exc:
                safe_error = ProviderError(
                    exc.code, operation, correlation, attempt, exc.retryable, exc.status,
                )
            except httpx.InvalidURL:
                safe_error = provider_error("invalid_configuration", operation, correlation, attempt)
            except Exception as exc:
                safe_error = _classify_transport_error(exc, operation, correlation, attempt)
            if emitted or not safe_error.retryable or attempt >= self.config.max_attempts:
                raise safe_error from None
            delay = min(self.config.max_backoff_delay, self.config.retry_base_delay * (2 ** (attempt - 1)))
            try:
                result = self._sleep(delay)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                raise provider_error("internal_error", operation, correlation, attempt) from None

        raise provider_error("internal_error", operation, correlation, self.config.max_attempts)

    async def embedding(
        self,
        text: str,
        *,
        model: str | None = None,
        correlation_id: str | None = None,
    ) -> EmbeddingResult:
        """Compatibility alias for singular embedding call sites."""

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
        """Short alias with messages-first argument order."""

        return await self.chat_completion(
            model,
            messages,
            temperature,
            response_format,
            correlation_id=correlation_id,
        )

    async def _post_json(
        self,
        operation: ProviderOperation,
        endpoint: str,
        payload: Mapping[str, object],
        correlation_id: str,
        attempt: int,
    ) -> object:
        url = f"{self.config.base_url.rstrip('/')}{endpoint}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Correlation-ID": correlation_id,
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        try:
            http_client = self._ensure_client()
            async with http_client.stream(
                "POST",
                url,
                headers=headers,
                json=dict(payload),
            ) as response:
                status = response.status_code
                raw = await _read_bounded_response(response)
        except asyncio.CancelledError:
            raise
        except httpx.InvalidURL:
            raise provider_error("invalid_configuration", operation, correlation_id, attempt) from None
        except Exception as exc:
            raise _classify_transport_error(exc, operation, correlation_id, attempt) from None

        if raw is None:
            if not 200 <= status <= 299:
                raise _classify_http_status(status, b"", operation, correlation_id, attempt) from None
            raise provider_error("malformed_response", operation, correlation_id, attempt, status=status) from None
        if not 200 <= status <= 299:
            raise _classify_http_status(status, raw, operation, correlation_id, attempt) from None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise provider_error("invalid_json", operation, correlation_id, attempt, status=status) from None
        try:
            return json.loads(text, parse_constant=_reject_json_constant)
        except (TypeError, ValueError, RecursionError):
            raise provider_error("invalid_json", operation, correlation_id, attempt, status=status) from None

    async def _health_request(self, correlation_id: str, model: str) -> bool:
        url = f"{self.config.base_url.rstrip('/')}/models"
        headers = {
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        async with self._ensure_client().stream(
            "GET",
            url,
            headers=headers,
        ) as response:
            status = response.status_code
            raw = await _read_bounded_response(response)
        if not 200 <= status <= 299 or raw is None:
            return False
        try:
            body = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
        except (UnicodeDecodeError, TypeError, ValueError, RecursionError):
            return False
        return _health_payload_is_valid(body, model)

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout,
                transport=self._transport,
                follow_redirects=False,
            )
        return self._client

    async def _with_retry(
        self,
        operation: ProviderOperation,
        correlation_id: str,
        action: Callable[[int], Awaitable[Any]],
    ) -> Any:
        max_attempts = self.config.max_attempts
        for attempt in range(1, max_attempts + 1):
            try:
                return await action(attempt)
            except asyncio.CancelledError:
                # Cancellation is control flow, never a provider failure.
                raise
            except ProviderError as exc:
                safe_error = ProviderError(
                    exc.code,
                    operation,
                    correlation_id,
                    attempt,
                    exc.retryable,
                    exc.status,
                )
            except Exception:
                safe_error = provider_error("internal_error", operation, correlation_id, attempt)

            if not safe_error.retryable or attempt >= max_attempts:
                raise safe_error from None
            delay = min(
                self.config.max_backoff_delay,
                self.config.retry_base_delay * (2 ** (attempt - 1)),
            )
            try:
                result = self._sleep(delay)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                raise provider_error("internal_error", operation, correlation_id, attempt) from None

        # The range is non-empty after configuration validation; this is a
        # defensive safe failure if a mutable test double changes settings.
        raise provider_error("internal_error", operation, correlation_id, max_attempts)

    def _prepare_operation(
        self,
        operation: ProviderOperation,
        requested_correlation_id: str | None,
    ) -> str:
        correlation_id, valid = _resolve_correlation_id(
            requested_correlation_id,
            self._correlation_id_factory,
        )
        if not valid:
            raise provider_error("invalid_configuration", operation, correlation_id, 0)
        try:
            self.config.validate()
        except ProviderConfigurationError:
            raise provider_error("invalid_configuration", operation, correlation_id, 0) from None
        if self.config.provider_kind == "deterministic":
            # Selecting that implementation belongs to create_provider; this
            # class must never silently turn into a test double.
            raise provider_error("invalid_configuration", operation, correlation_id, 0)
        return correlation_id


async def _read_bounded_response(response: httpx.Response) -> bytes | None:
    """Read at most ``MAX_RESPONSE_BYTES`` from a streaming response."""

    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        if not isinstance(chunk, bytes):
            try:
                chunk = bytes(chunk)
            except Exception:
                return None
        if len(chunk) > MAX_RESPONSE_BYTES - size:
            return None
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def _request_timeout_seconds(timeout: float | httpx.Timeout) -> float:
    if isinstance(timeout, httpx.Timeout):
        values = [
            value
            for value in (timeout.connect, timeout.read, timeout.write, timeout.pool)
            if value is not None
        ]
        return max(float(value) for value in values)
    return float(timeout)


def _health_payload_is_valid(body: object, expected_model: str) -> bool:
    """Validate only the bounded shape needed for a truthful health result."""

    if not isinstance(body, Mapping):
        return False
    models = body.get("data")
    if models is None:
        # Some compatible gateways return a small health object rather than a
        # model list.  A successful JSON object still proves endpoint/auth
        # reachability; model advertisement is checked when supplied.
        return True
    if not isinstance(models, list):
        return False
    return any(
        isinstance(item, Mapping)
        and (item.get("id") == expected_model or item.get("model") == expected_model)
        for item in models
    )


# Explicit class aliases preserve discoverability for callers that use the
# longer async/client naming convention.
AsyncOpenAICompatibleClient = OpenAICompatibleClient
AsyncOpenAIProvider = OpenAICompatibleClient
OpenAICompatibleAsyncClient = OpenAICompatibleClient
OpenAICompatibleProvider = OpenAICompatibleClient
OpenAIProvider = OpenAICompatibleClient


def _resolve_correlation_id(
    requested: str | None,
    factory: CorrelationIdFactory,
) -> tuple[str, bool]:
    if requested is None:
        try:
            candidate = str(factory())
        except Exception:
            candidate = str(uuid.uuid4())
        if _valid_correlation_id(candidate):
            return candidate, True
        return str(uuid.uuid4()), True
    if not isinstance(requested, str):
        return str(uuid.uuid4()), False
    candidate = requested.strip()
    if _valid_correlation_id(candidate):
        return candidate, True
    return str(uuid.uuid4()), False


def _valid_correlation_id(value: str) -> bool:
    return bool(value) and len(value) <= 128 and _CORRELATION_CONTROL.search(value) is None


def _validate_model(
    value: object,
    operation: ProviderOperation,
    correlation_id: str,
) -> str:
    if not isinstance(value, str):
        raise provider_error("invalid_model", operation, correlation_id, 0)
    normalized = value.strip()
    if not normalized or len(normalized) > 256 or _CORRELATION_CONTROL.search(normalized):
        raise provider_error("invalid_model", operation, correlation_id, 0)
    return normalized


def _serialize_messages(
    messages: Sequence[MessageInput] | None,
    operation: ProviderOperation,
    correlation_id: str,
) -> list[dict[str, str]]:
    if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence) or not messages or len(messages) > 1_024:
        raise provider_error("malformed_response", operation, correlation_id, 0)
    result: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, ProviderMessage):
            dto = message
        elif isinstance(message, Mapping):
            role = message.get("role")
            content = message.get("content")
            if not isinstance(role, str) or not isinstance(content, str):
                raise provider_error("malformed_response", operation, correlation_id, 0)
            try:
                dto = ProviderMessage.model_validate({"role": role, "content": content})
            except ValidationError:
                raise provider_error("malformed_response", operation, correlation_id, 0) from None
        else:
            raise provider_error("malformed_response", operation, correlation_id, 0)
        result.append(dto.model_dump(mode="json"))
    return result


def _validate_temperature(
    value: int | float | None,
    operation: ProviderOperation,
    correlation_id: str,
) -> float | None:
    if value is None:
        return None
    converted = _finite_float(value)
    if converted is None:
        raise provider_error("malformed_response", operation, correlation_id, 0)
    return converted


def _serialize_response_format(
    value: Mapping[str, object] | None,
    operation: ProviderOperation,
    correlation_id: str,
) -> dict[str, object]:
    if value is None:
        return {"type": "text"}
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise provider_error("malformed_response", operation, correlation_id, 0)
    result = dict(value)
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise provider_error("malformed_response", operation, correlation_id, 0) from None
    return result


def _extract_chat_result(
    body: object,
    expected_model: str,
    correlation_id: str,
    attempt: int,
) -> ChatCompletionResult:
    operation: ProviderOperation = "chat_completion"
    if not isinstance(body, Mapping):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if "choices" not in body or "model" not in body:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    choices = body["choices"]
    if not isinstance(choices, list):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if not choices or not isinstance(choices[0], Mapping):
        raise provider_error("missing_field", operation, correlation_id, attempt)
    choice = choices[0]
    if "message" not in choice:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    message = choice["message"]
    if not isinstance(message, Mapping):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if "content" not in message:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    content = message["content"]
    if not isinstance(content, str) or not content.strip():
        raise provider_error("missing_field", operation, correlation_id, attempt)
    model = body["model"]
    if not isinstance(model, str) or not model.strip() or len(model) > 256 or _CORRELATION_CONTROL.search(model):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    model = model.strip()
    if model != expected_model:
        raise provider_error("invalid_model", operation, correlation_id, attempt)
    finish_reason = choice.get("finish_reason", "stop")
    if not isinstance(finish_reason, str) or finish_reason not in _ALLOWED_FINISH_REASONS:
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    usage = body.get("usage")
    if usage is not None:
        if not isinstance(usage, Mapping) or any(
            not isinstance(key, str) or type(value) is not int for key, value in usage.items()
        ):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        usage = dict(usage)
    try:
        return ChatCompletionResult(
            model=model,
            content=content,
            finish_reason=finish_reason,
            correlation_id=correlation_id,
            usage=usage,
        )
    except ValidationError:
        raise provider_error("malformed_response", operation, correlation_id, attempt) from None


def _extract_chat_chunk(
    body: object,
    expected_model: str,
    correlation_id: str,
    attempt: int,
) -> ChatCompletionChunk | None:
    """Validate one OpenAI-compatible SSE payload without retaining raw data."""
    operation: ProviderOperation = "chat_completion"
    if not isinstance(body, Mapping):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    model = body.get("model", expected_model)
    if not isinstance(model, str) or model.strip() != expected_model or _CORRELATION_CONTROL.search(model):
        raise provider_error("invalid_model", operation, correlation_id, attempt)
    choices = body.get("choices")
    if not isinstance(choices, list):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if not choices:
        # Some providers send a usage-only event before [DONE]. It is safe to
        # ignore it because usage is not required to validate the answer.
        return None
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    delta = choice.get("delta", {})
    if not isinstance(delta, Mapping):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    content = delta.get("content", "")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and finish_reason not in _ALLOWED_FINISH_REASONS:
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    try:
        return ChatCompletionChunk(
            model=expected_model,
            delta=content,
            finish_reason=finish_reason,
            correlation_id=correlation_id,
        )
    except ValidationError:
        raise provider_error("malformed_response", operation, correlation_id, attempt) from None


def _extract_embedding_result(
    body: object,
    expected_model: str,
    correlation_id: str,
    attempt: int,
    dimensions: int,
) -> EmbeddingResult:
    operation: ProviderOperation = "embeddings"
    if not isinstance(body, Mapping):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if "data" not in body:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    data = body["data"]
    if not isinstance(data, list):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if not data or not isinstance(data[0], Mapping):
        raise provider_error("missing_field", operation, correlation_id, attempt)
    item = data[0]
    if "embedding" not in item:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    raw_vector = item["embedding"]
    if not isinstance(raw_vector, list):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if any(
        _finite_float(value) is None
        for value in raw_vector
    ):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if len(raw_vector) != dimensions:
        raise provider_error("embedding_dimension_mismatch", operation, correlation_id, attempt)
    if "model" not in body:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    model = body["model"]
    if not isinstance(model, str) or not model.strip() or len(model) > 256 or _CORRELATION_CONTROL.search(model):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    model = model.strip()
    if model != expected_model:
        raise provider_error("invalid_model", operation, correlation_id, attempt)
    vector = [_finite_float(value) for value in raw_vector]
    try:
        return EmbeddingResult(
            model=model,
            dimensions=dimensions,
            vector=vector,
            correlation_id=correlation_id,
        )
    except ValidationError:
        raise provider_error("malformed_response", operation, correlation_id, attempt) from None


def _classify_transport_error(
    error: Exception,
    operation: ProviderOperation,
    correlation_id: str,
    attempt: int,
) -> ProviderError:
    if isinstance(error, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
        return provider_error("timeout", operation, correlation_id, attempt)
    if isinstance(error, (httpx.RequestError, ConnectionError, OSError)):
        return provider_error("unavailable", operation, correlation_id, attempt)
    return provider_error("internal_error", operation, correlation_id, attempt)


def _classify_http_status(
    status: int,
    raw_body: bytes,
    operation: ProviderOperation,
    correlation_id: str,
    attempt: int,
) -> ProviderError:
    if status == 429:
        return provider_error("rate_limit", operation, correlation_id, attempt, status=status)
    if status == 408:
        return provider_error("timeout", operation, correlation_id, attempt, status=status)
    if 500 <= status <= 599:
        return provider_error("server_error", operation, correlation_id, attempt, status=status)
    body = _try_parse_json(raw_body)
    model_code = _model_error_code(body)
    if model_code == "model_not_found":
        return provider_error("model_not_found", operation, correlation_id, attempt, status=status)
    if model_code == "invalid_model":
        return provider_error("invalid_model", operation, correlation_id, attempt, status=status)
    return provider_error("http_error", operation, correlation_id, attempt, status=status)


def _try_parse_json(raw_body: bytes) -> object:
    if len(raw_body) > MAX_RESPONSE_BYTES:
        return None
    try:
        return json.loads(raw_body.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, TypeError, ValueError, RecursionError):
        return None


def _model_error_code(body: object) -> str | None:
    if not isinstance(body, Mapping):
        return None
    details = body.get("error", body)
    if not isinstance(details, Mapping):
        return None
    code = details.get("code")
    error_type = details.get("type")
    message = details.get("message")
    code_text = code.lower() if isinstance(code, str) else ""
    type_text = error_type.lower() if isinstance(error_type, str) else ""
    message_text = message.lower() if isinstance(message, str) else ""
    if code_text in {"model_not_found", "model-not-found", "model_not_found_error"}:
        return "model_not_found"
    if code_text in {"invalid_model", "invalid-model"}:
        return "invalid_model"
    if "model_not_found" in type_text or "model-not-found" in type_text:
        return "model_not_found"
    if re.search(r"model(?:[ _-]+.*)?(?:not[ _-]+found|does[ _-]+not[ _-]+exist)", message_text):
        return "model_not_found"
    if re.search(r"\bmodel\b.*\b(?:invalid|unavailable)\b", message_text):
        return "invalid_model"
    return None


def _reject_json_constant(value: str) -> object:
    raise ValueError(value)


def _finite_float(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except (OverflowError, ValueError, TypeError):
        return None
    return converted if math.isfinite(converted) else None


__all__ = [
    "MAX_RESPONSE_BYTES",
    "AsyncOpenAICompatibleClient",
    "AsyncOpenAIProvider",
    "OpenAICompatibleAsyncClient",
    "OpenAICompatibleClient",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
]
