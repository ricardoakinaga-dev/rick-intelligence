"""Safe, typed failures for the lease boundary.

The public error deliberately contains only the operation, a correlation ID,
and a stable classification.  Backend exception text, URLs, keys, and owner
tokens never become part of the public error.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from rick_contracts.locking import LeaseErrorDto

LeaseOperation = Literal["acquire", "renew", "release"]


class LeaseErrorCode(StrEnum):
    """Stable failure classifications exposed by the locking boundary."""

    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    NOT_OWNER = "not_owner"
    INVALID_REQUEST = "invalid_request"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


_SAFE_MESSAGES: dict[LeaseErrorCode, str] = {
    LeaseErrorCode.UNAVAILABLE: "Lease service unavailable",
    LeaseErrorCode.TIMEOUT: "Lease operation timed out",
    LeaseErrorCode.NOT_OWNER: "Lease owner mismatch",
    LeaseErrorCode.INVALID_REQUEST: "Invalid lease request",
    LeaseErrorCode.CANCELLED: "Lease operation cancelled",
    LeaseErrorCode.INTERNAL_ERROR: "Lease operation failed",
}

_RETRYABLE: frozenset[LeaseErrorCode] = frozenset(
    {LeaseErrorCode.UNAVAILABLE, LeaseErrorCode.TIMEOUT}
)
_OPERATIONS: frozenset[str] = frozenset({"acquire", "renew", "release"})
_CORRELATION_FALLBACK = "invalid-correlation"


def _safe_operation(operation: object) -> LeaseOperation:
    if isinstance(operation, str) and operation in _OPERATIONS:
        return operation  # type: ignore[return-value]
    return "acquire"


def _safe_correlation_id(correlation_id: object) -> str:
    if (
        isinstance(correlation_id, str)
        and 1 <= len(correlation_id) <= 128
        and all(char.isalnum() or char in "._:-" for char in correlation_id)
    ):
        return correlation_id
    return _CORRELATION_FALLBACK


class LeaseError(Exception):
    """A stable, redacted lease failure.

    ``str(error)`` and ``repr(error)`` contain only the stable safe message.
    Callers that need a serialized contract should use :meth:`to_dto`.
    """

    def __init__(
        self,
        code: LeaseErrorCode | str,
        operation: LeaseOperation | str,
        correlation_id: str,
    ) -> None:
        try:
            safe_code = LeaseErrorCode(code)
        except (TypeError, ValueError):
            safe_code = LeaseErrorCode.INTERNAL_ERROR
        safe_operation = _safe_operation(operation)
        safe_correlation_id = _safe_correlation_id(correlation_id)

        self.code: LeaseErrorCode = safe_code
        self.error_code: str = safe_code.value
        self.operation: LeaseOperation = safe_operation
        self.correlation_id: str = safe_correlation_id
        self.retryable: bool = safe_code in _RETRYABLE
        self.message: str = _SAFE_MESSAGES[safe_code]
        super().__init__(self.message)

    def __repr__(self) -> str:
        return (
            f"LeaseError(code={self.code.value!r}, operation={self.operation!r}, "
            f"correlation_id={self.correlation_id!r})"
        )

    def to_dto(self) -> LeaseErrorDto:
        """Return the shared serialized error contract without backend detail."""

        return LeaseErrorDto(
            operation=self.operation,
            code=self.code.value,
            correlation_id=self.correlation_id,
        )

    @property
    def dto(self) -> LeaseErrorDto:
        """Compatibility property for callers that prefer attribute access."""

        return self.to_dto()

    def as_dict(self) -> dict[str, object]:
        """Return the safe serialized representation."""

        return self.to_dto().model_dump(mode="json")

    def to_dict(self) -> dict[str, object]:
        """Compatibility alias for safe JSON-compatible serialization."""

        return self.as_dict()

    def to_json(self) -> str:
        """Serialize only the safe shared error fields."""

        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))

    def model_dump(
        self,
        *,
        mode: str = "python",
        exclude_none: bool = False,
        **_: object,
    ) -> dict[str, object]:
        """Expose the DTO's serialization hook without exception detail."""

        return self.to_dto().model_dump(mode=mode, exclude_none=exclude_none)


@dataclass(frozen=True, slots=True)
class LeaseFailure:
    """A non-raising safe failure value for adapters and diagnostics."""

    code: LeaseErrorCode
    operation: LeaseOperation
    correlation_id: str

    def __post_init__(self) -> None:
        try:
            safe_code = LeaseErrorCode(self.code)
        except (TypeError, ValueError):
            safe_code = LeaseErrorCode.INTERNAL_ERROR
        object.__setattr__(self, "code", safe_code)
        object.__setattr__(self, "operation", _safe_operation(self.operation))
        object.__setattr__(
            self, "correlation_id", _safe_correlation_id(self.correlation_id)
        )

    @property
    def retryable(self) -> bool:
        return self.code in _RETRYABLE

    def to_dto(self) -> LeaseErrorDto:
        return LeaseError(
            self.code, self.operation, self.correlation_id
        ).to_dto()


def classify_exception(exception: BaseException) -> LeaseErrorCode:
    """Classify an exception without exposing its text or cause."""

    if isinstance(exception, LeaseError):
        return exception.code
    if isinstance(exception, TimeoutError):
        return LeaseErrorCode.TIMEOUT
    if isinstance(exception, asyncio.CancelledError):
        return LeaseErrorCode.CANCELLED
    return LeaseErrorCode.INTERNAL_ERROR


# The aliases keep the boundary easy to discover for code that calls the
# resource a lock instead of a lease.
LockError = LeaseError
LockErrorCode = LeaseErrorCode


__all__ = [
    "LeaseError",
    "LeaseErrorCode",
    "LeaseFailure",
    "LeaseOperation",
    "LockError",
    "LockErrorCode",
    "classify_exception",
]
