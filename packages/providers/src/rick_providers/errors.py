"""Safe, typed errors for provider operations."""

from __future__ import annotations

import json
from typing import Literal, TypeGuard

from rick_contracts.providers import ProviderErrorCode, ProviderErrorDto


ProviderOperation = Literal["chat_completion", "embeddings"]

RETRYABLE_ERROR_CODES = frozenset({
    "timeout",
    "unavailable",
    "rate_limit",
    "server_error",
})


class ProviderError(Exception):
    """A serializable provider failure containing metadata only.

    The constructor intentionally has no ``cause`` argument and the instance
    never stores a response body, URL, request payload, credential, or raw
    exception.  Callers can safely use ``str``, ``repr``, ``to_dict`` and
    ``to_json`` at an API/logging boundary.
    """

    code: ProviderErrorCode
    operation: ProviderOperation
    correlation_id: str
    attempts: int
    retryable: bool
    status: int | None

    def __init__(
        self,
        code: ProviderErrorCode,
        operation: ProviderOperation,
        correlation_id: str,
        attempts: int,
        retryable: bool | None = None,
        status: int | None = None,
    ) -> None:
        # The taxonomy owns retryability.  Accepting a caller-provided true
        # value for a permanent code could accidentally make malformed
        # responses retry forever in a custom consumer.
        safe_retryable = code in RETRYABLE_ERROR_CODES
        dto = ProviderErrorDto(
            code=code,
            operation=operation,
            correlation_id=correlation_id,
            attempts=attempts,
            retryable=safe_retryable,
            status=status,
        )
        self.code = dto.code
        self.operation = dto.operation
        self.correlation_id = dto.correlation_id
        self.attempts = dto.attempts
        self.retryable = dto.retryable
        self.status = dto.status
        # Exception.args contains only the same safe fields surfaced by str.
        super().__init__(f"provider_{self.code} ({self.correlation_id})")

    @property
    def correlationId(self) -> str:
        """Camel-case compatibility accessor for JS-facing callers."""

        return self.correlation_id

    def __str__(self) -> str:
        return f"provider_{self.code} ({self.correlation_id})"

    def __repr__(self) -> str:
        status = f", status={self.status!r}" if self.status is not None else ""
        return (
            "ProviderError("
            f"code={self.code!r}, operation={self.operation!r}, "
            f"correlation_id={self.correlation_id!r}, attempts={self.attempts!r}, "
            f"retryable={self.retryable!r}{status})"
        )

    def to_dto(self) -> ProviderErrorDto:
        """Return the canonical shared error DTO."""

        return ProviderErrorDto(
            code=self.code,
            operation=self.operation,
            correlation_id=self.correlation_id,
            attempts=self.attempts,
            retryable=self.retryable,
            status=self.status,
        )

    def to_dict(self) -> dict[str, object]:
        """Return only safe JSON-compatible error metadata."""

        return self.to_dto().model_dump(mode="json", exclude_none=True)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def toJSON(self) -> dict[str, object]:
        """Camel-case compatibility alias for JSON-oriented adapters."""

        return self.to_dict()

    # Familiar names for frameworks that call an explicit serialization hook.
    def model_dump(self, *, mode: str = "python", exclude_none: bool = True, **_: object) -> dict[str, object]:
        return self.to_dto().model_dump(mode=mode, exclude_none=exclude_none)

    def model_dump_json(self, *, exclude_none: bool = True, **_: object) -> str:
        return self.to_dto().model_dump_json(exclude_none=exclude_none)

    def dict(self, *, exclude_none: bool = True, **_: object) -> dict[str, object]:
        return self.to_dict() if exclude_none else self.to_dto().model_dump(mode="json")

    def with_attempts(self, attempts: int) -> "ProviderError":
        """Copy an error with the current logical operation attempt count."""

        return ProviderError(
            self.code,
            self.operation,
            self.correlation_id,
            attempts,
            self.retryable,
            self.status,
        )


def provider_error(
    code: ProviderErrorCode,
    operation: ProviderOperation,
    correlation_id: str,
    attempts: int,
    status: int | None = None,
) -> ProviderError:
    """Construct an error with retryability derived from the taxonomy."""

    return ProviderError(code, operation, correlation_id, attempts, status=status)


def is_provider_error(error: object) -> TypeGuard[ProviderError]:
    return isinstance(error, ProviderError)


def summarize_provider_error(error: object) -> dict[str, object] | None:
    return error.to_dict() if isinstance(error, ProviderError) else None


__all__ = [
    "ProviderError",
    "ProviderOperation",
    "RETRYABLE_ERROR_CODES",
    "is_provider_error",
    "provider_error",
    "summarize_provider_error",
]
