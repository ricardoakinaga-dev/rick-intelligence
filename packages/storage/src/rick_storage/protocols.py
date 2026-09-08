"""Dependency-injection protocol for object storage adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from rick_storage.models import ObjectMetadata, ObjectPayload, ObjectScope


@runtime_checkable
class ObjectStore(Protocol):
    """Small scope-aware object-store port."""

    def put(self, scope: ObjectScope, key: str, data: ObjectPayload) -> ObjectMetadata: ...

    def get(self, scope: ObjectScope, key: str, *, max_bytes: int | None = None) -> bytes: ...

    def head(self, scope: ObjectScope, key: str) -> ObjectMetadata: ...

    def list(
        self,
        scope: ObjectScope,
        *,
        prefix: str = "",
        limit: int | None = None,
    ) -> tuple[ObjectMetadata, ...]: ...

    def delete(self, scope: ObjectScope, key: str) -> bool: ...

    def close(self) -> None: ...


@runtime_checkable
class SyncHttpResponse(Protocol):
    """The small synchronous response surface required by the S3 adapter."""

    status_code: int
    headers: Mapping[str, str]

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


@runtime_checkable
class SyncHttpTransport(Protocol):
    """An injected synchronous HTTP transport.

    The storage package deliberately does not choose an HTTP client.  A
    production composition root can supply a pooled TLS transport, while
    hermetic tests can supply an in-memory implementation.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> SyncHttpResponse: ...

    def close(self) -> None: ...


__all__ = ["ObjectStore", "SyncHttpResponse", "SyncHttpTransport"]
