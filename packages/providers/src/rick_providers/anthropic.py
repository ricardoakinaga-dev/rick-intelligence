"""Native Messages adapter; HTTP bounds and safe errors share the provider port.

Only text and client function tools fit the current DTOs. Unsupported content
and refusal metadata fail closed instead of disappearing during normalization.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import aclosing
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from rick_providers.sampling import Temperature, USE_DEFAULT_TEMPERATURE

from rick_contracts.providers import ChatCompletionChunk, ChatCompletionResult, ProviderUsage
from rick_providers.client import (
    MAX_RESPONSE_BYTES, MAX_TOOL_CALL_COUNT, MessageInput, OpenAICompatibleClient,
    _classify_http_status, _classify_transport_error, _extract_tool_call_deltas,
    _extract_tool_calls, _iter_bounded_sse_lines, _loads_json,
    _read_bounded_response, _request_timeout_seconds, _serialize_messages,
    _serialize_tools, _validate_model, _validate_response_format_result,
    _validate_temperature, inject_w3c_trace_headers,
)
from rick_providers.cleanup import await_io
from rick_providers.errors import ProviderError, ProviderOperation, provider_error
from rick_providers.model_identity import matches_model


def _bad(correlation: str, attempt: int = 0) -> ProviderError:
    return provider_error("malformed_response", "chat_completion", correlation, attempt)


def _empty_citations(block: Mapping) -> bool:
    value = block.get("citations")
    return value is None or (isinstance(value, list) and not value)


_MODEL_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


def _native_datetime(value: object) -> bool:
    """Use the same RFC 3339 lexical and calendar gate for native timestamps."""
    if not isinstance(value, str) or _MODEL_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _capability_support(value: object) -> bool:
    return isinstance(value, Mapping) and type(value.get("supported")) is bool


def _model_capabilities(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    for name in ("batch", "citations", "code_execution", "image_input", "pdf_input", "structured_outputs"):
        if not _capability_support(value.get(name)):
            return False
    context, effort, thinking = (value.get(name) for name in ("context_management", "effort", "thinking"))
    if not all(_capability_support(group) for group in (context, effort, thinking)):
        return False
    for name in ("clear_thinking_20251015", "clear_tool_uses_20250919", "compact_20260112"):
        if context.get(name) is not None and not _capability_support(context[name]):
            return False
    for name in ("high", "low", "max", "medium"):
        if not _capability_support(effort.get(name)):
            return False
    if effort.get("xhigh") is not None and not _capability_support(effort["xhigh"]):
        return False
    types = thinking.get("types")
    return (isinstance(types, Mapping)
            and all(_capability_support(types.get(name)) for name in ("adaptive", "enabled")))


def _model_metadata(body: Mapping) -> bool:
    """Bounded native ModelInfo gate, not capability negotiation or selection.

    Validate the documented required metadata and supplied known optional
    fields. Unknown extensions are ignored and never confer authority. The
    shared response byte bound limits input; this fixed shape has no recursion.
    """
    timestamp = body.get("created_at")
    if not isinstance(body.get("display_name"), str) or not _native_datetime(timestamp):
        return False
    for name in ("max_input_tokens", "max_tokens"):
        if body.get(name) is not None and (type(body[name]) is not int or body[name] < 0):
            return False
    return body.get("capabilities") is None or _model_capabilities(body["capabilities"])


def _usage(raw: object, correlation: str, attempt: int) -> ProviderUsage:
    if not isinstance(raw, Mapping):
        raise _bad(correlation, attempt)
    names = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    supported = set(names) | {"cache_creation", "output_tokens_details", "server_tool_use", "inference_geo", "service_tier"}
    if set(raw) - supported or "input_tokens" not in raw or "output_tokens" not in raw:
        raise _bad(correlation, attempt)
    counters = {}
    for name in names:
        value = raw.get(name, 0)
        if value is None and name.startswith("cache_"):
            value = 0
        if type(value) is not int or not 0 <= value <= 10_000_000:
            raise _bad(correlation, attempt)
        counters[name] = value
    for name, fields in {
        "cache_creation": {"ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens"},
        "output_tokens_details": {"thinking_tokens"},
        "server_tool_use": {"web_fetch_requests", "web_search_requests"},
    }.items():
        nested = raw.get(name)
        if nested is None:
            continue
        if not isinstance(nested, Mapping) or set(nested) != fields or any(
            type(value) is not int or not 0 <= value <= 10_000_000 for value in nested.values()
        ):
            raise _bad(correlation, attempt)
        if name == "cache_creation" and sum(nested.values()) > counters["cache_creation_input_tokens"]:
            raise _bad(correlation, attempt)
        if name == "output_tokens_details" and nested["thinking_tokens"] > counters["output_tokens"]:
            raise _bad(correlation, attempt)
    if raw.get("inference_geo") is not None and not isinstance(raw["inference_geo"], str):
        raise _bad(correlation, attempt)
    if raw.get("service_tier") is not None and raw["service_tier"] not in ("standard", "priority", "batch"):
        raise _bad(correlation, attempt)
    prompt = counters["input_tokens"] + counters["cache_creation_input_tokens"] + counters["cache_read_input_tokens"]
    completion = raw["output_tokens"]
    try:
        return ProviderUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)
    except ValidationError:
        raise _bad(correlation, attempt) from None


def _finish(body: Mapping, correlation: str, attempt: int) -> str:
    details = body.get("stop_details")
    if details is not None:
        # Native stop_details is reserved for refusal metadata. In particular,
        # the API reference also shows refusal details paired with end_turn.
        raise _bad(correlation, attempt)
    reasons = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
               "model_context_window_exceeded": "length", "tool_use": "tool_calls"}
    reason = body.get("stop_reason")
    if not isinstance(reason, str) or reason not in reasons:
        raise _bad(correlation, attempt)
    sequence = body.get("stop_sequence")
    if reason == "stop_sequence":
        if not isinstance(sequence, str) or not sequence:
            raise _bad(correlation, attempt)
    elif sequence is not None:
        raise _bad(correlation, attempt)
    return reasons[reason]


def _cumulative_usage(previous: Mapping, update: Mapping, correlation: str, attempt: int) -> dict:
    """Retain omitted delta fields; validate supplied raw counters before totals.

    Messages deltas may supply only output_tokens. A supplied partition or
    nested object, however, cannot erase or regress previously known counters.
    This prevents a growing normalized total from concealing a raw regression.
    """
    merged = {**previous, **update}
    _usage(merged, correlation, attempt)
    for field in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        old, new = previous.get(field), merged.get(field)
        if old is not None and (new is None or new < old):
            raise _bad(correlation, attempt)
    for field in ("cache_creation", "output_tokens_details", "server_tool_use"):
        old, new = previous.get(field), merged.get(field)
        if isinstance(old, Mapping):
            if not isinstance(new, Mapping) or not set(old) <= set(new):
                raise _bad(correlation, attempt)
            if any(new[name] < value for name, value in old.items()):
                raise _bad(correlation, attempt)
    return merged


def _result(body: object, model: str, correlation: str, attempt: int) -> ChatCompletionResult:
    if not isinstance(body, Mapping) or "error" in body or body.get("type") != "message" or body.get("role") != "assistant":
        raise _bad(correlation, attempt)
    _validate_message_fields(body, correlation, attempt)
    _message_id(body, correlation, attempt)
    if not isinstance(body.get("model"), str) or not matches_model(model, body["model"], anthropic=True):
        raise provider_error("invalid_model", "chat_completion", correlation, attempt)
    finish = _finish(body, correlation, attempt)
    blocks = body.get("content")
    if not isinstance(blocks, list) or not blocks or len(blocks) > 128:
        raise _bad(correlation, attempt)
    texts, calls, ids = [], [], set()
    for block in blocks:
        if not isinstance(block, Mapping):
            raise _bad(correlation, attempt)
        if block.get("type") == "text":
            if set(block) - {"type", "text", "citations"} or not isinstance(block.get("text"), str) or not _empty_citations(block):
                raise _bad(correlation, attempt)
            texts.append(block["text"])
        elif block.get("type") == "tool_use":
            if (set(block) - {"type", "id", "name", "input"} or not isinstance(block.get("input"), dict)
                or not isinstance(block.get("id"), str) or block.get("id") in ids):
                raise _bad(correlation, attempt)
            try:
                args = json.dumps(block["input"], allow_nan=False, separators=(",", ":"))
                ids.add(block.get("id"))
            except (TypeError, ValueError, RecursionError):
                raise _bad(correlation, attempt) from None
            calls.append({"id": block.get("id"), "type": "function",
                          "function": {"name": block.get("name"), "arguments": args}})
        else:
            raise _bad(correlation, attempt)
    tools = _extract_tool_calls(calls or None, "chat_completion", correlation, attempt)
    if (finish == "tool_calls") != bool(tools) and finish != "length":
        raise _bad(correlation, attempt)
    try:
        return ChatCompletionResult(model=body["model"], content="".join(texts), tool_calls=tools,
                                    finish_reason=finish, correlation_id=correlation,
                                    usage=_usage(body.get("usage"), correlation, attempt))
    except ValidationError:
        raise _bad(correlation, attempt) from None


def _message_id(body: Mapping, correlation: str, attempt: int) -> None:
    value = body.get("id")
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _bad(correlation, attempt)


def _validate_message_fields(body: Mapping, correlation: str, attempt: int) -> None:
    required = {"id", "type", "role", "model", "content", "stop_reason", "stop_sequence", "usage"}
    if not required <= set(body) or set(body) - required - {"stop_details", "container"}:
        raise _bad(correlation, attempt)
    # Preserve refusal-sensitive metadata until the boundary rejects it. Never
    # drop an unsupported safety field and manufacture a successful result.
    if body.get("stop_details") is not None:
        raise _bad(correlation, attempt)
    container = body.get("container")
    if container is not None:
        if (not isinstance(container, Mapping) or set(container) != {"id", "expires_at"}
            or not isinstance(container["id"], str) or not container["id"].strip()
            or len(container["id"]) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in container["id"])
            or not _native_datetime(container["expires_at"])):
            raise _bad(correlation, attempt)


class AnthropicMessagesClient(OpenAICompatibleClient):
    """Native Anthropic chat with explicitly independent OpenAI embeddings."""

    provider_kind = "anthropic"

    def _prepare_operation(self, operation: ProviderOperation, requested_correlation_id: str | None) -> str:
        correlation = super()._prepare_operation(operation, requested_correlation_id)
        if self.config.provider_kind != "anthropic":
            raise provider_error("invalid_configuration", operation, correlation, 0)
        if operation == "embeddings" and not self.config.embedding_provider_kind:
            raise provider_error("invalid_configuration", operation, correlation, 0)
        return correlation

    def _request_headers(self, operation: ProviderOperation, correlation_id: str) -> dict[str, str]:
        if operation == "embeddings":
            return super()._request_headers(operation, correlation_id)
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "X-Correlation-ID": correlation_id, "anthropic-version": self.config.anthropic_version}
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
        return inject_w3c_trace_headers(headers)

    async def _health_request(self, correlation_id: str, model: str) -> bool:
        deadline = asyncio.get_running_loop().time() + _request_timeout_seconds(self.config.timeout)
        async with self._response_context(
            "GET", f"{self.config.base_url.rstrip('/')}/models/{quote(model, safe='')}",
            headers=self._request_headers("chat_completion", correlation_id), deadline=deadline,
        ) as response:
            raw = await await_io(_read_bounded_response(response), deadline)
            status = response.status_code
        if status != 200 or raw is None:
            return False
        body = _loads_json(raw)
        # The native model endpoint resolves aliases to a canonical model ID.
        if not isinstance(body, Mapping) or "error" in body or body.get("type") != "model":
            return False
        _message_id(body, correlation_id, 1)
        return _model_metadata(body) and matches_model(model, body["id"], anthropic=True)

    def _payload(self, model_or_messages, messages, temperature, response_format, tools, model, correlation):
        if model is not None:
            if model_or_messages is not None:
                if messages is None and not isinstance(model_or_messages, str):
                    messages = model_or_messages
                else:
                    raise provider_error("invalid_model", "chat_completion", correlation, 0)
            selected = model
        elif messages is None and model_or_messages is not None and not isinstance(model_or_messages, str):
            messages, selected = model_or_messages, None
        else:
            selected = model_or_messages
        selected = _validate_model(self.config.chat_model if selected is None else selected, "chat_completion", correlation)
        # The shared message DTO only supports text history. Reject unsupported
        # fields, tool results, images and late system turns instead of dropping.
        if isinstance(messages, Sequence):
            for message in messages:
                if isinstance(message, Mapping) and set(message) != {"role", "content"}:
                    raise _bad(correlation)
        serialized = _serialize_messages(messages, "chat_completion", correlation)
        system, turns = [], []
        for message in serialized:
            if message["role"] == "system":
                if turns:
                    raise _bad(correlation)
                system.append({"type": "text", "text": message["content"]})
            else:
                turns.append(message)
        if not turns or turns[0]["role"] != "user":
            raise _bad(correlation)
        payload = {"model": selected, "messages": turns, "max_tokens": self.config.max_output_tokens}
        value = _validate_temperature(None if temperature is USE_DEFAULT_TEMPERATURE else temperature, "chat_completion", correlation)
        if value is not None:
            if not 0 <= value <= 1:
                raise _bad(correlation)
            # Models released after Opus 4.6 accept only the compatibility
            # value 1.0. Keep custom sampling on the known older families.
            older = re.match(r"^claude-(?:[23](?:-|\.)|(?:sonnet|opus)-4(?:$|-(?:202[0-9]{5}$|(?:0|1|5)(?:-|$)))|opus-4-6(?:-|$)|haiku-4-5(?:-|$))", selected)
            if not older and value != 1:
                raise provider_error("invalid_configuration", "chat_completion", correlation, 0)
            payload["temperature"] = value
        # The generic JSON-object contract has no schema. Native constrained
        # JSON requires closed properties, so request JSON explicitly and
        # validate the full object before delivering a terminal chunk.
        fmt = {"type": "text"} if response_format is None else response_format
        if not isinstance(fmt, Mapping) or set(fmt) != {"type"} or not isinstance(fmt["type"], str) or fmt["type"] not in {"text", "json_object"}:
            raise _bad(correlation)
        if fmt["type"] == "json_object":
            system.append({"type": "text", "text": "Return only a valid JSON object, without Markdown or surrounding text."})
        if tools is not None:
            normalized_tools = _serialize_tools(tools, "chat_completion", correlation)
            for tool in tools:
                if (not isinstance(tool, Mapping) or set(tool) != {"type", "function"}
                    or not isinstance(tool.get("function"), Mapping)
                    or set(tool["function"]) - {"name", "description", "parameters", "strict"}):
                    raise _bad(correlation)
            converted = []
            names = set()
            for tool in normalized_tools:
                function = tool["function"]
                if function["parameters"].get("type") != "object" or function["name"] in names:
                    raise _bad(correlation)
                names.add(function["name"])
                converted.append({"name": function["name"], "input_schema": function["parameters"],
                                  **{key: function[key] for key in ("description", "strict") if key in function}})
            payload["tools"] = converted
        if system:
            payload["system"] = system
        try:
            if len(json.dumps(payload, allow_nan=False).encode()) > MAX_RESPONSE_BYTES:
                raise _bad(correlation)
        except (TypeError, ValueError, RecursionError):
            raise _bad(correlation) from None
        return payload, fmt

    async def chat_completion(
        self, model_or_messages: str | Sequence[MessageInput] | None = None,
        messages: Sequence[MessageInput] | None = None, temperature: Temperature = USE_DEFAULT_TEMPERATURE,
        response_format: Mapping[str, object] | None = None,
        tools: Sequence[Mapping[str, object]] | None = None, *, model: str | None = None,
        correlation_id: str | None = None,
    ) -> ChatCompletionResult:
        correlation = self._prepare_operation("chat_completion", correlation_id)
        payload, fmt = self._payload(model_or_messages, messages, temperature, response_format, tools, model, correlation)

        async def request(attempt):
            body = await self._post_json("chat_completion", "/messages", payload, correlation, attempt)
            result = _result(body, payload["model"], correlation, attempt)
            return _validate_response_format_result(result, fmt, "chat_completion", correlation, attempt)

        return await self._with_retry("chat_completion", correlation, request)

    def chat_completion_stream(
        self, model_or_messages: str | Sequence[MessageInput] | None = None,
        messages: Sequence[MessageInput] | None = None, temperature: Temperature = USE_DEFAULT_TEMPERATURE,
        response_format: Mapping[str, object] | None = None,
        tools: Sequence[Mapping[str, object]] | None = None, *, model: str | None = None,
        correlation_id: str | None = None,
    ) -> AsyncIterator[ChatCompletionChunk]:
        return self._messages_stream(model_or_messages, messages, temperature, response_format, tools,
                                     model=model, correlation_id=correlation_id)

    async def _messages_stream(self, model_or_messages, messages, temperature, response_format, tools,
                               *, model, correlation_id) -> AsyncIterator[ChatCompletionChunk]:
        correlation = self._prepare_operation("chat_completion", correlation_id)
        payload, fmt = self._payload(model_or_messages, messages, temperature, response_format, tools, model, correlation)
        payload["stream"] = True
        for attempt in range(1, self.config.max_attempts + 1):
            emitted = False
            state = _MessageStream(payload["model"], correlation, attempt)
            deadline = asyncio.get_running_loop().time() + _request_timeout_seconds(self.config.timeout)
            try:
                headers = self._request_headers("chat_completion", correlation)
                headers["Accept"] = "text/event-stream"
                async with self._response_context(
                    "POST", f"{self.config.base_url.rstrip('/')}/messages",
                    headers=headers, payload=payload, deadline=deadline,
                ) as response:
                    if not 200 <= response.status_code < 300:
                        raw = await await_io(_read_bounded_response(response), deadline)
                        raise _classify_http_status(response.status_code, raw or b"", "chat_completion", correlation, attempt)
                    async with aclosing(_events(response, correlation, attempt)) as source:
                        while True:
                            if asyncio.get_running_loop().time() >= deadline:
                                raise TimeoutError
                            try:
                                event = await await_io(anext(source), deadline)
                            except StopAsyncIteration:
                                break
                            chunk = state.accept(event)
                            if chunk is not None:
                                emitted = True
                                # Caller suspension is outside the cumulative
                                # I/O budget; native ping/read events still spend it.
                                paused_at = asyncio.get_running_loop().time()
                                try:
                                    yield chunk
                                finally:
                                    deadline += asyncio.get_running_loop().time() - paused_at
                    result = state.finish()
                    _validate_response_format_result(result, fmt, "chat_completion", correlation, attempt)
                yield ChatCompletionChunk(model=result.model, correlation_id=correlation,
                                          finish_reason=result.finish_reason, usage=result.usage)
                return
            except asyncio.CancelledError:
                raise
            except ProviderError as exc:
                error = ProviderError(exc.code, "chat_completion", correlation, attempt, exc.retryable, exc.status)
            except httpx.InvalidURL:
                error = provider_error("invalid_configuration", "chat_completion", correlation, attempt)
            except Exception as exc:
                error = _classify_transport_error(exc, "chat_completion", correlation, attempt)
            if emitted or not error.retryable or attempt == self.config.max_attempts:
                raise error from None
            await self._retry_sleep("chat_completion", correlation, attempt)


async def _events(response, correlation, attempt):
    name, data = None, []
    async with aclosing(_iter_bounded_sse_lines(response, "chat_completion", correlation, attempt)) as lines:
        async for line in lines:
            if line.startswith(":"):
                continue
            if not line:
                if name is None and not data:
                    continue
                if not name or not data:
                    raise _bad(correlation, attempt)
                try:
                    event = _loads_json("\n".join(data))
                except (ValueError, TypeError, RecursionError):
                    raise provider_error("invalid_json", "chat_completion", correlation, attempt) from None
                if not isinstance(event, dict) or event.get("type") != name:
                    raise _bad(correlation, attempt)
                yield event
                name, data = None, []
            elif line.startswith("event:") and name is None:
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].removeprefix(" "))
            else:
                raise _bad(correlation, attempt)
    if name is not None or data:
        raise _bad(correlation, attempt)


class _MessageStream:
    def __init__(self, model, correlation, attempt):
        self.model, self.correlation, self.attempt = model, correlation, attempt
        self.body = None
        self.blocks = []
        self.active = None
        self.arguments = ""
        self.tool_count = 0
        self.saw_delta = self.stopped = False

    def chunk(self, text="", tools=None, usage=None):
        return ChatCompletionChunk(model=self.model, correlation_id=self.correlation,
                                   delta=text, tool_calls=tools, usage=usage)

    def accept(self, event):
        kind = event["type"]
        correlation, attempt = self.correlation, self.attempt
        fields = {"error": {"type", "error"}, "ping": {"type"}, "message_start": {"type", "message"},
                  "content_block_start": {"type", "index", "content_block"},
                  "content_block_delta": {"type", "index", "delta"},
                  "content_block_stop": {"type", "index"},
                  "message_delta": {"type", "delta", "usage"}, "message_stop": {"type"}}
        if not isinstance(kind, str) or kind not in fields or set(event) != fields[kind]:
            raise _bad(correlation, attempt)
        if self.stopped:
            raise _bad(correlation, attempt)
        if kind == "error":
            detail = event.get("error")
            code = {"overloaded_error": "server_error", "api_error": "server_error",
                    "rate_limit_error": "rate_limit"}.get(detail.get("type") if isinstance(detail, Mapping) else None, "http_error")
            raise provider_error(code, "chat_completion", correlation, attempt)
        if kind == "ping":
            return None
        if kind == "message_start":
            body = event.get("message")
            if (self.body is not None or not isinstance(body, dict) or body.get("type") != "message"
                or body.get("role") != "assistant" or body.get("content") != []
                or body.get("stop_reason") is not None or body.get("stop_sequence") is not None):
                raise _bad(correlation, attempt)
            _validate_message_fields(body, correlation, attempt)
            if not isinstance(body.get("model"), str) or not matches_model(self.model, body["model"], anthropic=True):
                raise provider_error("invalid_model", "chat_completion", correlation, attempt)
            self.model = body["model"]
            _message_id(body, correlation, attempt)
            self.body = dict(body)
            self.body["content"] = self.blocks
            return self.chunk(usage=_usage(body.get("usage"), correlation, attempt))
        if self.body is None:
            raise _bad(correlation, attempt)
        if kind.startswith("content_block_"):
            index = event.get("index")
            if type(index) is not int or not 0 <= index < 128 or self.saw_delta:
                raise _bad(correlation, attempt)
            if kind == "content_block_start":
                block = event.get("content_block")
                if self.active is not None or index != len(self.blocks) or not isinstance(block, dict):
                    raise _bad(correlation, attempt)
                self.active = index
                self.blocks.append(dict(block))
                if block.get("type") == "text":
                    if set(block) - {"type", "text", "citations"} or not isinstance(block.get("text"), str) or not _empty_citations(block):
                        raise _bad(correlation, attempt)
                    return self.chunk(text=block["text"]) if block["text"] else None
                if (set(block) - {"type", "id", "name", "input"} or block.get("type") != "tool_use"
                    or block.get("input") != {} or self.tool_count >= MAX_TOOL_CALL_COUNT):
                    raise _bad(correlation, attempt)
                self.arguments = ""
                self.tool_count += 1
                calls = _extract_tool_call_deltas([{"index": self.tool_count - 1, "id": block.get("id"),
                    "type": "function", "function": {"name": block.get("name"), "arguments": ""}}],
                    "chat_completion", correlation, attempt)
                if not block.get("id") or not block.get("name"):
                    raise _bad(correlation, attempt)
                return self.chunk(tools=calls)
            if index != self.active:
                raise _bad(correlation, attempt)
            block = self.blocks[index]
            if kind == "content_block_delta":
                delta = event.get("delta")
                if not isinstance(delta, dict):
                    raise _bad(correlation, attempt)
                if block["type"] == "text" and set(delta) == {"type", "text"} and delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                    block["text"] += delta["text"]
                    return self.chunk(text=delta["text"]) if delta["text"] else None
                if block["type"] == "tool_use" and set(delta) == {"type", "partial_json"} and delta.get("type") == "input_json_delta" and isinstance(delta.get("partial_json"), str):
                    self.arguments += delta["partial_json"]
                    calls = _extract_tool_call_deltas([{"index": self.tool_count - 1,
                        "function": {"arguments": delta["partial_json"]}}], "chat_completion", correlation, attempt)
                    return self.chunk(tools=calls)
                raise _bad(correlation, attempt)
            if kind == "content_block_stop":
                self.active = None
                if block["type"] == "tool_use":
                    try:
                        block["input"] = _loads_json(self.arguments or "{}")
                    except (ValueError, TypeError, RecursionError):
                        raise provider_error("invalid_json", "chat_completion", correlation, attempt) from None
                    if not isinstance(block["input"], dict):
                        raise _bad(correlation, attempt)
                    if not self.arguments:
                        return self.chunk(tools=_extract_tool_call_deltas([{"index": self.tool_count - 1,
                            "function": {"arguments": "{}"}}], "chat_completion", correlation, attempt))
                return None
            raise _bad(correlation, attempt)
        if kind == "message_delta":
            delta, usage = event.get("delta"), event.get("usage")
            if self.active is not None or not isinstance(delta, dict) or not isinstance(usage, dict):
                raise _bad(correlation, attempt)
            if set(delta) - {"stop_reason", "stop_sequence", "stop_details"}:
                raise _bad(correlation, attempt)
            if "output_tokens" not in usage:
                raise _bad(correlation, attempt)
            merged_usage = _cumulative_usage(self.body["usage"], usage, correlation, attempt)
            new_usage = _usage(merged_usage, correlation, attempt)
            previous = _usage(self.body["usage"], correlation, attempt)
            if new_usage.prompt_tokens < previous.prompt_tokens or new_usage.completion_tokens < previous.completion_tokens:
                raise _bad(correlation, attempt)
            if self.body.get("stop_reason") is not None and any(key in delta and self.body.get(key) != delta[key] for key in ("stop_reason", "stop_sequence", "stop_details")):
                raise _bad(correlation, attempt)
            self.body.update(delta)
            if self.body.get("stop_details") is not None:
                raise _bad(correlation, attempt)
            if self.body.get("stop_reason") is not None:
                _finish(self.body, correlation, attempt)
            self.body["usage"] = merged_usage
            self.saw_delta = True
            return self.chunk(usage=new_usage)
        if kind == "message_stop" and self.active is None and self.saw_delta:
            self.stopped = True
            return None
        raise _bad(correlation, attempt)

    def finish(self) -> ChatCompletionResult:
        if not self.stopped:
            raise _bad(self.correlation, self.attempt)
        return _result(self.body, self.model, self.correlation, self.attempt)


__all__ = ["AnthropicMessagesClient"]
