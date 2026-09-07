"""Typed, bounded Qdrant HTTP adapter for the retrieval vector contract.

The existing :mod:`rick_retrieval.vectordb` contract is intentionally small and
synchronous.  This module keeps that surface while adding the live operations
needed by the retrieval boundary.  HTTP is isolated behind ``HttpTransport``
so unit tests can exercise the request/response boundary without a Qdrant
process or network access.

The default transport imports ``httpx`` only when an adapter is constructed.
Importing this module therefore has no dependency-side effects and never makes
a network request.  No environment variables or production settings are read
here; callers must provide the base URL and collection explicitly.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias
from urllib.parse import urlsplit


# These limits are deliberately finite and are part of the adapter's safety
# boundary.  Per-instance values may be lowered for a deployment or test, but
# never raised above these hard ceilings.
MAX_POINTS_PER_UPSERT = 256
MAX_QUERY_RESULTS = 100
MAX_COLLECTION_FILTERS = 128
MAX_VECTOR_DIMENSIONS = 16_384
MAX_POINT_ID_CHARS = 128
MAX_SCOPE_VALUE_CHARS = 128
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_QUERY_BYTES = 256 * 1024
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 1_000_000

# Public aliases make the size policy discoverable without coupling callers to
# a private implementation name.
MAX_UPSERT_POINTS = MAX_POINTS_PER_UPSERT
MAX_QUERY_LIMIT = MAX_QUERY_RESULTS
MAX_RESPONSE_SIZE_BYTES = MAX_RESPONSE_BYTES

_COLLECTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_DENSE_VECTOR_NAME = "dense"

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class QdrantError(Exception):
    """Base class for safe, typed adapter failures.

    Error instances intentionally retain only bounded operational metadata.
    They never retain URLs, headers, request payloads, response bodies, or the
    original transport exception, all of which may contain credentials or
    sensitive document content.
    """

    code = "qdrant_error"

    def __init__(self, operation: str, *, detail: str | None = None) -> None:
        self.operation = operation
        self.detail = detail if detail in _SAFE_ERROR_DETAILS else None
        message = f"{self.code} ({operation})"
        if self.detail is not None:
            message = f"{message}: {self.detail}"
        super().__init__(message)

    def __repr__(self) -> str:
        suffix = f", detail={self.detail!r}" if self.detail is not None else ""
        return f"{type(self).__name__}(operation={self.operation!r}{suffix})"


# Details are selected from a fixed allow-list so a future call site cannot
# accidentally put an input value, URL, or server body into an exception.
_SAFE_ERROR_DETAILS = frozenset(
    {
        "invalid_configuration",
        "dependency_unavailable",
        "invalid_input",
        "limit_exceeded",
        "empty_scope",
        "transport_failure",
        "malformed_response",
        "response_too_large",
        "closed",
    }
)


class QdrantConfigurationError(QdrantError, ValueError):
    code = "qdrant_invalid_configuration"

    def __init__(self) -> None:
        super().__init__("configure", detail="invalid_configuration")


class QdrantDependencyError(QdrantError):
    code = "qdrant_dependency_unavailable"

    def __init__(self) -> None:
        super().__init__("configure", detail="dependency_unavailable")


class QdrantValidationError(QdrantError, ValueError):
    code = "qdrant_invalid_input"

    def __init__(self, operation: str = "validate", *, limit: bool = False, empty_scope: bool = False) -> None:
        detail = "limit_exceeded" if limit else "empty_scope" if empty_scope else "invalid_input"
        super().__init__(operation, detail=detail)


class QdrantBoundsError(QdrantValidationError):
    """Input or output crossed one of the adapter's finite bounds."""


class QdrantClosedError(QdrantError):
    code = "qdrant_closed"

    def __init__(self, operation: str) -> None:
        super().__init__(operation, detail="closed")


class QdrantTimeoutError(QdrantError):
    code = "qdrant_timeout"

    def __init__(self, operation: str) -> None:
        super().__init__(operation)


