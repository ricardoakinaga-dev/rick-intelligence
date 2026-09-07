"""Typed identities and metadata for local objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import BinaryIO, TypeAlias

from rick_storage.errors import InvalidObjectKeyError
from rick_storage.validation import validate_object_key, validate_scope_component

ObjectPayload: TypeAlias = bytes | bytearray | memoryview | BinaryIO
_CHECKSUM = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ObjectScope:
    """The mandatory tenant/workspace/source ownership boundary."""

    tenant_id: str
    workspace_id: str
    source_id: str

    def __post_init__(self) -> None:
        for name in ("tenant_id", "workspace_id", "source_id"):
            object.__setattr__(
                self,
                name,
                validate_scope_component(getattr(self, name)),
            )


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    """Durable metadata returned by writes, heads, and listings."""

    scope: ObjectScope
    key: str
    size: int
    checksum: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ObjectScope):
            raise TypeError("scope must be an ObjectScope")
        try:
            validate_object_key(self.key)
        except InvalidObjectKeyError:
            raise
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ValueError("size must be a non-negative integer")
        if not isinstance(self.checksum, str) or _CHECKSUM.fullmatch(self.checksum) is None:
            raise ValueError("checksum must be a sha256 checksum")

    @property
    def tenant_id(self) -> str:
        return self.scope.tenant_id

    @property
    def workspace_id(self) -> str:
        return self.scope.workspace_id

    @property
    def source_id(self) -> str:
        return self.scope.source_id

    @property
    def sha256(self) -> str:
        """Return the bare lowercase SHA-256 digest."""

        return self.checksum.removeprefix("sha256:")


__all__ = ["ObjectMetadata", "ObjectPayload", "ObjectScope"]
