from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from rick_contracts.providers import ChatCompletionResult, EmbeddingResult
from rick_providers import (
    DeterministicProvider,
    OpenAICompatibleClient,
    ProviderConfig,
    ProviderConfigurationError,
    ProviderError,
    create_provider,
)


RAW_SECRET = "provider-contract-secret"
RAW_STACK = "Error: synthetic provider stack"
CORRELATION = "contract-correlation-001"


def _config(**overrides: object) -> ProviderConfig:
    values: dict[str, object] = {
        "base_url": "https://provider.example/v1",
        "api_key": "test-only-key",
        "chat_model": "chat-test-model",
        "embedding_model": "embedding-test-model",
        "embedding_dimensions": 3,
        "timeout": 0.05,
        "max_attempts": 3,
        "retry_base_delay": 0.01,
        "max_backoff_delay": 1.0,
        "environment": "test",
    }
    values.update(overrides)
    return ProviderConfig(**values)  # type: ignore[arg-type]


def _chat_payload(model: str = "chat-test-model", content: str = "provider success") -> dict[str, object]:
    return {
        "id": "chat-contract",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    }


def _embedding_payload(vector: list[object] | None = None) -> dict[str, object]:
    return {
        "object": "list",
        "model": "embedding-test-model",
        "data": [{"object": "embedding", "index": 0, "embedding": vector or [0.1, 0.2, 0.3]}],
    }


def _response(request: httpx.Request, status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body, request=request)


async def _close(provider: OpenAICompatibleClient) -> None:
    await provider.aclose()


@pytest.mark.asyncio
async def test_chat_and_embedding_use_one_typed_http_boundary_and_propagate_correlation() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/chat/completions"):
            return _response(request, 200, _chat_payload())
        assert request.url.path.endswith("/embeddings")
        return _response(request, 200, _embedding_payload())

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        chat = await provider.chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            correlation_id=CORRELATION,
        )
        embedding = await provider.get_embedding("hello", correlation_id=CORRELATION)
    finally:
        await _close(provider)

    assert isinstance(chat, ChatCompletionResult)
    assert chat.model == "chat-test-model"
    assert chat.content == "provider success"
    assert chat.correlation_id == CORRELATION
    assert chat.usage is not None
    assert chat.usage.model_dump() == {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
    assert isinstance(embedding, EmbeddingResult)
    assert embedding.vector == [0.1, 0.2, 0.3]
    assert embedding.dimensions == 3
    assert embedding.correlation_id == CORRELATION
    assert [request.url.path for request in requests] == ["/v1/chat/completions", "/v1/embeddings"]
    assert all(request.headers["x-correlation-id"] == CORRELATION for request in requests)
    assert all(request.headers["authorization"] == "Bearer test-only-key" for request in requests)
    assert json.loads(requests[0].content)["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_health_check_probes_models_with_auth_and_validates_configured_model() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/v1/models"
        return _response(
            request,
            200,
            {"object": "list", "data": [{"id": "chat-test-model"}]},
        )

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        assert await provider.health_check() is True
    finally:
        await _close(provider)

    assert len(requests) == 1
    assert requests[0].headers["x-correlation-id"]
    assert requests[0].headers["authorization"] == "Bearer test-only-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body"),
    [
        (401, {"error": {"code": "unauthorized"}}),
        (200, {"object": "list", "data": [{"id": "other-model"}]}),
        (200, []),
    ],
)
async def test_health_check_fails_closed_for_unhealthy_or_wrong_model_responses(
    status: int,
    body: object,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, status, body)

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        assert await provider.health_check() is False
    finally:
        await _close(provider)

    assert len(requests) == 1


