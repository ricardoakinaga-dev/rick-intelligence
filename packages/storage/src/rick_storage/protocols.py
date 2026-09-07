"""Dependency-injection protocol for object storage adapters."""

from __future__ import annotations

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


__all__ = ["ObjectStore"]
