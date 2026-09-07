"""Stable, redacted failures for the local object-store boundary."""

from __future__ import annotations

from enum import StrEnum


class ObjectStoreErrorCode(StrEnum):
    """Stable classifications for failures at the storage boundary."""

    INVALID_SCOPE = "invalid_scope"
    INVALID_KEY = "invalid_key"
    INVALID_DATA = "invalid_data"
    INVALID_LIMIT = "invalid_limit"
    SIZE_LIMIT = "size_limit"
    READ_LIMIT = "read_limit"
    NOT_FOUND = "not_found"
    CORRUPT_OBJECT = "corrupt_object"
    INTEGRITY_ERROR = "integrity_error"
    CONFIGURATION = "configuration_error"
    PERMISSION = "permission_error"
    IO_ERROR = "io_error"
    PRODUCTION_MODE = "production_mode"


_SAFE_MESSAGES: dict[ObjectStoreErrorCode, str] = {
    ObjectStoreErrorCode.INVALID_SCOPE: "Invalid object scope",
    ObjectStoreErrorCode.INVALID_KEY: "Invalid object key",
    ObjectStoreErrorCode.INVALID_DATA: "Invalid object data",
    ObjectStoreErrorCode.INVALID_LIMIT: "Invalid storage limit",
    ObjectStoreErrorCode.SIZE_LIMIT: "Object exceeds the configured size limit",
    ObjectStoreErrorCode.READ_LIMIT: "Object exceeds the configured read limit",
    ObjectStoreErrorCode.NOT_FOUND: "Object not found",
    ObjectStoreErrorCode.CORRUPT_OBJECT: "Stored object is corrupt",
    ObjectStoreErrorCode.INTEGRITY_ERROR: "Stored object failed integrity verification",
    ObjectStoreErrorCode.CONFIGURATION: "Object store configuration is invalid",
    ObjectStoreErrorCode.PERMISSION: "Object store permission denied",
    ObjectStoreErrorCode.IO_ERROR: "Object store I/O failed",
    ObjectStoreErrorCode.PRODUCTION_MODE: "The local object store cannot run in production mode",
}


class ObjectStoreError(Exception):
    """A safe, typed object-store failure.

    Stringification intentionally excludes filesystem paths, object keys, and
    backend exception text.  Callers can use ``code`` for stable handling.
    """

    def __init__(
        self,
        code: ObjectStoreErrorCode | str,
        *,
        operation: str = "unknown",
    ) -> None:
        try:
            safe_code = ObjectStoreErrorCode(code)
        except (TypeError, ValueError):
            safe_code = ObjectStoreErrorCode.IO_ERROR
        self.code = safe_code
        self.error_code = safe_code.value
        self.operation = operation
        self.message = _SAFE_MESSAGES[safe_code]
        super().__init__(self.message)


class InvalidScopeError(ObjectStoreError):
    def __init__(self) -> None:
        super().__init__(ObjectStoreErrorCode.INVALID_SCOPE, operation="scope")


class InvalidObjectKeyError(ObjectStoreError):
    def __init__(self) -> None:
        super().__init__(ObjectStoreErrorCode.INVALID_KEY, operation="key")


class InvalidObjectDataError(ObjectStoreError):
    def __init__(self) -> None:
        super().__init__(ObjectStoreErrorCode.INVALID_DATA, operation="put")


class InvalidLimitError(ObjectStoreError):
    def __init__(self) -> None:
        super().__init__(ObjectStoreErrorCode.INVALID_LIMIT, operation="limit")


class ObjectTooLargeError(ObjectStoreError):
    def __init__(self, *, limit: int, observed: int | None = None) -> None:
        self.limit = limit
        self.observed = observed
        super().__init__(ObjectStoreErrorCode.SIZE_LIMIT, operation="put")


class ObjectReadLimitExceededError(ObjectStoreError):
    def __init__(self, *, limit: int, size: int) -> None:
        self.limit = limit
        self.size = size
        super().__init__(ObjectStoreErrorCode.READ_LIMIT, operation="get")


class ObjectNotFoundError(ObjectStoreError):
    def __init__(self, *, operation: str = "get") -> None:
        super().__init__(ObjectStoreErrorCode.NOT_FOUND, operation=operation)


class ObjectStoreCorruptionError(ObjectStoreError):
    def __init__(self, *, operation: str = "read") -> None:
        super().__init__(ObjectStoreErrorCode.CORRUPT_OBJECT, operation=operation)


class ObjectIntegrityError(ObjectStoreError):
    def __init__(self) -> None:
        super().__init__(ObjectStoreErrorCode.INTEGRITY_ERROR, operation="get")


class ObjectStoreConfigurationError(ObjectStoreError):
    def __init__(self) -> None:
        super().__init__(ObjectStoreErrorCode.CONFIGURATION, operation="configure")


class ObjectStorePermissionError(ObjectStoreError):
    def __init__(self, *, operation: str = "filesystem") -> None:
        super().__init__(ObjectStoreErrorCode.PERMISSION, operation=operation)


class ObjectStoreIOError(ObjectStoreError):
    def __init__(self, *, operation: str) -> None:
        super().__init__(ObjectStoreErrorCode.IO_ERROR, operation=operation)


class ProductionModeError(ObjectStoreError):
    def __init__(self) -> None:
        super().__init__(ObjectStoreErrorCode.PRODUCTION_MODE, operation="configure")


__all__ = [
    "InvalidLimitError",
    "InvalidObjectDataError",
    "InvalidObjectKeyError",
    "InvalidScopeError",
    "ObjectIntegrityError",
    "ObjectNotFoundError",
    "ObjectReadLimitExceededError",
    "ObjectStoreConfigurationError",
    "ObjectStoreCorruptionError",
    "ObjectStoreError",
    "ObjectStoreErrorCode",
    "ObjectStoreIOError",
    "ObjectStorePermissionError",
    "ObjectTooLargeError",
    "ProductionModeError",
]