@pytest.mark.asyncio
async def test_health_check_has_an_explicit_timeout_for_an_unresponsive_transport() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return _response(request, 200, {"data": [{"id": "chat-test-model"}]})

    provider = OpenAICompatibleClient(
        _config(timeout=0.01),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await asyncio.wait_for(provider.health_check(), timeout=0.2) is False
    finally:
        await _close(provider)


@pytest.mark.asyncio
async def test_streaming_contract_emits_typed_deltas_and_terminal_finish_reason() -> None:
    requests: list[httpx.Request] = []
    body = (
        b'data: {"model":"chat-test-model","choices":[{"delta":{"content":"stream "},"finish_reason":null}]}\n\n'
        b'data: {"model":"chat-test-model","choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
        b'data: {"model":"chat-test-model","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        chunks = [
            chunk
            async for chunk in provider.chat_completion_stream(
                messages=[{"role": "user", "content": "stream"}],
                correlation_id=CORRELATION,
            )
        ]
    finally:
        await _close(provider)

    assert [chunk.delta for chunk in chunks] == ["stream ", "ok", ""]
    assert chunks[-1].finish_reason == "stop"
    assert requests[0].method == "POST"
    assert json.loads(requests[0].content)["stream"] is True


@pytest.mark.asyncio
async def test_streaming_json_content_can_be_reassembled_as_an_object() -> None:
    body = (
        b'data: {"model":"chat-test-model","choices":[{"delta":{"content":"{\\"status\\":"},"finish_reason":null}]}\n\n'
        b'data: {"model":"chat-test-model","choices":[{"delta":{"content":"\\"ok\\"}"},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        chunks = [
            chunk
            async for chunk in provider.chat_completion_stream(
                messages=[{"role": "user", "content": "return JSON"}],
                response_format={"type": "json_object"},
            )
        ]
    finally:
        await _close(provider)

    assert json.loads("".join(chunk.delta for chunk in chunks)) == {"status": "ok"}
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_function_tools_are_serialized_and_typed_calls_are_returned() -> None:
    requests: list[httpx.Request] = []
    tool = {
        "type": "function",
        "function": {
            "name": "report_status",
            "description": "Report a bounded status.",
            "parameters": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["tools"] == [tool]
        return _response(
            request,
            200,
            {
                "model": "chat-test-model",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-status",
                                    "type": "function",
                                    "function": {
                                        "name": "report_status",
                                        "arguments": '{"status":"ok"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        result = await provider.chat_completion(
            messages=[{"role": "user", "content": "status"}],
            tools=[tool],
            correlation_id=CORRELATION,
        )
    finally:
        await _close(provider)

    assert len(requests) == 1
    assert result.content == ""
    assert result.tool_calls is not None
    assert result.tool_calls[0].id == "call-status"
    assert result.tool_calls[0].function.name == "report_status"
    assert json.loads(result.tool_calls[0].function.arguments) == {"status": "ok"}


@pytest.mark.asyncio
async def test_streaming_tool_call_deltas_are_typed_without_parsing_partial_arguments() -> None:
    events = [
        {
            "model": "chat-test-model",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-status",
                                "type": "function",
                                "function": {"name": "report_status", "arguments": '{"sta'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "model": "chat-test-model",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": 'tus":"ok"}'}}
                        ]
                    },
                    "finish_reason": "stop",
                }
            ],
        },
    ]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode() + b"data: [DONE]\n\n"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        chunks = [
            chunk
            async for chunk in provider.chat_completion_stream(
                messages=[{"role": "user", "content": "status"}],
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "report_status", "parameters": {"type": "object"}},
                    }
                ],
            )
        ]
    finally:
        await _close(provider)

    assert chunks[0].tool_calls is not None
    assert chunks[0].tool_calls[0].function.arguments == '{"sta'
    assert chunks[1].tool_calls is not None
    assert chunks[1].tool_calls[0].function.arguments == 'tus":"ok"}'
    assert chunks[1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_invalid_function_tool_is_rejected_before_network() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(request, 200, _chat_payload())

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(
                messages=[{"role": "user", "content": "status"}],
                tools=[{"type": "function", "function": {"name": "bad\nname"}}],
            )
    finally:
        await _close(provider)

    assert caught.value.code == "malformed_response"
    assert caught.value.attempts == 0
    assert calls == 0


@pytest.mark.asyncio
async def test_streaming_cancellation_propagates_without_retry_or_conversion() -> None:
    started = asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.Event().wait()
        return httpx.Response(200, content=b"", request=request)

    provider = OpenAICompatibleClient(_config(max_attempts=3), transport=httpx.MockTransport(handler))

    async def consume() -> None:
        async for _chunk in provider.chat_completion_stream(
            messages=[{"role": "user", "content": "cancel"}],
            correlation_id=CORRELATION,
        ):
            pass

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await _close(provider)

    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (httpx.ReadTimeout("synthetic timeout"), "timeout"),
        (httpx.ConnectError("synthetic unavailable"), "unavailable"),
    ],
)
async def test_transient_transport_errors_retry_with_bounded_attempts_and_stable_correlation(
    exception: Exception,
    expected_code: str,
) -> None:
    requests: list[httpx.Request] = []
    delays: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise exception

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    provider = OpenAICompatibleClient(
        _config(max_attempts=3),
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
    )
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion("chat-test-model", [{"role": "user", "content": "hello"}])
    finally:
        await _close(provider)

    error = caught.value
    assert error.code == expected_code
    assert error.operation == "chat_completion"
    assert error.attempts == 3
    assert error.retryable is True
    assert error.status is None
    assert len(requests) == 3
    assert [request.headers["x-correlation-id"] for request in requests] == [error.correlation_id] * 3
    assert delays == [0.01, 0.02]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_code"),
    [(429, "rate_limit"), (500, "server_error"), (503, "server_error")],
)
async def test_transient_http_statuses_retry_and_preserve_status(
    status: int,
    expected_code: str,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(
            request,
            status,
            {"error": {"code": "synthetic", "message": f"{RAW_SECRET} {RAW_STACK}"}},
        )

    provider = OpenAICompatibleClient(
        _config(max_attempts=2),
        transport=httpx.MockTransport(handler),
        sleep=lambda _delay: None,
    )
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.get_embedding("hello")
    finally:
        await _close(provider)

    error = caught.value
    assert error.code == expected_code
    assert error.status == status
    assert error.attempts == 2
    assert len(requests) == 2
    assert len({request.headers["x-correlation-id"] for request in requests}) == 1


@pytest.mark.asyncio
async def test_non_transient_http_error_is_not_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(request, 400, {"error": {"code": "bad_request"}})

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        await _close(provider)

    assert caught.value.code == "http_error"
    assert caught.value.status == 400
    assert caught.value.attempts == 1
    assert caught.value.retryable is False
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        ("not-json", "invalid_json"),
        ([], "malformed_response"),
        ({"choices": "not-a-list", "model": "chat-test-model"}, "malformed_response"),
        ({"model": "chat-test-model"}, "missing_field"),
        ({"model": "chat-test-model", "choices": []}, "missing_field"),
        ({"model": "chat-test-model", "choices": [{"message": {}}]}, "missing_field"),
        (
            {"model": "chat-test-model", "choices": [{"message": {"content": 42}}]},
            "missing_field",
        ),
        (
            {"model": "chat-test-model", "choices": [{"message": {"content": "ok"}}], "usage": {"total": "3"}},
            "malformed_response",
        ),
        (
            {
                "model": "chat-test-model",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "bad"}],
            },
            "malformed_response",
        ),
    ],
)
async def test_chat_response_validation_is_typed_and_not_retried(body: object, expected_code: str) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if body == "not-json":
            return httpx.Response(200, content=b"not-json", request=request)
        return _response(request, 200, body)

    provider = OpenAICompatibleClient(_config(max_attempts=3), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        await _close(provider)

    assert caught.value.code == expected_code
    assert caught.value.attempts == 1
    assert caught.value.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        ('{"status":"ok"}', None),
        ("not-json", "invalid_json"),
        ("[]", "malformed_response"),
        ("NaN", "invalid_json"),
    ],
)
async def test_json_object_response_format_is_validated_at_the_provider_boundary(
    content: str,
    expected_code: str | None,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(request, 200, _chat_payload(content=content))

    provider = OpenAICompatibleClient(_config(max_attempts=3), transport=httpx.MockTransport(handler))
    try:
        if expected_code is None:
            result = await provider.chat_completion(
                messages=[{"role": "user", "content": "return JSON"}],
                response_format={"type": "json_object"},
            )
            assert result.content == content
        else:
            with pytest.raises(ProviderError) as caught:
                await provider.chat_completion(
                    messages=[{"role": "user", "content": "return JSON"}],
                    response_format={"type": "json_object"},
                )
            assert caught.value.code == expected_code
            assert caught.value.attempts == 1
            assert caught.value.retryable is False
    finally:
        await _close(provider)

    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        ({}, "missing_field"),
        ({"data": "not-a-list", "model": "embedding-test-model"}, "malformed_response"),
        ({"data": [], "model": "embedding-test-model"}, "missing_field"),
        ({"data": [{}], "model": "embedding-test-model"}, "missing_field"),
        ({"data": [{"embedding": "not-a-vector"}], "model": "embedding-test-model"}, "malformed_response"),
        ({"data": [{"embedding": [0.1, "bad", 0.3]}], "model": "embedding-test-model"}, "malformed_response"),
        ({"data": [{"embedding": [0.1, 0.2]}], "model": "embedding-test-model"}, "embedding_dimension_mismatch"),
        ({"data": [{"embedding": [0.1, 0.2, 0.3]}]}, "missing_field"),
    ],
)
async def test_embedding_response_validation_checks_finite_values_and_exact_dimensions(
    body: object,
    expected_code: str,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(request, 200, body)

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.get_embedding("hello")
    finally:
        await _close(provider)

    assert caught.value.code == expected_code
    assert caught.value.attempts == 1
    assert calls == 1


@pytest.mark.asyncio
async def test_non_json_nan_is_rejected_before_embedding_validation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"model":"embedding-test-model","data":[{"embedding":[NaN,0.2,0.3]}]}',
            request=request,
        )

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.get_embedding("hello")
    finally:
        await _close(provider)
    assert caught.value.code == "invalid_json"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "expected_code"),
    [
        (404, {"error": {"code": "model_not_found"}}, "model_not_found"),
        (404, {"error": {"message": "The requested model does not exist"}}, "model_not_found"),
        (400, {"error": {"code": "invalid_model"}}, "invalid_model"),
    ],
)
async def test_model_http_failures_are_classified_without_retry(
    status: int,
    body: object,
    expected_code: str,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(request, status, body)

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        await _close(provider)
    assert caught.value.code == expected_code
    assert caught.value.status == status
    assert caught.value.attempts == 1
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_model", ["", "   ", 123, "x" * 257])
async def test_invalid_model_fails_before_network_with_zero_attempts(bad_model: object) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(request, 200, _chat_payload())

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(bad_model, [{"role": "user", "content": "hello"}])  # type: ignore[arg-type]
    finally:
        await _close(provider)
    assert caught.value.code == "invalid_model"
    assert caught.value.attempts == 0
    assert calls == 0


@pytest.mark.asyncio
async def test_invalid_configuration_is_safe_and_does_not_open_a_transport() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(request, 200, _chat_payload())

    provider = OpenAICompatibleClient(
        _config(base_url="not a URL"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(messages=[{"role": "user", "content": "hello"}])
    finally:
        await _close(provider)
    assert caught.value.code == "invalid_configuration"
    assert caught.value.attempts == 0
    assert calls == 0


@pytest.mark.asyncio
async def test_cancellation_is_propagated_without_retry_or_conversion() -> None:
    started = asyncio.Event()
    calls = 0
    sleep_calls: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.Event().wait()
        return _response(request, 200, _chat_payload())

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    provider = OpenAICompatibleClient(
        _config(max_attempts=3),
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
    )
    task = asyncio.create_task(
        provider.chat_completion(messages=[{"role": "user", "content": "hello"}])
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await _close(provider)
    assert calls == 1
    assert sleep_calls == []


@pytest.mark.asyncio
async def test_cancellation_during_backoff_is_not_retried_or_wrapped() -> None:
    first_response = asyncio.Event()
    release_sleep = asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        first_response.set()
        return _response(request, 503, {"error": {"code": "busy"}})

    async def blocking_sleep(_delay: float) -> None:
        await release_sleep.wait()

    provider = OpenAICompatibleClient(
        _config(max_attempts=3),
        transport=httpx.MockTransport(handler),
        sleep=blocking_sleep,
    )
    task = asyncio.create_task(
        provider.get_embedding("hello", correlation_id=CORRELATION)
    )
    try:
        await asyncio.wait_for(first_response.wait(), timeout=1)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release_sleep.set()
        await _close(provider)
    assert calls == 1


@pytest.mark.asyncio
async def test_provider_error_redacts_body_url_key_and_cause_from_all_public_forms() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            request,
            400,
            {"error": {"message": f"{RAW_SECRET} {RAW_STACK}"}},
        )

    provider = OpenAICompatibleClient(
        _config(base_url=f"https://{RAW_SECRET}.example/v1", api_key=RAW_SECRET),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.chat_completion(
                messages=[{"role": "user", "content": RAW_SECRET}],
                correlation_id=CORRELATION,
            )
    finally:
        await _close(provider)

    error = caught.value
    serialized = json.dumps(error.to_dict()) + error.to_json()
    public = f"{error!s} {error!r} {serialized}"
    assert RAW_SECRET not in public
    assert RAW_STACK not in public
    assert "Bearer " not in public
    assert "cause" not in public.lower()
    assert "url" not in public.lower()
    assert "body" not in public.lower()
    assert "stack" not in public.lower()
    assert error.to_dto().correlation_id == CORRELATION
    assert error.to_dict()["code"] == "http_error"


@pytest.mark.asyncio
async def test_oversized_success_body_is_malformed_and_not_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"x" * 1_000_001, request=request)

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.get_embedding("hello")
    finally:
        await _close(provider)
    assert caught.value.code == "malformed_response"
    assert caught.value.status == 200
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["chat", "embedding"])
async def test_success_response_model_must_match_requested_model(operation: str) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if operation == "chat":
            return _response(request, 200, _chat_payload(model="unexpected-model"))
        body = _embedding_payload()
        body["model"] = "unexpected-model"
        return _response(request, 200, body)

    provider = OpenAICompatibleClient(_config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as caught:
            if operation == "chat":
                await provider.chat_completion(messages=[{"role": "user", "content": "hello"}])
            else:
                await provider.get_embedding("hello")
    finally:
        await _close(provider)

    assert caught.value.code == "invalid_model"
    assert caught.value.attempts == 1
    assert calls == 1


@pytest.mark.asyncio
async def test_deterministic_provider_is_stable_and_explicitly_non_production() -> None:
    provider = DeterministicProvider(embedding_dimensions=4, environment="dev")
    first = await provider.get_embedding("same", correlation_id=CORRELATION)
    second = await provider.get_embedding("same", correlation_id=CORRELATION)
    answer = await provider.chat_completion(messages=[{"role": "user", "content": "SOURCE source-1"}])

    assert provider.is_test_provider is True
    assert provider.non_production is True
    assert provider.production_safe is False
    assert first.vector == second.vector
    assert first.dimensions == 4
    assert first.correlation_id == CORRELATION
    assert answer.content.startswith("Deterministic provider response")
    assert answer.content.endswith("[cite:source-1]")
    assert answer.model == "gpt-4o-mini"


def test_deterministic_provider_and_factory_fail_closed_for_production() -> None:
    with pytest.raises(ProviderConfigurationError):
        DeterministicProvider(environment="production")
    with pytest.raises(ProviderConfigurationError):
        create_provider(
            ProviderConfig(
                base_url="http://deterministic.invalid",
                provider_kind="deterministic",
                environment="production",
            )
        )


def test_factory_defaults_to_live_boundary_even_in_test_environment() -> None:
    provider = create_provider(
        ProviderConfig(
            base_url="https://provider.example/v1",
            environment="test",
            provider_kind="openai",
        )
    )
    try:
        assert isinstance(provider, OpenAICompatibleClient)
        assert provider.is_test_provider is False
    finally:
        # No event loop is needed because no client was lazily opened.
        assert provider._client is None  # noqa: SLF001


def test_environment_and_direct_constructor_settings_are_supported() -> None:
    config = ProviderConfig.from_env(
        {
            "OPENAI_BASE_URL": "http://loopback.test/v1",
            "OPENAI_API_KEY": "env-key",
            "OPENAI_CHAT_MODEL": "env-chat",
            "OPENAI_EMBEDDING_MODEL": "env-embedding",
            "OPENAI_EMBEDDING_DIMENSIONS": "7",
            "OPENAI_TIMEOUT_MS": "125",
            "OPENAI_MAX_ATTEMPTS": "2",
            "OPENAI_RETRY_DELAY_MS": "4",
            "OPENAI_MAX_BACKOFF_MS": "9",
            "RICK_ENV": "dev",
            "RICK_PROVIDER": "openai",
        }
    )
    assert config.base_url == "http://loopback.test/v1"
    assert config.api_key == "env-key"
    assert config.chat_model == "env-chat"
    assert config.embedding_model == "env-embedding"
    assert config.embedding_dimensions == 7
    assert config.timeout == 0.125
    assert config.max_attempts == 2
    assert config.retry_base_delay == 0.004
    assert config.max_backoff_delay == 0.009

    direct = OpenAICompatibleClient(
        base_url="https://direct.example/v1",
        api_key="direct-key",
        chat_model="direct-chat",
        embedding_model="direct-embedding",
        embedding_dimensions=5,
        timeout_ms=100,
        max_attempts=1,
        retry_delay_seconds=0,
    )
    assert direct.config.base_url == "https://direct.example/v1"
    assert direct.config.embedding_dimensions == 5
    assert direct.config.timeout == 0.1
    assert direct.config.max_attempts == 1
    assert direct.config.retry_base_delay == 0


def test_invalid_environment_setting_is_safe() -> None:
    with pytest.raises(ProviderConfigurationError) as caught:
        ProviderConfig.from_env({"OPENAI_MAX_ATTEMPTS": "not-an-integer"})
    assert str(caught.value) == "Invalid provider configuration."
