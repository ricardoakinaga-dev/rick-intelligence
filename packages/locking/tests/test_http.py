"""HTTP protocol, bounded failure, and cancellation tests."""

import asyncio
import json

import httpx
import pytest

from rick_locking import (
    HttpLockerStore,
    LeaseError,
    LockerClient,
)


@pytest.mark.asyncio
async def test_locker_client_maps_payloads_and_owner_bound_handle() -> None:
    requests: list[tuple[str, dict[str, object], str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (request.url.path, json.loads(request.content), request.headers.get("x-correlation-id"))
        )
        field = {
            "/lock": "acquired",
            "/renew": "renewed",
            "/unlock": "deleted",
        }[request.url.path]
        return httpx.Response(200, json={"ok": True, field: True})

    transport = httpx.MockTransport(handler)
    async with LockerClient(
        "http://locker.test",
        transport=transport,
        owner_factory=lambda: "generated-owner",
    ) as client:
        handle = await client.acquire("lock-key", 1234, correlation_id="corr-123")
        assert handle is not None
        assert await handle.renew(2345, correlation_id="corr-renew") is True
        assert await handle.release(correlation_id="corr-release") is True

    assert [path for path, _, _ in requests] == ["/lock", "/renew", "/unlock"]
    assert requests[0][1] == {
        "lock_key": "lock-key",
        "lock_value": "generated-owner",
        "ttl_ms": 1234,
    }
    assert requests[1][1] == {
        "lock_key": "lock-key",
        "lock_value": "generated-owner",
        "ttl_ms": 2345,
    }
    assert requests[2][1] == {
        "lock_key": "lock-key",
        "lock_value": "generated-owner",
    }
    assert [correlation for _, _, correlation in requests] == [
        "corr-123",
        "corr-renew",
        "corr-release",
    ]


@pytest.mark.asyncio
async def test_http_contention_returns_false_or_none_without_release() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"ok": True, "acquired": False})

    async with LockerClient(
        "http://locker.test", transport=httpx.MockTransport(handler)
    ) as client:
        assert await client.acquire("k", 100) is None
    assert calls == ["/lock"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "invalid_request"),
        (408, "timeout"),
        (429, "unavailable"),
        (500, "unavailable"),
        (499, "cancelled"),
    ],
)
async def test_http_statuses_are_typed_without_body_leak(status: int, code: str) -> None:
    secret = "https://user:password@example.test/private"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=secret.encode())

    async with HttpLockerStore(
        "http://locker.test", transport=httpx.MockTransport(handler)
    ) as store:
        with pytest.raises(LeaseError) as caught:
            await store.acquire("k", "owner", 100, correlation_id="corr")
    error = caught.value
    assert error.code.value == code
    assert secret not in str(error)
    assert secret not in repr(error)
    assert secret not in json.dumps(error.as_dict())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [b"not-json", b"{}", b'{"ok": true, "acquired": "yes"}', b"[]"],
)
async def test_http_malformed_success_is_internal_error(content: bytes) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    async with HttpLockerStore(
        "http://locker.test", transport=httpx.MockTransport(handler)
    ) as store:
        with pytest.raises(LeaseError) as caught:
            await store.acquire("k", "owner", 100)
    assert caught.value.code.value == "internal_error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        b'{"ok":true,"acquired":true,"metadata":NaN}',
        b'{"ok":true,"acquired":false,"acquired":true}',
    ],
)
async def test_http_ambiguous_or_nonfinite_success_is_internal_error(content: bytes) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    async with HttpLockerStore(
        "http://locker.test", transport=httpx.MockTransport(handler)
    ) as store:
        with pytest.raises(LeaseError) as caught:
            await store.acquire("k", "owner", 100)
    assert caught.value.code.value == "internal_error"


@pytest.mark.asyncio
async def test_http_response_is_bounded_and_timeout_is_typed() -> None:
    async def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 100)

    async with HttpLockerStore(
        "http://locker.test",
        transport=httpx.MockTransport(oversized),
        max_response_bytes=32,
    ) as store:
        with pytest.raises(LeaseError) as caught:
            await store.acquire("k", "owner", 100)
    assert caught.value.code.value == "internal_error"

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(60)
        return httpx.Response(200, json={"ok": True, "acquired": True})

    async with HttpLockerStore(
        "http://locker.test", transport=httpx.MockTransport(slow), timeout=0.01
    ) as store:
        with pytest.raises(LeaseError) as caught:
            await store.acquire("k", "owner", 100)
    assert caught.value.code.value == "timeout"


@pytest.mark.asyncio
async def test_http_cancellation_propagates_and_does_not_leave_request_task() -> None:
    started = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(60)
        return httpx.Response(200, json={"ok": True, "acquired": True})

    store = HttpLockerStore(
        "http://locker.test", transport=httpx.MockTransport(slow), timeout=5
    )
    task = asyncio.create_task(store.acquire("k", "owner", 100))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await store.close()


@pytest.mark.asyncio
async def test_heartbeat_is_one_cancellable_owner_bound_task() -> None:
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        field = {"/lock": "acquired", "/renew": "renewed", "/unlock": "deleted"}[
            request.url.path
        ]
        return httpx.Response(200, json={"ok": True, field: True})

    async with LockerClient(
        "http://locker.test", transport=httpx.MockTransport(handler)
    ) as client:
        handle = await client.acquire("k", 100)
        assert handle is not None
        heartbeat = handle.start_heartbeat(interval_ms=5)
        await asyncio.sleep(0.02)
        await heartbeat.stop()
        assert heartbeat.running is False
        assert await handle.release() is True

    assert "/lock" in requests
    assert "/renew" in requests
    assert requests[-1] == "/unlock"
