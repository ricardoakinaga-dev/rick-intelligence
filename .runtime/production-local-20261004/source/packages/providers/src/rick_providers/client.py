"""Async OpenAI-compatible provider boundary.

Only this module knows about HTTP. Chat and embedding calls share the same
request, classification, retry, timeout, and correlation path, while the
health probe uses the same bounded client and redaction boundary so readiness
cannot be inferred from object construction.
"""

from __future__ import annotations

import asyncio
import codecs
import inspect
import json
import math
import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import aclosing, asynccontextmanager
from typing import Any

import httpx
from pydantic import ValidationError

from rick_providers.sampling import Temperature, USE_DEFAULT_TEMPERATURE

from rick_contracts.providers import (
    ChatCompletionChunk,
    ChatCompletionResult,
    EmbeddingResult,
    ProviderMessage,
    ProviderToolCall,
    ProviderToolCallDelta,
    ProviderToolCallDeltaFunction,
    ProviderToolCallFunction,
    ProviderUsage,
)

from rick_providers.cleanup import ResponseCleanup, await_io, bounded_cleanup
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

try:
    from rick_observability import inject_w3c_trace_headers
except ImportError:  # pragma: no cover - provider package can run standalone.
    def inject_w3c_trace_headers(headers: Mapping[str, str] | None = None) -> dict[str, str]:
        return dict(headers or {})


MAX_RESPONSE_BYTES = 1_000_000
MAX_TOOL_COUNT = 128
MAX_TOOL_SCHEMA_BYTES = 262_144
MAX_TOOLS_BYTES = 1_000_000
MAX_TOOL_CALL_COUNT = 32
_ALLOWED_FINISH_REASONS = frozenset({"stop", "length", "content_filter", "tool_calls"})
_CORRELATION_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SSE_LINE_END = re.compile(r"\r\n|[\r\n]")

