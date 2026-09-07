"""Canonical local-only object storage boundary."""

from rick_storage.errors import (
    InvalidLimitError,
    InvalidObjectDataError,
    InvalidObjectKeyError,
    InvalidScopeError,
    ObjectIntegrityError,
    ObjectNotFoundError,
    ObjectReadLimitExceededError,
    ObjectStoreConfigurationError,
    ObjectStoreCorruptionError,
    ObjectStoreError,
    ObjectStoreErrorCode,
    ObjectStoreIOError,
    ObjectStorePermissionError,
    ObjectTooLargeError,
    ProductionModeError,
)
from rick_storage.models import ObjectMetadata, ObjectPayload, ObjectScope
from rick_storage.object_store import (
    DEFAULT_MAX_LIST_ITEMS,
    DEFAULT_MAX_OBJECT_BYTES,
    DEFAULT_MAX_READ_BYTES,
    LocalObjectStore,
)
from rick_storage.protocols import ObjectStore

__all__ = [
    "DEFAULT_MAX_LIST_ITEMS",
    "DEFAULT_MAX_OBJECT_BYTES",
    "DEFAULT_MAX_READ_BYTES",
    "InvalidLimitError",
    "InvalidObjectDataError",
    "InvalidObjectKeyError",
    "InvalidScopeError",
    "LocalObjectStore",
    "ObjectIntegrityError",
    "ObjectMetadata",
    "ObjectNotFoundError",
    "ObjectPayload",
    "ObjectReadLimitExceededError",
    "ObjectScope",
    "ObjectStore",
    "ObjectStoreConfigurationError",
    "ObjectStoreCorruptionError",
    "ObjectStoreError",
    "ObjectStoreErrorCode",
    "ObjectStoreIOError",
    "ObjectStorePermissionError",
    "ObjectTooLargeError",
    "ProductionModeError",
]
