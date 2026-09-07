"""Validated, durable upload admission metadata for the ingestion boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


MAX_TOKEN_LENGTH = 128
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_SOURCE_TYPES = ("md", "txt", "pdf", "docx")
ALLOWED_OPERATIONS = ("ingest", "reindex", "delete")

_TOKEN = re.compile(r"[A-Za-z0-9._-]+")
_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}")
_SECRET_MARKER = re.compile(
    r"(?:^|[-_.])(?:secret|token|password|passwd|bearer|basic|"
    r"api[-_]?key|access[-_]?key|private[-_]?key)(?:$|[-_.])",
    re.IGNORECASE,
)


class UploadJobEnvelopeError(ValueError):
    """Base class for deterministic upload envelope validation failures."""


class InvalidUploadFieldError(UploadJobEnvelopeError):
    """A required identifier or key is missing or unsafe."""


class InvalidChecksumError(UploadJobEnvelopeError):
    """The checksum is not a lowercase SHA-256 digest with its prefix."""


class InvalidUploadSizeError(UploadJobEnvelopeError):
    """The upload size is not an integer within the supported bound."""


class UnsupportedSourceTypeError(UploadJobEnvelopeError):
    """The source type is outside the ingestion parser allowlist."""


class UnsupportedOperationError(UploadJobEnvelopeError):
    """The operation is outside the durable job operation allowlist."""


class ObjectScopeLike(Protocol):
    """Structural contract shared by storage's ObjectScope and the fallback."""

    tenant_id: str
    workspace_id: str
    source_id: str


@dataclass(frozen=True, slots=True)
class UploadJobScope:
    """Dependency-free ObjectScope-compatible fallback value."""

    tenant_id: str
    workspace_id: str
    source_id: str


def _validate_token(field_name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidUploadFieldError(f"{field_name} must be a non-empty ASCII token")
    if len(value) > MAX_TOKEN_LENGTH or _TOKEN.fullmatch(value) is None:
        raise InvalidUploadFieldError(
            f"{field_name} must be a non-empty ASCII token of at most {MAX_TOKEN_LENGTH} characters"
        )
    if value in {".", ".."} or value.endswith(".") or _SECRET_MARKER.search(value):
        raise InvalidUploadFieldError(f"{field_name} contains an unsafe token")
    return value


@dataclass(frozen=True, slots=True)
class UploadJobEnvelope:
    """Immutable metadata envelope crossing into the durable ingestion queue."""

    tenant_id: str
    workspace_id: str
    collection_id: str
    job_id: str
    idempotency_key: str
    source_key: str
    checksum: str
    size_bytes: int
    source_type: str
    request_id: str
    correlation_id: str
    operation: str = "ingest"

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "workspace_id",
            "collection_id",
            "job_id",
            "idempotency_key",
            "source_key",
            "request_id",
            "correlation_id",
        ):
            _validate_token(field_name, getattr(self, field_name))

        if not isinstance(self.checksum, str) or _CHECKSUM.fullmatch(self.checksum) is None:
            raise InvalidChecksumError("checksum must match sha256:<64 lowercase hex>")

        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or not 0 <= self.size_bytes <= MAX_UPLOAD_BYTES
        ):
            raise InvalidUploadSizeError(
                f"size_bytes must be an integer between 0 and {MAX_UPLOAD_BYTES}"
            )

        if self.source_type not in ALLOWED_SOURCE_TYPES:
            raise UnsupportedSourceTypeError(
                f"source_type must be one of {', '.join(ALLOWED_SOURCE_TYPES)}"
            )

        if self.operation not in ALLOWED_OPERATIONS:
            raise UnsupportedOperationError(
                f"operation must be one of {', '.join(ALLOWED_OPERATIONS)}"
            )

    def payload(self) -> dict[str, str]:
        """Return only the bounded metadata accepted by the queue contract."""

        return {
            "operation": self.operation,
            "source_key": self.source_key,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "collection_id": self.collection_id,
            "workspace_id": self.workspace_id,
            "tenant_id": self.tenant_id,
        }

    def scope(self) -> ObjectScopeLike:
        """Return storage's ObjectScope when installed, otherwise a local equivalent."""

        try:
            from rick_storage import ObjectScope
        except ImportError:
            return UploadJobScope(self.tenant_id, self.workspace_id, self.source_key)
        try:
            return ObjectScope(self.tenant_id, self.workspace_id, self.source_key)
        except (TypeError, ValueError):
            return UploadJobScope(self.tenant_id, self.workspace_id, self.source_key)

    def as_dict(self) -> dict[str, str | int]:
        """Return bounded diagnostic metadata, never upload content."""

        return {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "collection_id": self.collection_id,
            "job_id": self.job_id,
            "idempotency_key": self.idempotency_key,
            "source_key": self.source_key,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "source_type": self.source_type,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "operation": self.operation,
        }

    def to_dict(self) -> dict[str, str | int]:
        """Alias for callers that use serialization-oriented naming."""

        return self.as_dict()


__all__ = [
    "ALLOWED_OPERATIONS",
    "ALLOWED_SOURCE_TYPES",
    "InvalidChecksumError",
    "InvalidUploadFieldError",
    "InvalidUploadSizeError",
    "MAX_TOKEN_LENGTH",
    "MAX_UPLOAD_BYTES",
    "ObjectScopeLike",
    "UnsupportedOperationError",
    "UnsupportedSourceTypeError",
    "UploadJobEnvelope",
    "UploadJobEnvelopeError",
    "UploadJobScope",
]