SleepFunction = Callable[[float], Awaitable[object] | object]
CorrelationIdFactory = Callable[[], str]
MessageInput = ProviderMessage | Mapping[str, object]


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _loads_json(value: str | bytes) -> object:
    return json.loads(
        value,
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_json_constant,
    )


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
                embedding_provider_kind=config.embedding_provider_kind,
                embedding_base_url=config.embedding_base_url,
                embedding_api_key=config.embedding_api_key,
                anthropic_version=config.anthropic_version,
                max_output_tokens=config.max_output_tokens,
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
            await bounded_cleanup([self._client.aclose])
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
            return await self._health_request(correlation, model)
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
        temperature: Temperature = USE_DEFAULT_TEMPERATURE,
        response_format: Mapping[str, object] | None = None,
        tools: Sequence[Mapping[str, object]] | None = None,
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
        normalized_temperature = _validate_temperature(0.2 if temperature is USE_DEFAULT_TEMPERATURE else temperature, operation, correlation)
        normalized_format = _serialize_response_format(response_format, operation, correlation)
        normalized_tools = _serialize_tools(tools, operation, correlation)
        payload: dict[str, object] = {
            "model": normalized_model,
            "messages": serialized_messages,
            "temperature": normalized_temperature,
            "response_format": normalized_format,
        }
        if normalized_tools is not None:
            payload["tools"] = normalized_tools
        _configure_frontier_payload(payload, self.config, operation, correlation, temperature)

        async def attempt_request(attempt: int) -> ChatCompletionResult:
            body = await self._post_json(
                operation,
                "/chat/completions",
                payload,
                correlation,
                attempt,
            )
            result = _extract_chat_result(body, normalized_model, correlation, attempt)
            return _validate_response_format_result(
                result,
                normalized_format,
                operation,
                correlation,
                attempt,
            )

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
        embedding_kind = self.config.embedding_provider_kind or self.config.provider_kind
        if embedding_kind == "openai" and normalized_model.startswith("text-embedding-3-"):
            payload["dimensions"] = self.config.embedding_dimensions

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
        temperature: Temperature = USE_DEFAULT_TEMPERATURE,
        response_format: Mapping[str, object] | None = None,
        tools: Sequence[Mapping[str, object]] | None = None,
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
            model_or_messages, messages, temperature, response_format, tools,
            model=model, correlation_id=correlation_id,
        )

    async def _chat_completion_stream(
        self,
        model_or_messages: str | Sequence[MessageInput] | None,
        messages: Sequence[MessageInput] | None,
        temperature: Temperature,
        response_format: Mapping[str, object] | None,
        tools: Sequence[Mapping[str, object]] | None,
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
        normalized_temperature = _validate_temperature(0.2 if temperature is USE_DEFAULT_TEMPERATURE else temperature, operation, correlation)
        normalized_format = _serialize_response_format(response_format, operation, correlation)
        normalized_tools = _serialize_tools(tools, operation, correlation)
        payload: dict[str, object] = {
            "model": normalized_model, "messages": serialized_messages,
            "temperature": normalized_temperature, "response_format": normalized_format,
            "stream": True,
        }
        if normalized_tools is not None:
            payload["tools"] = normalized_tools
        _configure_frontier_payload(payload, self.config, operation, correlation, temperature)

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
                headers = inject_w3c_trace_headers(headers)
                deadline = asyncio.get_running_loop().time() + _request_timeout_seconds(self.config.timeout)
                async with self._response_context(
                    "POST", url, headers=headers, payload=payload, deadline=deadline,
                ) as response:
                    status = response.status_code
                    if not 200 <= status <= 299:
                        raw = await await_io(_read_bounded_response(response), deadline)
                        raise _classify_http_status(status, raw or b"", operation, correlation, attempt)
                    saw_done = False
                    terminal_chunk: ChatCompletionChunk | None = None
                    has_content = False
                    has_tools = False
                    streamed_tools: dict[int, dict[str, Any]] = {}
                    json_fragments: list[str] = []
                    async with aclosing(_iter_bounded_sse_lines(response, operation, correlation, attempt)) as lines:
                        while True:
                            # One absolute deadline bounds headers and the full
                            # body, including preterminal drip and tail events.
                            # End the timeout context before yielding to callers.
                            if asyncio.get_running_loop().time() >= deadline:
                                raise TimeoutError
                            try:
                                line = await await_io(anext(lines), deadline)
                            except StopAsyncIteration:
                                break
                            if not line or line.startswith(":"):
                                continue
                            if line.startswith(("event:", "id:", "retry:")):
                                continue
                            if not line.startswith("data:") or saw_done:
                                raise provider_error("malformed_response", operation, correlation, attempt)
                            data = line[5:].strip()
                            if data == "[DONE]":
                                saw_done = True
                                continue
                            try:
                                decoded = _loads_json(data)
                            except (TypeError, ValueError, RecursionError):
                                raise provider_error("invalid_json", operation, correlation, attempt) from None
                            chunk = _extract_chat_chunk(decoded, normalized_model, correlation, attempt)
                            if chunk is None:
                                continue
                            if (chunk.usage is not None and not chunk.delta and not chunk.tool_calls
                                    and chunk.finish_reason is None):
                                # Usage-only events are legal up to [DONE]. Keep
                                # their accounting visible to the product's token
                                # budget even when the terminal choice arrived first.
                                emitted = True
                                if terminal_chunk is not None:
                                    previous = terminal_chunk.usage
                                    if previous is None or chunk.usage.total_tokens >= previous.total_tokens:
                                        terminal_chunk = terminal_chunk.model_copy(update={"usage": chunk.usage})
                                else:
                                    yield chunk
                                continue
                            if terminal_chunk is not None:
                                raise provider_error("malformed_response", operation, correlation, attempt)
                            has_content = has_content or bool(chunk.delta.strip())
                            has_tools = has_tools or bool(chunk.tool_calls)
                            for call in chunk.tool_calls or []:
                                assembled = streamed_tools.setdefault(call.index, {
                                    "id": None, "type": None,
                                    "function": {"name": None, "arguments": ""},
                                })
                                function = assembled["function"]
                                for target, field, value in (
                                    (assembled, "id", call.id), (assembled, "type", call.type),
                                    (function, "name", call.function.name),
                                ):
                                    if value is not None:
                                        if target[field] not in (None, value):
                                            raise provider_error("malformed_response", operation, correlation, attempt)
                                        target[field] = value
                                function["arguments"] += call.function.arguments
                            if normalized_format.get("type") == "json_object":
                                json_fragments.append(chunk.delta)
                            # Do not replay accepted output, including a terminal
                            # chunk held for full-response validation.
                            emitted = True
                            if chunk.finish_reason is not None:
                                terminal_chunk = chunk
                            else:
                                yield chunk
                    if not saw_done:
                        raise provider_error("malformed_response", operation, correlation, attempt)
                    if terminal_chunk is None:
                        raise provider_error("missing_field", operation, correlation, attempt)
                    if streamed_tools:
                        _extract_tool_calls(
                            [streamed_tools[index] for index in sorted(streamed_tools)],
                            operation, correlation, attempt,
                        )
                    if not has_content and (not has_tools or normalized_format.get("type") == "json_object"):
                        raise provider_error("missing_field", operation, correlation, attempt)
                    _validate_tool_termination(terminal_chunk.finish_reason, bool(streamed_tools), operation, correlation, attempt)
                    if normalized_format.get("type") == "json_object":
                        _validate_response_format_result(
                            ChatCompletionResult(
                                model=normalized_model, content="".join(json_fragments),
                                finish_reason=terminal_chunk.finish_reason, correlation_id=correlation,
                            ),
                            normalized_format, operation, correlation, attempt,
                        )
                yield terminal_chunk
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
        temperature: Temperature = USE_DEFAULT_TEMPERATURE,
        response_format: Mapping[str, object] | None = None,
        tools: Sequence[Mapping[str, object]] | None = None,
        correlation_id: str | None = None,
    ) -> ChatCompletionResult:
        """Short alias with messages-first argument order."""

        return await self.chat_completion(
            model,
            messages,
            temperature,
            response_format,
            tools,
            correlation_id=correlation_id,
        )

    @asynccontextmanager
    async def _response_context(self, method: str, url: str, *, headers: Mapping[str, str],
                                payload: Mapping[str, object] | None = None,
                                deadline: float | None = None):
        request = httpx.Request(
            method, url, headers=headers, json=dict(payload) if payload is not None else None,
            extensions={"timeout": httpx.Timeout(self.config.timeout).as_dict()},
        )
        # Request construction must not merge client headers/cookies; auth=None
        # also suppresses client-level auth. The injected transport stays intact.
        async with asyncio.timeout_at(deadline):
            response = await self._ensure_client().send(
                request, auth=None, stream=True, follow_redirects=False,
            )
        cleanup = ResponseCleanup(response)
        first_failure = None
        try:
            yield response
        except BaseException as exc:
            first_failure = exc
            raise
        finally:
            try:
                await cleanup.close()
            except Exception:
                if first_failure is not None:
                    # Never log raw exceptions, endpoints, or payloads.
                    logging.getLogger(__name__).error(
                        "provider_cleanup_after_failure code=%s",
                        first_failure.code if isinstance(first_failure, ProviderError) else type(first_failure).__name__,
                    )
                if isinstance(first_failure, asyncio.CancelledError):
                    raise first_failure from None
                raise

    async def _post_json(
        self,
        operation: ProviderOperation,
        endpoint: str,
        payload: Mapping[str, object],
        correlation_id: str,
        attempt: int,
    ) -> object:
        base_url = self.config.embedding_base_url if operation == "embeddings" and self.config.embedding_provider_kind else self.config.base_url
        url = f"{base_url.rstrip('/')}{endpoint}"
        headers = self._request_headers(operation, correlation_id)

        try:
            deadline = asyncio.get_running_loop().time() + _request_timeout_seconds(self.config.timeout)
            async with self._response_context("POST", url, headers=headers, payload=payload, deadline=deadline) as response:
                status = response.status_code
                raw = await await_io(_read_bounded_response(response), deadline)
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
            raise provider_error("malformed_response", operation, correlation_id, attempt, status=status) from None
        try:
            return _loads_json(text)
        except (TypeError, ValueError, RecursionError):
            raise provider_error("invalid_json", operation, correlation_id, attempt, status=status) from None

    def _request_headers(self, operation: ProviderOperation, correlation_id: str) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Correlation-ID": correlation_id,
        }
        key = self.config.embedding_api_key if operation == "embeddings" and self.config.embedding_provider_kind else self.config.api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return inject_w3c_trace_headers(headers)

    async def _health_request(self, correlation_id: str, model: str) -> bool:
        url = f"{self.config.base_url.rstrip('/')}/models"
        headers = {
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        headers = inject_w3c_trace_headers(headers)

        deadline = asyncio.get_running_loop().time() + _request_timeout_seconds(self.config.timeout)
        async with self._response_context("GET", url, headers=headers, deadline=deadline) as response:
            status = response.status_code
            raw = await await_io(_read_bounded_response(response), deadline)
        if not 200 <= status <= 299 or raw is None:
            return False
        try:
            body = _loads_json(raw.decode("utf-8"))
        except (UnicodeDecodeError, TypeError, ValueError, RecursionError):
            return False
        return _health_payload_is_valid(body, model)

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout,
                transport=self._transport,
                follow_redirects=False,
                # Provider credentials and requests must stay on the explicit
                # configured origin; ambient proxy variables are not runtime
                # authority and may redirect them across a trust boundary.
                trust_env=False,
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
        if self.config.provider_kind == "anthropic" and self.provider_kind != "anthropic":
            raise provider_error("invalid_configuration", operation, correlation_id, 0)
        return correlation_id


async def _iter_bounded_sse_lines(
    response: httpx.Response,
    operation: ProviderOperation,
    correlation_id: str,
    attempt: int,
) -> AsyncIterator[str]:
    total_bytes = 0
    # Validate the entire envelope, including comments and post-DONE tails.
    # Strip only a fully decoded initial BOM; genuine U+FFFD remains valid text.
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    pending: list[str] = []
    at_start = True
    skip_lf = False
    async with aclosing(response.aiter_bytes()) as chunks:
        async for chunk in chunks:
            if len(chunk) > MAX_RESPONSE_BYTES - total_bytes:
                raise provider_error("malformed_response", operation, correlation_id, attempt)
            total_bytes += len(chunk)
            try:
                text = decoder.decode(chunk)
            except UnicodeDecodeError:
                raise provider_error("malformed_response", operation, correlation_id, attempt, status=response.status_code) from None
            if not text:
                continue
            if at_start:
                text = text.removeprefix("\ufeff")
                at_start = False
            # A CRLF split between chunks is one line ending, just as when
            # received together. Buffer fragments without rescanning a long line.
            if skip_lf and text.startswith("\n"):
                text = text[1:]
            skip_lf = text.endswith("\r")
            start = 0
            for separator in _SSE_LINE_END.finditer(text):
                pending.append(text[start:separator.start()])
                yield "".join(pending)
                pending.clear()
                start = separator.end()
            if start < len(text):
                pending.append(text[start:])
        try:
            decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            raise provider_error("malformed_response", operation, correlation_id, attempt, status=response.status_code) from None
    if pending:
        yield "".join(pending)


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


def _configure_frontier_payload(payload: dict[str, object], config: ProviderConfig,
                                operation: ProviderOperation, correlation_id: str,
                                temperature: Temperature) -> None:
    # Reasoning families reject the historic custom temperature default.
    # Compatible gateways retain their previous wire contract.
    if temperature is None:
        payload.pop("temperature", None)
    model = str(payload["model"])
    if config.provider_kind == "openai" and model.startswith(("gpt-6", "gpt-5", "o1", "o3", "o4")):
        if temperature is not USE_DEFAULT_TEMPERATURE and temperature is not None:
            raise provider_error("invalid_configuration", operation, correlation_id, 0)
        payload.pop("temperature", None)
        if payload.get("tools"):
            # GPT-6 frontier tool calls need Responses, or an explicit non-
            # reasoning mode for Sol/Luna. Never silently drop requested tools.
            if model.startswith("gpt-6"):
                raise provider_error("invalid_configuration", operation, correlation_id, 0)


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
            if set(message) - {"role", "content"}:
                raise provider_error("malformed_response", operation, correlation_id, 0)
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
    kind = result.get("type")
    if not isinstance(kind, str) or kind not in {"text", "json_object", "json_schema"}:
        raise provider_error("malformed_response", operation, correlation_id, 0)
    allowed = {"type", "json_schema"} if kind == "json_schema" else {"type"}
    if set(result) - allowed:
        raise provider_error("malformed_response", operation, correlation_id, 0)
    if kind == "json_schema":
        schema = result.get("json_schema")
        if not isinstance(schema, Mapping) or set(schema) - {"name", "description", "schema", "strict"}:
            raise provider_error("malformed_response", operation, correlation_id, 0)
        name = schema.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise provider_error("malformed_response", operation, correlation_id, 0)
        if not isinstance(schema.get("schema"), Mapping):
            raise provider_error("malformed_response", operation, correlation_id, 0)
        if schema.get("strict") is not None and type(schema["strict"]) is not bool:
            raise provider_error("malformed_response", operation, correlation_id, 0)
        if schema.get("description") is not None and not isinstance(schema["description"], str):
            raise provider_error("malformed_response", operation, correlation_id, 0)
        result["json_schema"] = dict(schema)
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise provider_error("malformed_response", operation, correlation_id, 0) from None
    return result


def _validate_response_format_result(
    result: ChatCompletionResult,
    response_format: Mapping[str, object],
    operation: ProviderOperation,
    correlation_id: str,
    attempt: int,
) -> ChatCompletionResult:
    """Validate the response body promised by the supported JSON mode."""

    if response_format.get("type") != "json_object":
        return result
    if not result.content.strip():
        raise provider_error("missing_field", operation, correlation_id, attempt)
    try:
        decoded = _loads_json(result.content)
    except (TypeError, ValueError, RecursionError):
        raise provider_error("invalid_json", operation, correlation_id, attempt) from None
    if not isinstance(decoded, dict):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    return result


def _serialize_tools(
    value: Sequence[Mapping[str, object]] | None,
    operation: ProviderOperation,
    correlation_id: str,
) -> list[dict[str, object]] | None:
    """Normalize function tools without allowing arbitrary payload passthrough."""

    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise provider_error("malformed_response", operation, correlation_id, 0)
    if not value or len(value) > MAX_TOOL_COUNT:
        raise provider_error("malformed_response", operation, correlation_id, 0)

    normalized: list[dict[str, object]] = []
    names: set[str] = set()
    total_bytes = 0
    for tool in value:
        if not isinstance(tool, Mapping) or any(not isinstance(key, str) for key in tool):
            raise provider_error("malformed_response", operation, correlation_id, 0)
        if set(tool) - {"type", "function"} or tool.get("type") != "function":
            raise provider_error("malformed_response", operation, correlation_id, 0)
        function = tool.get("function")
        if not isinstance(function, Mapping) or any(not isinstance(key, str) for key in function):
            raise provider_error("malformed_response", operation, correlation_id, 0)
        if set(function) - {"name", "description", "parameters", "strict"}:
            raise provider_error("malformed_response", operation, correlation_id, 0)
        name = function.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or _CORRELATION_CONTROL.search(name):
            raise provider_error("malformed_response", operation, correlation_id, 0)
        if name.strip() in names:
            raise provider_error("malformed_response", operation, correlation_id, 0)
        names.add(name.strip())
        description = function.get("description")
        if description is not None and (
            not isinstance(description, str)
            or len(description) > 4_096
            or _CORRELATION_CONTROL.search(description)
        ):
            raise provider_error("malformed_response", operation, correlation_id, 0)
        parameters = function.get("parameters", {"type": "object", "properties": {}})
        if not isinstance(parameters, Mapping) or any(not isinstance(key, str) for key in parameters):
            raise provider_error("malformed_response", operation, correlation_id, 0)
        strict = function.get("strict")
        if strict is not None and type(strict) is not bool:
            raise provider_error("malformed_response", operation, correlation_id, 0)
        normalized_function: dict[str, object] = {
            "name": name.strip(),
            "parameters": dict(parameters),
        }
        if description is not None:
            normalized_function["description"] = description
        if strict is not None:
            normalized_function["strict"] = strict
        candidate = {"type": "function", "function": normalized_function}
        try:
            encoded = json.dumps(candidate, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise provider_error("malformed_response", operation, correlation_id, 0) from None
        encoded_size = len(encoded.encode("utf-8"))
        if encoded_size > MAX_TOOL_SCHEMA_BYTES:
            raise provider_error("malformed_response", operation, correlation_id, 0)
        total_bytes += encoded_size
        if total_bytes > MAX_TOOLS_BYTES:
            raise provider_error("malformed_response", operation, correlation_id, 0)
        normalized.append(candidate)
    return normalized


def _normalize_openai_usage(value: object, operation: ProviderOperation,
                            correlation_id: str, attempt: int) -> ProviderUsage | None:
    if value is None:
        return None
    totals = {"prompt_tokens", "completion_tokens", "total_tokens"}
    details = {
        "prompt_tokens_details": {"cached_tokens", "audio_tokens", "text_tokens", "image_tokens", "cache_write_tokens"},
        "completion_tokens_details": {"reasoning_tokens", "audio_tokens", "accepted_prediction_tokens", "rejected_prediction_tokens", "text_tokens"},
    }
    if not isinstance(value, Mapping) or set(value) - totals - set(details):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    try:
        usage = ProviderUsage.model_validate({key: value[key] for key in totals})
    except (KeyError, ValidationError):
        raise provider_error("malformed_response", operation, correlation_id, attempt) from None
    if usage.total_tokens != usage.prompt_tokens + usage.completion_tokens:
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    for key, allowed in details.items():
        nested = value.get(key)
        if nested is None:
            continue
        total = usage.prompt_tokens if key == "prompt_tokens_details" else usage.completion_tokens
        if not isinstance(nested, Mapping) or set(nested) - allowed or any(
            counter is not None and (type(counter) is not int or not 0 <= counter <= total)
            for counter in nested.values()
        ):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        # Cache and prediction counters overlap modality counts; don't add them
        # twice. Modality and reasoning categories are disjoint decompositions.
        disjoint = ("text_tokens", "image_tokens", "audio_tokens") if key == "prompt_tokens_details" else ("text_tokens", "audio_tokens", "reasoning_tokens")
        if sum(nested.get(name) or 0 for name in disjoint) > total:
            raise provider_error("malformed_response", operation, correlation_id, attempt)
    return usage


def _validate_tool_termination(reason: str, has_tools: bool, operation: ProviderOperation,
                               correlation_id: str, attempt: int) -> None:
    if (reason == "tool_calls" and not has_tools) or (reason == "stop" and has_tools):
        raise provider_error("malformed_response", operation, correlation_id, attempt)


def _extract_chat_result(
    body: object,
    expected_model: str,
    correlation_id: str,
    attempt: int,
) -> ChatCompletionResult:
    operation: ProviderOperation = "chat_completion"
    if not isinstance(body, Mapping) or "error" in body:
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
    if not isinstance(message, Mapping) or message.get("role") != "assistant":
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    # A refusal cannot be represented as a successful content/tool completion.
    # Permit the normal absent/null/empty marker; reject refusal and invalid types.
    if message.get("refusal") is not None and message.get("refusal") != "":
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if "content" not in message and "tool_calls" not in message:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    content = message.get("content", "")
    if content is None:
        content = ""
    if not isinstance(content, str) or len(content) > MAX_RESPONSE_BYTES:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    tool_calls = _extract_tool_calls(message.get("tool_calls"), operation, correlation_id, attempt)
    if not content.strip() and not tool_calls:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    model = body["model"]
    if not isinstance(model, str) or not model.strip() or len(model) > 256 or _CORRELATION_CONTROL.search(model):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    model = model.strip()
    if model != expected_model:
        raise provider_error("invalid_model", operation, correlation_id, attempt)
    if "finish_reason" not in choice:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    finish_reason = choice["finish_reason"]
    if not isinstance(finish_reason, str) or finish_reason not in _ALLOWED_FINISH_REASONS:
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    _validate_tool_termination(finish_reason, bool(tool_calls), operation, correlation_id, attempt)
    usage = _normalize_openai_usage(body.get("usage"), operation, correlation_id, attempt)
    try:
        return ChatCompletionResult(
            model=model,
            content=content,
            tool_calls=tool_calls,
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
    if not isinstance(body, Mapping) or "error" in body:
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    model = body.get("model", expected_model)
    if not isinstance(model, str) or model.strip() != expected_model or _CORRELATION_CONTROL.search(model):
        raise provider_error("invalid_model", operation, correlation_id, attempt)
    usage = _normalize_openai_usage(body.get("usage"), operation, correlation_id, attempt)
    choices = body.get("choices")
    if not isinstance(choices, list):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if not choices:
        # Validated usage-only events are legal before [DONE], including after
        # the terminal choice. No data events are legal after [DONE].
        return ChatCompletionChunk(
            model=expected_model, correlation_id=correlation_id, usage=usage,
        ) if usage is not None else None
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    delta = choice.get("delta", {})
    if not isinstance(delta, Mapping) or ("role" in delta and delta["role"] != "assistant"):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if delta.get("refusal") is not None and delta.get("refusal") != "":
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    content = delta.get("content", "")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    finish_reason = choice.get("finish_reason")
    tool_calls = _extract_tool_call_deltas(delta.get("tool_calls"), operation, correlation_id, attempt)
    if not content and not tool_calls and finish_reason is None and usage is None:
        return None
    if finish_reason is not None and (
        not isinstance(finish_reason, str) or finish_reason not in _ALLOWED_FINISH_REASONS
    ):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    try:
        return ChatCompletionChunk(
            model=expected_model,
            delta=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            correlation_id=correlation_id,
            usage=usage,
        )
    except ValidationError:
        raise provider_error("malformed_response", operation, correlation_id, attempt) from None


def _extract_tool_calls(
    value: object,
    operation: ProviderOperation,
    correlation_id: str,
    attempt: int,
) -> list[ProviderToolCall] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value or len(value) > MAX_TOOL_CALL_COUNT:
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    calls: list[ProviderToolCall] = []
    identities: set[str] = set()
    for raw_call in value:
        if not isinstance(raw_call, Mapping):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        raw_id = raw_call.get("id")
        raw_type = raw_call.get("type")
        raw_function = raw_call.get("function")
        if not isinstance(raw_id, str) or not raw_id.strip() or len(raw_id) > 256 or _CORRELATION_CONTROL.search(raw_id):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        if raw_id.strip() in identities:
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        identities.add(raw_id.strip())
        if set(raw_call) - {"id", "type", "function"}:
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        if raw_type != "function" or not isinstance(raw_function, Mapping):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        if set(raw_function) - {"name", "arguments"}:
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        raw_name = raw_function.get("name")
        raw_arguments = raw_function.get("arguments")
        if not isinstance(raw_name, str) or not raw_name.strip() or len(raw_name) > 128 or _CORRELATION_CONTROL.search(raw_name):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        if not isinstance(raw_arguments, str) or not raw_arguments.strip() or len(raw_arguments) > MAX_RESPONSE_BYTES:
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        try:
            decoded_arguments = _loads_json(raw_arguments)
        except (TypeError, ValueError, RecursionError):
            raise provider_error("invalid_json", operation, correlation_id, attempt) from None
        if not isinstance(decoded_arguments, dict):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        try:
            calls.append(
                ProviderToolCall(
                    id=raw_id.strip(),
                    type="function",
                    function=ProviderToolCallFunction(
                        name=raw_name.strip(),
                        arguments=raw_arguments,
                    ),
                )
            )
        except ValidationError:
            raise provider_error("malformed_response", operation, correlation_id, attempt) from None
    return calls


def _extract_tool_call_deltas(
    value: object,
    operation: ProviderOperation,
    correlation_id: str,
    attempt: int,
) -> list[ProviderToolCallDelta] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value or len(value) > MAX_TOOL_CALL_COUNT:
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    deltas: list[ProviderToolCallDelta] = []
    indices: set[int] = set()
    for raw_call in value:
        if not isinstance(raw_call, Mapping):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        index = raw_call.get("index")
        raw_id = raw_call.get("id")
        raw_type = raw_call.get("type")
        raw_function = raw_call.get("function", {})
        if type(index) is not int or not 0 <= index < MAX_TOOL_CALL_COUNT or index in indices:
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        indices.add(index)
        if set(raw_call) - {"index", "id", "type", "function"}:
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        if isinstance(raw_function, Mapping) and set(raw_function) - {"name", "arguments"}:
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        if raw_id is not None and (
            not isinstance(raw_id, str) or not raw_id.strip() or len(raw_id) > 256 or _CORRELATION_CONTROL.search(raw_id)
        ):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        if raw_type is not None and raw_type != "function":
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        if not isinstance(raw_function, Mapping):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        raw_name = raw_function.get("name")
        arguments = raw_function.get("arguments", "")
        if raw_name is not None and (
            not isinstance(raw_name, str) or not raw_name.strip() or len(raw_name) > 128 or _CORRELATION_CONTROL.search(raw_name)
        ):
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        if not isinstance(arguments, str) or len(arguments) > MAX_RESPONSE_BYTES:
            raise provider_error("malformed_response", operation, correlation_id, attempt)
        try:
            deltas.append(
                ProviderToolCallDelta(
                    index=index,
                    id=raw_id.strip() if isinstance(raw_id, str) else None,
                    type="function" if raw_type == "function" else None,
                    function=ProviderToolCallDeltaFunction(
                        name=raw_name.strip() if isinstance(raw_name, str) else None,
                        arguments=arguments,
                    ),
                )
            )
        except ValidationError:
            raise provider_error("malformed_response", operation, correlation_id, attempt) from None
    return deltas


def _extract_embedding_result(
    body: object,
    expected_model: str,
    correlation_id: str,
    attempt: int,
    dimensions: int,
) -> EmbeddingResult:
    operation: ProviderOperation = "embeddings"
    if not isinstance(body, Mapping) or "error" in body:
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if "data" not in body:
        raise provider_error("missing_field", operation, correlation_id, attempt)
    data = body["data"]
    if not isinstance(data, list):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if not data or not isinstance(data[0], Mapping):
        raise provider_error("missing_field", operation, correlation_id, attempt)
    if len(data) != 1:
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    item = data[0]
    if type(item.get("index")) is not int or item["index"] != 0:
        raise provider_error("malformed_response", operation, correlation_id, attempt)
    if ("object" in item and item["object"] != "embedding") or ("object" in body and body["object"] != "list"):
        raise provider_error("malformed_response", operation, correlation_id, attempt)
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
        return _loads_json(raw_body.decode("utf-8"))
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