class QdrantTransportError(QdrantError):
    code = "qdrant_transport_error"

    def __init__(self, operation: str) -> None:
        super().__init__(operation, detail="transport_failure")


class QdrantStatusError(QdrantError):
    """A non-success HTTP response with no body or URL disclosure."""

    code = "qdrant_http_status"

    def __init__(self, operation: str, status_code: int) -> None:
        self.status_code = status_code
        self.status = status_code
        super().__init__(operation)

    def __str__(self) -> str:
        return f"{self.code} ({self.operation}, status={self.status_code})"

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(operation={self.operation!r}, "
            f"status_code={self.status_code!r})"
        )


class QdrantMalformedResponseError(QdrantError):
    code = "qdrant_malformed_response"

    def __init__(self, operation: str) -> None:
        super().__init__(operation, detail="malformed_response")


class QdrantResponseTooLargeError(QdrantError):
    code = "qdrant_response_too_large"

    def __init__(self, operation: str) -> None:
        super().__init__(operation, detail="response_too_large")


# Common short names for callers that do not need the longer class spelling.
QdrantHTTPError = QdrantStatusError
QdrantResponseError = QdrantMalformedResponseError


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Minimal response value understood by the adapter transport boundary."""

    status_code: int
    content: bytes | str
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("invalid HTTP status")
        if isinstance(self.content, str):
            object.__setattr__(self, "content", self.content.encode("utf-8"))
        elif isinstance(self.content, bytearray):
            object.__setattr__(self, "content", bytes(self.content))
        elif not isinstance(self.content, bytes):
            raise TypeError("HTTP content must be bytes or text")

    @property
    def body(self) -> bytes:
        """Compatibility spelling for transports that call the body ``body``."""

        return self.content


class HttpTransport(Protocol):
    """Synchronous, injectable HTTP transport used by the adapter."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes,
        timeout: float,
    ) -> HttpResponse: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class QdrantLimits:
    """Per-adapter limits, each bounded by the module hard ceiling."""

    max_points: int = MAX_POINTS_PER_UPSERT
    max_query_results: int = MAX_QUERY_RESULTS
    max_collection_filters: int = MAX_COLLECTION_FILTERS
    max_vector_dimensions: int = MAX_VECTOR_DIMENSIONS
    max_payload_bytes: int = MAX_PAYLOAD_BYTES
    max_query_bytes: int = MAX_QUERY_BYTES
    max_request_bytes: int = MAX_REQUEST_BYTES
    max_response_bytes: int = MAX_RESPONSE_BYTES

    def validate(self) -> None:
        ceilings = (
            (self.max_points, MAX_POINTS_PER_UPSERT),
            (self.max_query_results, MAX_QUERY_RESULTS),
            (self.max_collection_filters, MAX_COLLECTION_FILTERS),
            (self.max_vector_dimensions, MAX_VECTOR_DIMENSIONS),
            (self.max_payload_bytes, MAX_PAYLOAD_BYTES),
            (self.max_query_bytes, MAX_QUERY_BYTES),
            (self.max_request_bytes, MAX_REQUEST_BYTES),
            (self.max_response_bytes, MAX_RESPONSE_BYTES),
        )
        if any(type(value) is not int or value <= 0 or value > ceiling for value, ceiling in ceilings):
            raise QdrantConfigurationError()

    def __repr__(self) -> str:
        return (
            "QdrantLimits("
            f"max_points={self.max_points}, max_query_results={self.max_query_results}, "
            f"max_payload_bytes={self.max_payload_bytes}, "
            f"max_response_bytes={self.max_response_bytes})"
        )


@dataclass(frozen=True, slots=True)
class QdrantHealth:
    """Safe health result; server body text is deliberately not retained."""

    ok: bool
    status_code: int

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True, slots=True)
class QdrantSearchHit(Mapping[str, object]):
    """Validated search hit with dict-like compatibility for retrieval callers."""

    point_id: str
    score: float
    payload: Mapping[str, JsonValue]

    @property
    def id(self) -> str:
        return self.point_id

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.point_id,
            "point_id": self.point_id,
            "score": self.score,
            "payload": dict(self.payload),
        }

    def __getitem__(self, key: str) -> object:
        return self.as_dict()[key]

    def __iter__(self):
        return iter(self.as_dict())

    def __len__(self) -> int:
        return 4


