"""Bounded async HTTP adapter for the preserved Locker protocol."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from rick_locking.client import LeaseClient, OwnerFactory
from rick_locking.errors import LeaseError, LeaseOperation
from rick_locking.validation import (
    MAX_RESPONSE_BYTES,
    correlation_id_for,
    validate_base_url,
    validate_key,
    validate_owner,
    validate_response_limit,
    validate_timeout,
    validate_ttl,
)


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON constants are not allowed")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


class HttpLockerStore:
    """Low-level HTTP backend mapping to ``/lock``, ``/renew``, and ``/unlock``.

    Request payloads use the preserved service vocabulary
    ``lock_key``, ``lock_value``, and ``ttl_ms``.  Responses are accepted only
    when the expected boolean is present; response bodies and exception text
    are never surfaced in a :class:`LeaseError`.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 5.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        close_client: bool | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("invalid locker client configuration")
        if client is None and base_url is None:
            raise ValueError("invalid locker endpoint")
        if client is not None and base_url is None:
            base_url = str(client.base_url)
        assert base_url is not None
        self._base_url = validate_base_url(base_url)

        # Constructor failures contain no endpoint or transport details.
        constructor_corr = correlation_id_for("acquire", None)
        self._timeout = validate_timeout(timeout, "acquire", constructor_corr)
        self._max_response_bytes = validate_response_limit(
            max_response_bytes, "acquire", constructor_corr
        )

        self._owns_client = client is None if close_client is None else bool(close_client)
        constructed_client: httpx.AsyncClient | None = None
        if client is None:
            construction_failed = False
            try:
                constructed_client = httpx.AsyncClient(
                    transport=transport,
                    timeout=httpx.Timeout(self._timeout),
                    follow_redirects=False,
                    limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
                )
            except Exception:
                construction_failed = True
            if construction_failed:
                raise ValueError("invalid locker client configuration")
            assert constructed_client is not None
            self._client = constructed_client
        else:
            self._client = client
        self._closed = False

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"

    async def _post(
        self,
        operation: LeaseOperation,
        path: str,
        payload: dict[str, object],
        result_field: str,
        *,
        correlation_id: str | None,
    ) -> bool:
        corr = correlation_id_for(operation, correlation_id)
        if self._closed:
            raise LeaseError("unavailable", operation, corr)

        failure_code: str | None = None
        status: int | None = None
        content = b""
        oversized = False
        try:
            async with asyncio.timeout(self._timeout):
                async with self._client.stream(
                    "POST",
                    self._url(path),
                    json=payload,
                    headers={"x-correlation-id": corr},
                    timeout=self._timeout,
                ) as response:
                    status = response.status_code
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            oversized = int(content_length) > self._max_response_bytes
                        except (TypeError, ValueError):
                            oversized = False
                    if not oversized:
                        chunks: list[bytes] = []
                        total = 0
                        async for chunk in response.aiter_bytes():
                            remaining = self._max_response_bytes - total
                            if len(chunk) > remaining:
                                oversized = True
                                break
                            chunks.append(chunk)
                            total += len(chunk)
                        content = b"".join(chunks)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            failure_code = "timeout"
        except httpx.TimeoutException:
            failure_code = "timeout"
        except httpx.HTTPError:
            failure_code = "unavailable"
        except Exception:
            failure_code = "internal_error"

        if failure_code is not None:
            raise LeaseError(failure_code, operation, corr) from None
        if oversized:
            raise LeaseError("internal_error", operation, corr)
        if status is None:
            raise LeaseError("internal_error", operation, corr)
        if status == 499:
            raise LeaseError("cancelled", operation, corr)
        if status in {408, 504}:
            raise LeaseError("timeout", operation, corr)
        if status == 429 or status >= 500:
            raise LeaseError("unavailable", operation, corr)
        if status >= 400:
            raise LeaseError("invalid_request", operation, corr)
        if not 200 <= status < 300:
            raise LeaseError("internal_error", operation, corr)

        parse_failure = False
        body: Any = None
        try:
            body = json.loads(
                content,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError, RecursionError):
            parse_failure = True
        if parse_failure:
            raise LeaseError("internal_error", operation, corr)
        if not isinstance(body, dict):
            raise LeaseError("internal_error", operation, corr)
        if "ok" in body and body["ok"] is not True:
            raise LeaseError("internal_error", operation, corr)
        result = body.get(result_field)
        if type(result) is not bool:
            raise LeaseError("internal_error", operation, corr)
        return result

    async def acquire(
        self,
        key: str,
        owner: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        operation: LeaseOperation = "acquire"
        corr = correlation_id_for(operation, correlation_id)
        checked_key = validate_key(key, operation, corr)
        checked_owner = validate_owner(owner, operation, corr)
        checked_ttl = validate_ttl(ttl_ms, operation, corr)
        return await self._post(
            operation,
            "/lock",
            {"lock_key": checked_key, "lock_value": checked_owner, "ttl_ms": checked_ttl},
            "acquired",
            correlation_id=corr,
        )

    async def renew(
        self,
        key: str,
        owner: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        operation: LeaseOperation = "renew"
        corr = correlation_id_for(operation, correlation_id)
        checked_key = validate_key(key, operation, corr)
        checked_owner = validate_owner(owner, operation, corr)
        checked_ttl = validate_ttl(ttl_ms, operation, corr)
        return await self._post(
            operation,
            "/renew",
            {"lock_key": checked_key, "lock_value": checked_owner, "ttl_ms": checked_ttl},
            "renewed",
            correlation_id=corr,
        )

    async def release(
        self,
        key: str,
        owner: str,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        operation: LeaseOperation = "release"
        corr = correlation_id_for(operation, correlation_id)
        checked_key = validate_key(key, operation, corr)
        checked_owner = validate_owner(owner, operation, corr)
        return await self._post(
            operation,
            "/unlock",
            {"lock_key": checked_key, "lock_value": checked_owner},
            "deleted",
            correlation_id=corr,
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            try:
                await self._client.aclose()
            except Exception:
                # Closing is best-effort and intentionally has no public cause.
                return

    async def __aenter__(self) -> "HttpLockerStore":
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()


class LockerClient(LeaseClient):
    """Owner-generating :class:`LeaseClient` over the Locker HTTP service."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 5.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        close_client: bool | None = None,
        owner_factory: OwnerFactory | None = None,
        cleanup_timeout: float = 2.0,
    ) -> None:
        store = HttpLockerStore(
            base_url,
            client=client,
            transport=transport,
            timeout=timeout,
            max_response_bytes=max_response_bytes,
            close_client=close_client,
        )
        kwargs: dict[str, object] = {"cleanup_timeout": cleanup_timeout}
        if owner_factory is not None:
            kwargs["owner_factory"] = owner_factory
        super().__init__(store, **kwargs)
        self.store = store

    async def close(self) -> None:
        await self.store.close()


HttpLeaseStore = HttpLockerStore
HttpLeaseClient = LockerClient


__all__ = [
    "HttpLeaseClient",
    "HttpLeaseStore",
    "HttpLockerStore",
    "LockerClient",
]