@dataclass(frozen=True, slots=True)
class QdrantDeleteResult:
    """Acknowledgement returned by Qdrant's asynchronous update endpoint."""

    acknowledged: bool
    operation_id: int | str | None = None

    def __bool__(self) -> bool:
        return self.acknowledged


@dataclass(frozen=True, slots=True)
class _Scope:
    tenant_id: str
    workspace_id: str
    allowed_collection_ids: tuple[str, ...]


class _HttpxTransport:
    """Lazy sync httpx transport, including support for MockTransport."""

    def __init__(self, transport: object | None = None) -> None:
        try:
            import httpx
        except ImportError:
            raise QdrantDependencyError() from None
        try:
            self._client = httpx.Client(transport=transport)
        except Exception:
            raise QdrantConfigurationError() from None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes,
        timeout: float,
    ) -> HttpResponse:
        response = self._client.request(
            method,
            url,
            headers=dict(headers),
            content=content,
            timeout=timeout,
        )
        return HttpResponse(
            status_code=response.status_code,
            content=response.content,
            headers=dict(response.headers),
        )

    def close(self) -> None:
        self._client.close()


class QdrantHttpVectorStore:
    """Live Qdrant REST adapter with mandatory scoped reads and deletes.

    ``base_url`` and ``collection`` have no defaults by design.  A caller must
    opt into a concrete external destination.  A supplied ``transport`` must
    implement :class:`HttpTransport`; an ``httpx.MockTransport`` is also
    accepted and wrapped lazily for hermetic tests.
    """

    def __init__(
        self,
        base_url: str | None = None,
        collection: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 5.0,
        transport: HttpTransport | object | None = None,
        limits: QdrantLimits | None = None,
        max_points: int | None = None,
        max_query_results: int | None = None,
        max_payload_bytes: int | None = None,
        max_response_bytes: int | None = None,
    ) -> None:
        self._base_url = _validate_base_url(base_url)
        self.collection = _validate_collection_name(collection)
        self._timeout = _validate_timeout(timeout)
        self._api_key = _validate_api_key(api_key)
        selected_limits = limits or QdrantLimits()
        overrides = {
            "max_points": max_points,
            "max_query_results": max_query_results,
            "max_payload_bytes": max_payload_bytes,
            "max_response_bytes": max_response_bytes,
        }
        if any(value is not None for value in overrides.values()):
            selected_limits = QdrantLimits(
                max_points=selected_limits.max_points if max_points is None else max_points,
                max_query_results=(
                    selected_limits.max_query_results
                    if max_query_results is None
                    else max_query_results
                ),
                max_collection_filters=selected_limits.max_collection_filters,
                max_vector_dimensions=selected_limits.max_vector_dimensions,
                max_payload_bytes=(
                    selected_limits.max_payload_bytes
                    if max_payload_bytes is None
                    else max_payload_bytes
                ),
                max_query_bytes=selected_limits.max_query_bytes,
                max_request_bytes=selected_limits.max_request_bytes,
                max_response_bytes=(
                    selected_limits.max_response_bytes
                    if max_response_bytes is None
                    else max_response_bytes
                ),
            )
        selected_limits.validate()
        self.limits = selected_limits
        self._transport = _coerce_transport(transport)
        self._closed = False

    def __repr__(self) -> str:
        # Do not expose the base URL: it may contain internal topology.  The
        # API key is never represented at all.
        return (
            f"{type(self).__name__}(collection={self.collection!r}, "
            f"timeout={self._timeout!r}, closed={self._closed!r})"
        )

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> "QdrantHttpVectorStore":
        self._ensure_open("enter")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying transport once; repeated close is a no-op."""

        if self._closed:
            return
        self._closed = True
        close_failed = False
        try:
            close = getattr(self._transport, "close", None)
            if callable(close):
                close()
        except Exception:
            # The resource is terminally closed even if its implementation
            # reports a cleanup failure.  Do not retain or expose that error.
            close_failed = True
        if close_failed:
            raise QdrantTransportError("close")

    def health(self) -> QdrantHealth:
        """Check Qdrant liveness through ``GET /healthz``."""

        response = self._request("GET", "/healthz", operation="health")
        return QdrantHealth(ok=True, status_code=response.status_code)

    # Explicit alias for callers that name the operation as a check.
    health_check = health

    def upsert_points(self, points: list[dict[str, Any]] | Sequence[Mapping[str, object]]) -> int:
        """Upsert bounded points using the named ``dense`` vector."""

        operation = "upsert"
        self._ensure_open(operation)
        if not isinstance(points, Sequence) or isinstance(points, (str, bytes, bytearray)):
            raise QdrantValidationError(operation)
        if len(points) > self.limits.max_points:
            raise QdrantBoundsError(operation, limit=True)
        if not points:
            return 0

        encoded_points: list[dict[str, object]] = []
        for point in points:
            encoded_points.append(self._normalize_point(point, operation))
        body = self._encode_json(
            {"points": encoded_points},
            operation,
            max_bytes=min(self.limits.max_request_bytes, MAX_REQUEST_BYTES),
        )
        response = self._request(
            "PUT",
            self._collection_path("/points?wait=true"),
            operation=operation,
            content=body,
        )
        result = self._decode_json(response.content, operation)
        _require_acknowledged_result(result, operation)
        return len(encoded_points)

    def upsert(self, points: list[dict[str, Any]] | Sequence[Mapping[str, object]]) -> int:
        """Operation-named alias for the contract method ``upsert_points``."""

        return self.upsert_points(points)

    def query(
        self,
        query_vector: Sequence[float] | None = None,
        *,
        vector: Sequence[float] | None = None,
        tenant_id: str,
        workspace_id: str,
        allowed_collection_ids: Sequence[str],
        limit: int = 10,
    ) -> list[QdrantSearchHit]:
        """Query the modern Qdrant Query API with mandatory ACL filters."""

        return self._query_or_search(
            query_vector,
            vector=vector,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            allowed_collection_ids=allowed_collection_ids,
            limit=limit,
            endpoint="/points/query",
            operation="query",
        )

    def search(
        self,
        query_vector: Sequence[float] | None = None,
        *,
        vector: Sequence[float] | None = None,
        tenant_id: str,
        workspace_id: str,
        allowed_collection_ids: Sequence[str],
        limit: int = 10,
    ) -> list[QdrantSearchHit]:
        """Search the compatibility Qdrant search endpoint with ACL filters."""

        return self._query_or_search(
            query_vector,
            vector=vector,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            allowed_collection_ids=allowed_collection_ids,
            limit=limit,
            endpoint="/points/search",
            operation="search",
        )

    def delete_by_filter(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        allowed_collection_ids: Sequence[str],
        document_id: str | None = None,
        chunk_id: str | None = None,
    ) -> QdrantDeleteResult:
        """Delete only a non-empty, ACL-scoped payload filter.

        Raw Qdrant filter objects are intentionally not accepted.  The adapter
        owns construction of the mandatory tenant/workspace/collection
        predicates, preventing a caller from accidentally replacing them.
        """

        operation = "delete"
        self._ensure_open(operation)
        scope = self._scope(
            tenant_id,
            workspace_id,
            allowed_collection_ids,
            operation=operation,
            require_nonempty=True,
        )
        if document_id is None and chunk_id is None:
            raise QdrantValidationError(operation)
        must = list(_acl_filter(scope)["must"])
        if document_id is not None:
            must.append({"key": "document_id", "match": {"value": _validate_id(document_id, operation)}})
        if chunk_id is not None:
            must.append({"key": "chunk_id", "match": {"value": _validate_id(chunk_id, operation)}})
        body = self._encode_json(
            {"filter": {"must": must}, "wait": True},
            operation,
            max_bytes=self.limits.max_query_bytes,
        )
        response = self._request(
            "POST",
            self._collection_path("/points/delete"),
            operation=operation,
            content=body,
        )
        parsed = self._decode_json(response.content, operation)
        result = _require_acknowledged_result(parsed, operation)
        operation_id = None
        if isinstance(result, Mapping):
            candidate = result.get("operation_id")
            if type(candidate) is int or isinstance(candidate, str):
                operation_id = candidate
        return QdrantDeleteResult(acknowledged=True, operation_id=operation_id)

    def delete_document(
        self,
        document_id: str,
        collection_id: str,
        *,
        tenant_id: str,
        workspace_id: str | None = None,
    ) -> int:
        """Contract-compatible delete; workspace scope is mandatory in use."""

        if workspace_id is None:
            raise QdrantValidationError("delete", empty_scope=True)
        self.delete_by_filter(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            allowed_collection_ids=[collection_id],
            document_id=document_id,
        )
        # Qdrant's update acknowledgement does not promise a deleted count.
        # Preserve the existing VectorStore return type without inventing one.
        return 0

    def count_for_document(
        self,
        document_id: str,
        collection_id: str,
        *,
        tenant_id: str,
        workspace_id: str | None = None,
    ) -> int:
        """Contract-compatible exact count over a mandatory ACL scope."""

        operation = "count"
        self._ensure_open(operation)
        if workspace_id is None:
            raise QdrantValidationError(operation, empty_scope=True)
        scope = self._scope(
            tenant_id,
            workspace_id,
            [collection_id],
            operation=operation,
            require_nonempty=True,
        )
        must = list(_acl_filter(scope)["must"])
        must.append({"key": "document_id", "match": {"value": _validate_id(document_id, operation)}})
        body = self._encode_json(
            {"filter": {"must": must}, "exact": True},
            operation,
            max_bytes=self.limits.max_query_bytes,
        )
        response = self._request(
            "POST",
            self._collection_path("/points/count"),
            operation=operation,
            content=body,
        )
        parsed = self._decode_json(response.content, operation)
        if not isinstance(parsed, Mapping):
            raise QdrantMalformedResponseError(operation)
        result = parsed.get("result")
        if not isinstance(result, Mapping) or type(result.get("count")) is not int or result["count"] < 0:
            raise QdrantMalformedResponseError(operation)
        return result["count"]

    def _query_or_search(
        self,
        query_vector: Sequence[float] | None,
        *,
        vector: Sequence[float] | None,
        tenant_id: str,
        workspace_id: str,
        allowed_collection_ids: Sequence[str],
        limit: int,
        endpoint: str,
        operation: str,
    ) -> list[QdrantSearchHit]:
        self._ensure_open(operation)
        if query_vector is not None and vector is not None:
            raise QdrantValidationError(operation)
        selected_vector = query_vector if query_vector is not None else vector
        checked_vector = _validate_vector(selected_vector, operation, self.limits.max_vector_dimensions)
        checked_limit = _validate_limit(limit, operation, self.limits.max_query_results)
        scope = self._scope(
            tenant_id,
            workspace_id,
            allowed_collection_ids,
            operation=operation,
            require_nonempty=False,
        )
        if scope is None:
            # An empty grant is an authoritative deny.  Returning before HTTP
            # prevents accidental unscoped queries and avoids remote probing.
            return []
        query_filter = _acl_filter(scope)
        if endpoint.endswith("/query"):
            request_body: dict[str, object] = {
                "query": checked_vector,
                "using": _DENSE_VECTOR_NAME,
                "filter": query_filter,
                "limit": checked_limit,
                "with_payload": True,
                "with_vector": False,
            }
        else:
            request_body = {
                "vector": {"name": _DENSE_VECTOR_NAME, "vector": checked_vector},
                "filter": query_filter,
                "limit": checked_limit,
                "with_payload": True,
                "with_vector": False,
            }
        body = self._encode_json(request_body, operation, max_bytes=self.limits.max_query_bytes)
        response = self._request(
            "POST",
            self._collection_path(endpoint),
            operation=operation,
            content=body,
        )
        parsed = self._decode_json(response.content, operation)
        raw_hits = _extract_hits(parsed, operation)
        if len(raw_hits) > self.limits.max_query_results:
            raise QdrantBoundsError(operation, limit=True)
        return self._trusted_hits(raw_hits, scope, operation)

    def _trusted_hits(
        self,
        raw_hits: list[object],
        scope: _Scope,
        operation: str,
    ) -> list[QdrantSearchHit]:
        trusted: list[QdrantSearchHit] = []
        allowed = set(scope.allowed_collection_ids)
        for raw in raw_hits:
            if not isinstance(raw, Mapping):
                raise QdrantMalformedResponseError(operation)
            raw_id = raw.get("id")
            score = raw.get("score")
            payload = raw.get("payload")
            if (not isinstance(raw_id, (str, int)) or isinstance(raw_id, bool)
                    or not isinstance(payload, Mapping)
                    or not isinstance(score, (int, float)) or isinstance(score, bool)
                    or not math.isfinite(float(score))):
                raise QdrantMalformedResponseError(operation)
            payload_json = self._encode_json(dict(payload), operation, max_bytes=self.limits.max_payload_bytes)
            typed_payload = _validate_json_mapping(payload, operation)
            payload_tenant = typed_payload.get("tenant_id")
            payload_workspace = typed_payload.get("workspace_id")
            payload_collection = typed_payload.get("collection_id")
            # A server-side filter is mandatory, but a compromised/misconfigured
            # server response is still untrusted.  Drop out-of-scope points
            # without placing their payload in an error or log.
            if payload_tenant != scope.tenant_id or payload_workspace != scope.workspace_id:
                continue
            if "*" not in allowed and payload_collection not in allowed:
                continue
            if not isinstance(payload_collection, str):
                raise QdrantMalformedResponseError(operation)
            del payload_json  # size validation above is the observable check.
            trusted.append(
                QdrantSearchHit(
                    point_id=str(raw_id),
                    score=float(score),
                    payload=typed_payload,
                )
            )
        return trusted

    def _normalize_point(self, point: Mapping[str, object], operation: str) -> dict[str, object]:
        if not isinstance(point, Mapping):
            raise QdrantValidationError(operation)
        point_id = _validate_id(point.get("point_id"), operation)
        vector = _validate_vector(point.get("vector"), operation, self.limits.max_vector_dimensions)
        payload_obj = point.get("payload")
        payload = _validate_json_mapping(payload_obj, operation)
        for field_name in ("tenant_id", "workspace_id", "collection_id"):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value or len(value) > MAX_SCOPE_VALUE_CHARS:
                raise QdrantValidationError(operation)
            if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
                raise QdrantValidationError(operation)
        self._encode_json(payload, operation, max_bytes=self.limits.max_payload_bytes)
        return {
            "id": point_id,
            "vector": {_DENSE_VECTOR_NAME: vector},
            "payload": payload,
        }

    def _scope(
        self,
        tenant_id: str,
        workspace_id: str,
        allowed_collection_ids: Sequence[str],
        *,
        operation: str,
        require_nonempty: bool,
    ) -> _Scope | None:
        tenant = _validate_scope_value(tenant_id, operation)
        workspace = _validate_scope_value(workspace_id, operation)
        if not isinstance(allowed_collection_ids, Sequence) or isinstance(
            allowed_collection_ids, (str, bytes, bytearray)
        ):
            raise QdrantValidationError(operation)
        if len(allowed_collection_ids) > self.limits.max_collection_filters:
            raise QdrantBoundsError(operation, limit=True)
        normalized: list[str] = []
        for collection_id in allowed_collection_ids:
            if not isinstance(collection_id, str):
                raise QdrantValidationError(operation)
            if collection_id == "*":
                if "*" not in normalized:
                    normalized.append("*")
                continue
            checked = _validate_scope_value(collection_id, operation)
            if checked not in normalized:
                normalized.append(checked)
        if not normalized:
            if require_nonempty:
                raise QdrantValidationError(operation, empty_scope=True)
            return None
        if "*" in normalized:
            normalized = ["*"]
        return _Scope(tenant, workspace, tuple(normalized))

    def _collection_path(self, suffix: str) -> str:
        return f"/collections/{self.collection}{suffix}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        content: bytes = b"",
    ) -> HttpResponse:
        self._ensure_open(operation)
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }
        if self._api_key is not None:
            headers["api-key"] = self._api_key
        timed_out = False
        transport_failed = False
        response: object | None = None
        try:
            response = self._transport.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                content=content,
                timeout=self._timeout,
            )
        except QdrantError:
            raise
        except Exception as exc:
            timed_out = _looks_like_timeout(exc)
            transport_failed = not timed_out
        if timed_out:
            raise QdrantTimeoutError(operation)
        if transport_failed:
            raise QdrantTransportError(operation)
        normalized = _normalize_response(response, operation)
        if len(normalized.content) > self.limits.max_response_bytes:
            raise QdrantResponseTooLargeError(operation)
        if not 200 <= normalized.status_code <= 299:
            raise QdrantStatusError(operation, normalized.status_code)
        return normalized

    def _encode_json(self, value: object, operation: str, *, max_bytes: int) -> bytes:
        try:
            encoded = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError):
            raise QdrantValidationError(operation) from None
        if len(encoded) > max_bytes:
            raise QdrantBoundsError(operation, limit=True)
        return encoded

    def _decode_json(self, content: bytes, operation: str) -> object:
        if not content:
            raise QdrantMalformedResponseError(operation)
        malformed = False
        value: object = None
        try:
            value = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            malformed = True
        if malformed:
            raise QdrantMalformedResponseError(operation)
        return value

    def _ensure_open(self, operation: str) -> None:
        if self._closed:
            raise QdrantClosedError(operation)


def _coerce_transport(transport: HttpTransport | object | None) -> HttpTransport:
    if transport is None:
        return _HttpxTransport()
    if callable(getattr(transport, "request", None)):
        return transport  # type: ignore[return-value]
    # httpx.MockTransport exposes handle_request rather than request.  Keep
    # this compatibility branch lazy and avoid importing httpx at module time.
    if callable(getattr(transport, "handle_request", None)):
        return _HttpxTransport(transport)
    raise QdrantConfigurationError()


def _normalize_response(response: object, operation: str) -> HttpResponse:
    if isinstance(response, HttpResponse):
        return response
    status_code = getattr(response, "status_code", None)
    content = getattr(response, "content", None)
    if type(status_code) is not int or not isinstance(content, (bytes, bytearray, str)):
        raise QdrantMalformedResponseError(operation)
    try:
        return HttpResponse(status_code, content, getattr(response, "headers", {}))
    except (TypeError, ValueError):
        raise QdrantMalformedResponseError(operation) from None


def _validate_base_url(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QdrantConfigurationError()
    candidate = value.strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError
        if parsed.username is not None or parsed.password is not None:
            raise ValueError
        if parsed.query or parsed.fragment:
            raise ValueError
        _ = parsed.port
    except (ValueError, UnicodeError):
        raise QdrantConfigurationError() from None
    return candidate


def _validate_collection_name(value: str | None) -> str:
    if not isinstance(value, str) or not _COLLECTION_NAME.fullmatch(value):
        raise QdrantConfigurationError()
    return value


def _validate_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QdrantConfigurationError()
    converted = float(value)
    if not math.isfinite(converted) or converted <= 0 or converted > 120:
        raise QdrantConfigurationError()
    return converted


def _validate_api_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_SCOPE_VALUE_CHARS:
        raise QdrantConfigurationError()
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise QdrantConfigurationError()
    return value


def _validate_scope_value(value: object, operation: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_SCOPE_VALUE_CHARS:
        raise QdrantValidationError(operation)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise QdrantValidationError(operation)
    return value


def _validate_id(value: object, operation: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_POINT_ID_CHARS:
        raise QdrantValidationError(operation)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise QdrantValidationError(operation)
    return value


def _validate_vector(value: object, operation: str, max_dimensions: int) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise QdrantValidationError(operation)
    if not value or len(value) > max_dimensions:
        raise QdrantBoundsError(operation, limit=True)
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise QdrantValidationError(operation)
        converted = float(item)
        if not math.isfinite(converted):
            raise QdrantValidationError(operation)
        result.append(converted)
    return result


def _validate_limit(value: object, operation: str, maximum: int) -> int:
    if type(value) is not int or value <= 0:
        raise QdrantValidationError(operation)
    if value > maximum:
        raise QdrantBoundsError(operation, limit=True)
    return value


def _validate_json_mapping(value: object, operation: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise QdrantValidationError(operation)
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        json.loads(encoded)
    except (TypeError, ValueError, OverflowError):
        raise QdrantValidationError(operation) from None
    if any(not isinstance(key, str) for key in value):
        raise QdrantValidationError(operation)
    return dict(value)  # type: ignore[return-value]


def _acl_filter(scope: _Scope) -> dict[str, object]:
    must: list[dict[str, object]] = [
        {"key": "tenant_id", "match": {"value": scope.tenant_id}},
        {"key": "workspace_id", "match": {"value": scope.workspace_id}},
    ]
    if "*" not in scope.allowed_collection_ids:
        must.append(
            {
                "key": "collection_id",
                "match": {"any": list(scope.allowed_collection_ids)},
            }
        )
    return {"must": must}


def _extract_hits(value: object, operation: str) -> list[object]:
    if not isinstance(value, Mapping) or "result" not in value:
        raise QdrantMalformedResponseError(operation)
    result = value["result"]
    if isinstance(result, list):
        return result
    if isinstance(result, Mapping) and isinstance(result.get("points"), list):
        return result["points"]
    raise QdrantMalformedResponseError(operation)


def _require_acknowledged_result(value: object, operation: str) -> object:
    if not isinstance(value, Mapping) or "result" not in value:
        raise QdrantMalformedResponseError(operation)
    result = value["result"]
    if result is False or result is None:
        raise QdrantMalformedResponseError(operation)
    if isinstance(result, Mapping) and not result:
        raise QdrantMalformedResponseError(operation)
    if not isinstance(result, (bool, Mapping, str, int)):
        raise QdrantMalformedResponseError(operation)
    return result


def _looks_like_timeout(error: BaseException) -> bool:
    if isinstance(error, TimeoutError):
        return True
    return "timeout" in type(error).__name__.lower()


# The primary name is intentionally explicit; aliases ease migration from
# callers that use adapter/HTTP capitalization without introducing another
# implementation.
QdrantHttpAdapter = QdrantHttpVectorStore
QdrantHTTPAdapter = QdrantHttpVectorStore


__all__ = [
    "HttpResponse",
    "HttpTransport",
    "MAX_COLLECTION_FILTERS",
    "MAX_PAYLOAD_BYTES",
    "MAX_POINTS_PER_UPSERT",
    "MAX_QUERY_BYTES",
    "MAX_QUERY_RESULTS",
    "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES",
    "MAX_VECTOR_DIMENSIONS",
    "QdrantBoundsError",
    "QdrantClosedError",
    "QdrantConfigurationError",
    "QdrantDeleteResult",
    "QdrantDependencyError",
    "QdrantError",
    "QdrantHTTPAdapter",
    "QdrantHTTPError",
    "QdrantHealth",
    "QdrantHttpAdapter",
    "QdrantHttpVectorStore",
    "QdrantMalformedResponseError",
    "QdrantLimits",
    "QdrantResponseError",
    "QdrantResponseTooLargeError",
    "QdrantSearchHit",
    "QdrantStatusError",
    "QdrantTimeoutError",
    "QdrantTransportError",
    "QdrantValidationError",
]
