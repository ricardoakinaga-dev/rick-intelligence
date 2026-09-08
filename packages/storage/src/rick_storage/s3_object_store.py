"""S3-compatible object storage with an injected synchronous HTTP transport.

The adapter intentionally owns the protocol boundary rather than an HTTP
client.  It signs each request with AWS Signature Version 4 using only the
Python standard library, keeps every object below a tenant/workspace/source
namespace, and never reads an unbounded request or response body.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import re
from typing import Final, TypeAlias
from urllib.parse import quote, urlsplit, urlunsplit
from xml.etree import ElementTree

from rick_storage.errors import (
    InvalidLimitError,
    InvalidObjectDataError,
    InvalidObjectKeyError,
    InvalidScopeError,
    ObjectIntegrityError,
    ObjectNotFoundError,
    ObjectReadLimitExceededError,
    ObjectStoreClosedError,
    ObjectStoreConfigurationError,
    ObjectStoreError,
    ObjectStoreIOError,
    ObjectStorePermissionError,
    ObjectStoreProtocolError,
    ObjectStoreRemoteError,
    ObjectStoreResponseLimitError,
    ObjectStoreTransportError,
    ObjectTooLargeError,
)
from rick_storage.models import ObjectMetadata, ObjectPayload, ObjectScope
from rick_storage.object_store import (
    DEFAULT_MAX_OBJECT_BYTES,
    DEFAULT_MAX_LIST_ITEMS,
    MAX_CONFIGURED_BYTES,
    MAX_CONFIGURED_LIST_ITEMS,
)
from rick_storage.protocols import SyncHttpResponse, SyncHttpTransport
from rick_storage.validation import (
    MAX_OBJECT_KEY_BYTES,
    validate_key_prefix,
    validate_object_key,
    validate_scope_component,
)

DEFAULT_MAX_RESPONSE_BYTES: Final = 4 * 1024 * 1024
MAX_CONFIGURED_RESPONSE_BYTES: Final = 64 * 1024 * 1024
S3_MAX_LIST_KEYS: Final = 1_000
_IO_CHUNK_BYTES: Final = 64 * 1024
_MAX_CONTINUATION_TOKEN_BYTES: Final = 2_048
_MAX_ENDPOINT_BYTES: Final = 2_048
_MAX_REGION_BYTES: Final = 128
_MAX_BUCKET_BYTES: Final = 63
_CHECKSUM_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_DIGEST_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL_RE: Final = re.compile(r"^(0|[1-9][0-9]*)$")
_BUCKET_RE: Final = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


@dataclass(frozen=True, slots=True, repr=False)
class AwsCredentials:
    """Credentials supplied by the composition root, never read from env.

    The custom representation prevents accidental logging of the secret or
    session token.  A callable credential source is also accepted by
    :class:`S3ObjectStore` so rotations can be handled outside this package.
    """

    access_key_id: str
    secret_access_key: str
    session_token: str | None = None

    def __post_init__(self) -> None:
        _validate_credential_text(self.access_key_id, maximum=256)
        if any(character.isspace() or character in "/,;" for character in self.access_key_id):
            raise ObjectStoreConfigurationError()
        _validate_credential_text(self.secret_access_key, maximum=512)
        if self.session_token is not None:
            _validate_credential_text(self.session_token, maximum=8_192)

    def __repr__(self) -> str:
        token = "set" if self.session_token else "none"
        return (
            "AwsCredentials(access_key_id=<redacted>, "
            f"secret_access_key=<redacted>, session_token={token})"
        )


CredentialSource: TypeAlias = AwsCredentials | Callable[[], AwsCredentials]


class S3ObjectStore:
    """A scope-aware S3-compatible implementation of the object-store port.

    ``transport`` is deliberately injected.  It must provide a synchronous
    ``request`` method and return a response whose ``read`` method honors the
    requested maximum.  The adapter passes complete bounded byte bodies to
    ``request`` and closes every response before returning.
    """

    def __init__(
        self,
        endpoint_url: str,
        bucket: str,
        region: str,
        credentials: CredentialSource,
        transport: SyncHttpTransport,
        *,
        key_prefix: str = "",
        max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES,
        max_read_bytes: int | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_list_items: int = DEFAULT_MAX_LIST_ITEMS,
        require_https: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(require_https, bool):
            raise ObjectStoreConfigurationError()
        endpoint = _validate_endpoint(endpoint_url, require_https=require_https)
        self._endpoint = endpoint
        self._bucket = _validate_bucket(bucket)
        self._region = _validate_region(region)
        if not isinstance(credentials, AwsCredentials) and not callable(credentials):
            raise ObjectStoreConfigurationError()
        try:
            request = getattr(transport, "request", None)
        except Exception as exc:
            raise ObjectStoreConfigurationError() from exc
        if not callable(request):
            raise ObjectStoreConfigurationError()

        self._credentials = credentials
        self._transport = transport
        self._key_prefix = _validate_base_prefix(key_prefix)
        self._max_object_bytes = _positive_bounded_limit(max_object_bytes, MAX_CONFIGURED_BYTES)
        self._max_read_bytes = _positive_bounded_limit(
            self._max_read_bytes_default(max_object_bytes, max_read_bytes),
            MAX_CONFIGURED_BYTES,
        )
        self._max_response_bytes = _positive_bounded_limit(
            max_response_bytes,
            MAX_CONFIGURED_RESPONSE_BYTES,
        )
        self._max_list_items = _positive_bounded_limit(max_list_items, MAX_CONFIGURED_LIST_ITEMS)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._closed = False

    @staticmethod
    def _max_read_bytes_default(max_object_bytes: int, requested: int | None) -> int:
        return max_object_bytes if requested is None else requested

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def region(self) -> str:
        return self._region

    @property
    def key_prefix(self) -> str:
        return self._key_prefix

    @property
    def max_object_bytes(self) -> int:
        return self._max_object_bytes

    @property
    def max_read_bytes(self) -> int:
        return self._max_read_bytes

    @property
    def max_response_bytes(self) -> int:
        return self._max_response_bytes

    @property
    def closed(self) -> bool:
        return self._closed

    def health_check(self) -> bool:
        """Check bucket reachability with a bounded, bodyless request."""

        if self._closed:
            return False
        try:
            with self._response(
                operation="health",
                method="HEAD",
                url=self._bucket_url([]),
                headers={},
                body=None,
                accepted=(200,),
            ):
                return True
        except ObjectStoreError:
            return False

    def put(self, scope: ObjectScope, key: str, data: ObjectPayload) -> ObjectMetadata:
        """Upload a bounded object and return its verified client metadata."""

        self._ensure_open()
        scope = _validated_scope(scope)
        key = validate_object_key(key)
        remote_key = self._remote_key(scope, key)
        body = _read_payload(data, self._max_object_bytes)
        checksum = hashlib.sha256(body).hexdigest()
        metadata = ObjectMetadata(
            scope=scope,
            key=key,
            size=len(body),
            checksum=f"sha256:{checksum}",
        )
        headers = {
            "Content-Length": str(metadata.size),
            "Content-Type": "application/octet-stream",
            "x-amz-meta-rick-checksum": metadata.checksum,
            "x-amz-meta-rick-size": str(metadata.size),
        }
        with self._response(
            operation="put",
            method="PUT",
            url=self._object_url(remote_key),
            headers=headers,
            body=body,
            accepted=(200, 201, 204),
        ):
            return metadata

    def get(self, scope: ObjectScope, key: str, *, max_bytes: int | None = None) -> bytes:
        """Download one object with a bounded read and checksum verification."""

        self._ensure_open()
        scope = _validated_scope(scope)
        key = validate_object_key(key)
        limit = self._read_limit(max_bytes)
        with self._response(
            operation="get",
            method="GET",
            url=self._object_url(self._remote_key(scope, key)),
            headers={},
            body=None,
            accepted=(200,),
        ) as response:
            headers = _response_headers(response, operation="get")
            declared_size = _object_size(headers, operation="get", required=False)
            if declared_size is not None and declared_size > limit:
                raise ObjectReadLimitExceededError(limit=limit, size=declared_size)
            expected_checksum = _object_checksum(headers, operation="get", required=False)
            payload = _read_response_body(
                response,
                limit=limit,
                operation="get",
                declared_size=declared_size,
                response_limit=False,
            )
            if expected_checksum is not None:
                actual_checksum = hashlib.sha256(payload).hexdigest()
                if actual_checksum != expected_checksum.removeprefix("sha256:"):
                    raise ObjectIntegrityError()
            return payload

    def read(self, scope: ObjectScope, key: str, *, max_bytes: int | None = None) -> bytes:
        """Readable-name alias for :meth:`get`."""

        return self.get(scope, key, max_bytes=max_bytes)

    def head(self, scope: ObjectScope, key: str) -> ObjectMetadata:
        """Read remote size/checksum metadata without downloading the object."""

        self._ensure_open()
        scope = _validated_scope(scope)
        key = validate_object_key(key)
        with self._response(
            operation="head",
            method="HEAD",
            url=self._object_url(self._remote_key(scope, key)),
            headers={},
            body=None,
            accepted=(200,),
        ) as response:
            headers = _response_headers(response, operation="head")
            size = _object_size(headers, operation="head", required=True)
            checksum = _object_checksum(headers, operation="head", required=True)
            try:
                return ObjectMetadata(scope=scope, key=key, size=size, checksum=checksum)
            except (TypeError, ValueError, ObjectStoreError) as exc:
                raise ObjectStoreProtocolError(operation="head") from exc

    def list(
        self,
        scope: ObjectScope,
        *,
        prefix: str = "",
        limit: int | None = None,
    ) -> tuple[ObjectMetadata, ...]:
        """List and head only objects below one exact scope namespace."""

        self._ensure_open()
        scope = _validated_scope(scope)
        prefix = validate_key_prefix(prefix)
        result_limit = self._list_limit(limit)
        if result_limit == 0:
            return ()

        scope_prefix = self._scope_prefix(scope)
        requested_remote_prefix = scope_prefix + prefix
        candidates: list[str] = []
        seen: set[str] = set()
        continuation: str | None = None
        page_count = 0
        maximum_pages = (result_limit + S3_MAX_LIST_KEYS - 1) // S3_MAX_LIST_KEYS + 1

        while len(candidates) < result_limit:
            page_count += 1
            if page_count > maximum_pages:
                raise ObjectStoreProtocolError(operation="list")
            page_limit = min(S3_MAX_LIST_KEYS, result_limit - len(candidates))
            query: list[tuple[str, str]] = [
                ("list-type", "2"),
                ("max-keys", str(page_limit)),
                ("prefix", requested_remote_prefix),
            ]
            if continuation is not None:
                query.append(("continuation-token", continuation))
            with self._response(
                operation="list",
                method="GET",
                url=self._bucket_url(query),
                headers={},
                body=None,
                accepted=(200,),
            ) as response:
                payload = _read_response_body(
                    response,
                    limit=self._max_response_bytes,
                    operation="list",
                    declared_size=_declared_response_size(response, operation="list"),
                    response_limit=True,
                )
            page_keys, is_truncated, next_token = _parse_list_page(
                payload,
                scope_prefix=scope_prefix,
                requested_prefix=prefix,
                operation="list",
            )
            for candidate in page_keys:
                if candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
                    if len(candidates) >= result_limit:
                        break
            if len(candidates) >= result_limit or not is_truncated:
                break
            if next_token is None or next_token == continuation:
                raise ObjectStoreProtocolError(operation="list")
            continuation = next_token

        metadata_items: list[ObjectMetadata] = []
        for key in candidates[:result_limit]:
            try:
                metadata_items.append(self.head(scope, key))
            except ObjectNotFoundError:
                # A concurrent delete between ListObjectsV2 and HEAD is safe to
                # represent as an absent item in this read-only listing.
                continue
        metadata_items.sort(key=lambda item: item.key)
        return tuple(metadata_items)

    def list_objects(
        self,
        scope: ObjectScope,
        *,
        prefix: str = "",
        limit: int | None = None,
    ) -> tuple[ObjectMetadata, ...]:
        """Explicit alias for callers that avoid the built-in name ``list``."""

        return self.list(scope, prefix=prefix, limit=limit)

    def delete(self, scope: ObjectScope, key: str) -> bool:
        """Delete one scoped object; absent objects return ``False``."""

        self._ensure_open()
        scope = _validated_scope(scope)
        key = validate_object_key(key)
        response = self._send(
            operation="delete",
            method="DELETE",
            url=self._object_url(self._remote_key(scope, key)),
            headers={},
            body=None,
        )
        try:
            status = _response_status(response, operation="delete")
            if status == 404:
                return False
            _expect_status(status, operation="delete", accepted=(200, 204), max_object_bytes=None)
            return True
        finally:
            _close_response(response)

    def close(self) -> None:
        """Close the injected transport and reject future adapter operations."""

        if self._closed:
            return
        self._closed = True
        close = getattr(self._transport, "close", None)
        if not callable(close):
            return
        try:
            close()
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreTransportError(operation="close") from exc

    def __enter__(self) -> "S3ObjectStore":
        self._ensure_open()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ObjectStoreClosedError()

    def _read_limit(self, requested: int | None) -> int:
        if requested is None:
            return self._max_read_bytes
        return min(_positive_limit(requested), self._max_read_bytes)

    def _list_limit(self, requested: int | None) -> int:
        if requested is None:
            return self._max_list_items
        if isinstance(requested, bool) or not isinstance(requested, int) or requested < 0:
            raise InvalidLimitError()
        return min(requested, self._max_list_items)

    def _scope_prefix(self, scope: ObjectScope) -> str:
        return (
            f"{self._key_prefix}tenants/{scope.tenant_id}/"
            f"workspaces/{scope.workspace_id}/sources/{scope.source_id}/objects/"
        )

    def _remote_key(self, scope: ObjectScope, key: str) -> str:
        remote_key = self._scope_prefix(scope) + key
        if len(remote_key.encode("utf-8")) > MAX_OBJECT_KEY_BYTES:
            raise InvalidObjectKeyError()
        return remote_key

    def _bucket_url(self, query: list[tuple[str, str]]) -> str:
        return self._url_for_path(f"/{quote(self._bucket, safe='-._~')}", query)

    def _object_url(self, remote_key: str) -> str:
        return self._url_for_path(
            f"/{quote(self._bucket, safe='-._~')}/{quote(remote_key, safe='/-._~')}",
            (),
        )

    def _url_for_path(self, suffix: str, query: Sequence[tuple[str, str]]) -> str:
        endpoint = urlsplit(self._endpoint)
        endpoint_path = endpoint.path.rstrip("/")
        raw_path = f"{endpoint_path}{suffix}" or "/"
        encoded_path = quote(raw_path, safe="/%:@-._~")
        canonical_query = _canonical_query(query)
        return urlunsplit((endpoint.scheme, endpoint.netloc, encoded_path, canonical_query, ""))

    @contextmanager
    def _response(
        self,
        *,
        operation: str,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        accepted: tuple[int, ...],
    ) -> Iterator[SyncHttpResponse]:
        response = self._send(
            operation=operation,
            method=method,
            url=url,
            headers=headers,
            body=body,
        )
        try:
            status = _response_status(response, operation=operation)
            _expect_status(
                status,
                operation=operation,
                accepted=accepted,
                max_object_bytes=self._max_object_bytes,
            )
            yield response
        finally:
            _close_response(response)

    def _send(
        self,
        *,
        operation: str,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> SyncHttpResponse:
        self._ensure_open()
        credentials = self._resolve_credentials()
        try:
            signed_headers = _sign_request(
                method=method,
                url=url,
                headers=headers,
                body=body,
                credentials=credentials,
                region=self._region,
                service="s3",
                clock=self._clock,
            )
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreConfigurationError() from exc
        try:
            response = self._transport.request(method, url, headers=signed_headers, body=body)
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreTransportError(operation=operation) from exc
        if response is None:
            raise ObjectStoreProtocolError(operation=operation)
        try:
            close = getattr(response, "close", None)
        except Exception as exc:
            raise ObjectStoreProtocolError(operation=operation) from exc
        if not callable(close):
            raise ObjectStoreProtocolError(operation=operation)
        return response

    def _resolve_credentials(self) -> AwsCredentials:
        try:
            credentials = self._credentials() if callable(self._credentials) else self._credentials
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreConfigurationError() from exc
        if not isinstance(credentials, AwsCredentials):
            raise ObjectStoreConfigurationError()
        return credentials


S3CompatibleObjectStore = S3ObjectStore


def _validate_endpoint(value: object, *, require_https: bool) -> str:
    if not isinstance(value, str) or not value:
        raise ObjectStoreConfigurationError()
    try:
        if len(value.encode("utf-8")) > _MAX_ENDPOINT_BYTES:
            raise ObjectStoreConfigurationError()
    except UnicodeEncodeError as exc:
        raise ObjectStoreConfigurationError() from exc
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or parts.hostname is None
        ):
            raise ObjectStoreConfigurationError()
        _ = parts.port
    except ObjectStoreError:
        raise
    except (TypeError, ValueError) as exc:
        raise ObjectStoreConfigurationError() from exc
    if require_https and parts.scheme != "https":
        raise ObjectStoreConfigurationError()
    if any(
        ord(character) < 0x20 or ord(character) == 0x7F or character.isspace()
        for character in value
    ):
        raise ObjectStoreConfigurationError()
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _validate_bucket(value: object) -> str:
    if not isinstance(value, str):
        raise ObjectStoreConfigurationError()
    try:
        length = len(value.encode("ascii"))
    except UnicodeEncodeError as exc:
        raise ObjectStoreConfigurationError() from exc
    if length < 3 or length > _MAX_BUCKET_BYTES or _BUCKET_RE.fullmatch(value) is None:
        raise ObjectStoreConfigurationError()
    if ".." in value or ".-" in value or "-." in value:
        raise ObjectStoreConfigurationError()
    return value


def _validate_region(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ObjectStoreConfigurationError()
    try:
        if len(value.encode("utf-8")) > _MAX_REGION_BYTES:
            raise ObjectStoreConfigurationError()
    except UnicodeEncodeError as exc:
        raise ObjectStoreConfigurationError() from exc
    if any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or character.isspace()
        or character in "/\\"
        for character in value
    ):
        raise ObjectStoreConfigurationError()
    return value


def _validate_base_prefix(value: object) -> str:
    if value == "":
        return ""
    prefix = validate_key_prefix(value)
    return prefix if prefix.endswith("/") else f"{prefix}/"


def _validate_credential_text(value: object, *, maximum: int) -> None:
    if not isinstance(value, str) or not value:
        raise ObjectStoreConfigurationError()
    try:
        if len(value.encode("utf-8")) > maximum:
            raise ObjectStoreConfigurationError()
    except UnicodeEncodeError as exc:
        raise ObjectStoreConfigurationError() from exc
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ObjectStoreConfigurationError()


def _validated_scope(scope: object) -> ObjectScope:
    if not isinstance(scope, ObjectScope):
        raise InvalidScopeError()
    validate_scope_component(scope.tenant_id)
    validate_scope_component(scope.workspace_id)
    validate_scope_component(scope.source_id)
    return scope


def _positive_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidLimitError()
    return value


def _positive_bounded_limit(value: object, maximum: int) -> int:
    candidate = _positive_limit(value)
    if candidate > maximum:
        raise InvalidLimitError()
    return candidate


def _read_payload(data: ObjectPayload, limit: int) -> bytes:
    if isinstance(data, (bytes, bytearray, memoryview)):
        try:
            view = memoryview(data)
            if view.nbytes > limit:
                raise ObjectTooLargeError(limit=limit, observed=view.nbytes)
            return view.tobytes()
        except ObjectStoreError:
            raise
        except (TypeError, ValueError) as exc:
            raise InvalidObjectDataError() from exc

    reader = getattr(data, "read", None)
    if not callable(reader):
        raise InvalidObjectDataError()
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            requested = min(_IO_CHUNK_BYTES, limit - total + 1)
            chunk = reader(requested)
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise InvalidObjectDataError()
            try:
                chunk_view = memoryview(chunk)
            except (TypeError, ValueError) as exc:
                raise InvalidObjectDataError() from exc
            size = chunk_view.nbytes
            if size == 0:
                break
            if size > limit - total:
                raise ObjectTooLargeError(limit=limit, observed=total + size)
            chunks.append(chunk_view.tobytes())
            total += size
    except ObjectStoreError:
        raise
    except Exception as exc:
        raise ObjectStoreIOError(operation="put") from exc
    return b"".join(chunks)


def _canonical_query(query: Sequence[tuple[str, str]]) -> str:
    encoded = [(_aws_quote(name), _aws_quote(value)) for name, value in query]
    encoded.sort()
    return "&".join(f"{name}={value}" for name, value in encoded)


def _aws_quote(value: str) -> str:
    return quote(value, safe="-_.~")


def _normalise_header_value(value: str) -> str:
    return " ".join(value.strip().split())


def _sign_request(
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    credentials: AwsCredentials,
    region: str,
    service: str,
    clock: Callable[[], datetime],
) -> dict[str, str]:
    request_headers = _validated_headers(headers)
    parts = urlsplit(url)
    host = parts.netloc
    if not host or parts.fragment:
        raise ObjectStoreConfigurationError()
    request_headers["host"] = host
    payload = b"" if body is None else body
    if not isinstance(payload, bytes):
        raise ObjectStoreConfigurationError()
    try:
        current = clock()
        if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
            raise ObjectStoreConfigurationError()
        current = current.astimezone(timezone.utc)
    except ObjectStoreError:
        raise
    except Exception as exc:
        raise ObjectStoreConfigurationError() from exc
    amz_date = current.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = current.strftime("%Y%m%d")
    request_headers["x-amz-content-sha256"] = hashlib.sha256(payload).hexdigest()
    request_headers["x-amz-date"] = amz_date
    if credentials.session_token is not None:
        request_headers["x-amz-security-token"] = credentials.session_token

    canonical_headers, signed_headers = _canonical_headers(request_headers)
    canonical_uri = parts.path or "/"
    canonical_query = parts.query
    canonical_request = "\n".join(
        (
            method.upper(),
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            request_headers["x-amz-content-sha256"],
        )
    )
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        (
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        )
    )
    signing_key = _signing_key(credentials.secret_access_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    request_headers["authorization"] = (
        "AWS4-HMAC-SHA256 "
        f"Credential={credentials.access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return _restore_header_case(request_headers)


def _validated_headers(headers: Mapping[str, str]) -> dict[str, str]:
    try:
        items = headers.items()
    except Exception as exc:
        raise ObjectStoreConfigurationError() from exc
    result: dict[str, str] = {}
    try:
        for name, value in items:
            if not isinstance(name, str) or not isinstance(value, str) or not name:
                raise ObjectStoreConfigurationError()
            if any(ord(character) < 0x20 or ord(character) == 0x7F for character in name + value):
                raise ObjectStoreConfigurationError()
            lower_name = name.lower()
            normalised = _normalise_header_value(value)
            if lower_name in result and result[lower_name] != normalised:
                raise ObjectStoreConfigurationError()
            result[lower_name] = normalised
    except ObjectStoreError:
        raise
    except Exception as exc:
        raise ObjectStoreConfigurationError() from exc
    return result


def _canonical_headers(headers: Mapping[str, str]) -> tuple[str, str]:
    names = sorted(headers)
    canonical = "".join(f"{name}:{_normalise_header_value(headers[name])}\n" for name in names)
    return canonical, ";".join(names)


def _restore_header_case(headers: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in headers.items():
        if name == "authorization":
            result["Authorization"] = value
        elif name == "host":
            result["Host"] = value
        elif name == "content-length":
            result["Content-Length"] = value
        elif name == "content-type":
            result["Content-Type"] = value
        else:
            result[name] = value
    return result


def _signing_key(secret: str, date_stamp: str, region: str, service: str) -> bytes:
    date_key = hmac.new(("AWS4" + secret).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode("utf-8"), hashlib.sha256).digest()
    service_key = hmac.new(region_key, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def _response_status(response: object, *, operation: str) -> int:
    try:
        value = getattr(response, "status_code", None)
        if value is None:
            value = getattr(response, "status", None)
    except Exception as exc:
        raise ObjectStoreProtocolError(operation=operation) from exc
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise ObjectStoreProtocolError(operation=operation)
    return value


def _response_headers(response: object, *, operation: str) -> dict[str, str]:
    raw_headers = getattr(response, "headers", None)
    try:
        items = raw_headers.items()
    except Exception as exc:
        raise ObjectStoreProtocolError(operation=operation) from exc
    normalized: dict[str, str] = {}
    try:
        for name, value in items:
            if not isinstance(name, str) or not isinstance(value, str) or not name:
                raise ObjectStoreProtocolError(operation=operation)
            lower_name = name.lower()
            normalised = _normalise_header_value(value)
            if lower_name in normalized and normalized[lower_name] != normalised:
                raise ObjectStoreProtocolError(operation=operation)
            normalized[lower_name] = normalised
    except ObjectStoreError:
        raise
    except Exception as exc:
        raise ObjectStoreProtocolError(operation=operation) from exc
    return normalized


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    return headers.get(name.lower())


def _declared_response_size(response: object, *, operation: str) -> int | None:
    headers = _response_headers(response, operation=operation)
    return _object_size(headers, operation=operation, required=False)


def _object_size(headers: Mapping[str, str], *, operation: str, required: bool) -> int | None:
    content_length = _decimal_header(_header_value(headers, "content-length"), operation=operation)
    metadata_size = _decimal_header(
        _header_value(headers, "x-amz-meta-rick-size"),
        operation=operation,
    )
    if content_length is not None and metadata_size is not None and content_length != metadata_size:
        raise ObjectStoreProtocolError(operation=operation)
    size = metadata_size if metadata_size is not None else content_length
    if required and size is None:
        raise ObjectStoreProtocolError(operation=operation)
    return size


def _decimal_header(value: str | None, *, operation: str) -> int | None:
    if value is None:
        return None
    if len(value) > 32 or _DECIMAL_RE.fullmatch(value) is None:
        raise ObjectStoreProtocolError(operation=operation)
    try:
        return int(value, 10)
    except ValueError as exc:
        raise ObjectStoreProtocolError(operation=operation) from exc


def _object_checksum(headers: Mapping[str, str], *, operation: str, required: bool) -> str | None:
    custom = _header_value(headers, "x-amz-meta-rick-checksum")
    if custom is None:
        custom = _header_value(headers, "x-amz-meta-rick-sha256")
    if custom is not None:
        if _CHECKSUM_RE.fullmatch(custom):
            return custom
        if _DIGEST_RE.fullmatch(custom):
            return f"sha256:{custom}"
        raise ObjectStoreProtocolError(operation=operation)

    standard = _header_value(headers, "x-amz-checksum-sha256")
    if standard is not None:
        try:
            digest = base64.b64decode(standard.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
            raise ObjectStoreProtocolError(operation=operation) from exc
        if len(digest) != hashlib.sha256().digest_size:
            raise ObjectStoreProtocolError(operation=operation)
        return f"sha256:{digest.hex()}"
    if required:
        raise ObjectStoreProtocolError(operation=operation)
    return None


def _read_response_body(
    response: object,
    *,
    limit: int,
    operation: str,
    declared_size: int | None,
    response_limit: bool,
) -> bytes:
    reader = getattr(response, "read", None)
    if not callable(reader):
        raise ObjectStoreProtocolError(operation=operation)
    if declared_size is not None and declared_size > limit:
        if response_limit:
            raise ObjectStoreResponseLimitError(
                limit=limit,
                observed=declared_size,
                operation=operation,
            )
        raise ObjectReadLimitExceededError(limit=limit, size=declared_size)
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            requested = min(_IO_CHUNK_BYTES, limit - total + 1)
            if requested <= 0:
                error = (
                    ObjectStoreResponseLimitError(
                        limit=limit,
                        observed=total,
                        operation=operation,
                    )
                    if response_limit
                    else ObjectReadLimitExceededError(limit=limit, size=total)
                )
                raise error
            chunk = reader(requested)
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise ObjectStoreProtocolError(operation=operation)
            try:
                chunk_view = memoryview(chunk)
            except (TypeError, ValueError) as exc:
                raise ObjectStoreProtocolError(operation=operation) from exc
            size = chunk_view.nbytes
            if size == 0:
                break
            if size > limit - total:
                if response_limit:
                    raise ObjectStoreResponseLimitError(
                        limit=limit,
                        observed=total + size,
                        operation=operation,
                    )
                raise ObjectReadLimitExceededError(limit=limit, size=total + size)
            chunks.append(chunk_view.tobytes())
            total += size
    except ObjectStoreError:
        raise
    except Exception as exc:
        raise ObjectStoreTransportError(operation=operation) from exc
    if declared_size is not None and total != declared_size:
        raise ObjectStoreProtocolError(operation=operation)
    return b"".join(chunks)


def _parse_list_page(
    payload: bytes,
    *,
    scope_prefix: str,
    requested_prefix: str,
    operation: str,
) -> tuple[list[str], bool, str | None]:
    if b"<!doctype" in payload.lower() or b"<!entity" in payload.lower():
        raise ObjectStoreProtocolError(operation=operation)
    try:
        root = ElementTree.fromstring(payload)
    except (ElementTree.ParseError, ValueError) as exc:
        raise ObjectStoreProtocolError(operation=operation) from exc
    if _xml_local_name(root.tag) != "ListBucketResult":
        raise ObjectStoreProtocolError(operation=operation)

    candidates: list[str] = []
    for content in root:
        if _xml_local_name(content.tag) != "Contents":
            continue
        key_value = _xml_child_text(content, "Key")
        size_value = _xml_child_text(content, "Size")
        if key_value is None or size_value is None:
            raise ObjectStoreProtocolError(operation=operation)
        if _decimal_header(size_value, operation=operation) is None:
            raise ObjectStoreProtocolError(operation=operation)
        if not key_value.startswith(scope_prefix):
            continue
        relative = key_value[len(scope_prefix) :]
        if requested_prefix and not relative.startswith(requested_prefix):
            continue
        try:
            validate_object_key(relative)
        except InvalidObjectKeyError:
            continue
        candidates.append(relative)

    truncated_value = _xml_child_text(root, "IsTruncated")
    if truncated_value is None:
        is_truncated = False
    elif truncated_value.strip().lower() == "true":
        is_truncated = True
    elif truncated_value.strip().lower() == "false":
        is_truncated = False
    else:
        raise ObjectStoreProtocolError(operation=operation)
    token = _xml_child_text(root, "NextContinuationToken") if is_truncated else None
    if token is not None:
        token = token.strip()
        if not token or len(token.encode("utf-8")) > _MAX_CONTINUATION_TOKEN_BYTES:
            raise ObjectStoreProtocolError(operation=operation)
    return candidates, is_truncated, token


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_child_text(parent: ElementTree.Element, name: str) -> str | None:
    for child in parent:
        if _xml_local_name(child.tag) == name:
            return child.text
    return None


def _expect_status(
    status: int,
    *,
    operation: str,
    accepted: tuple[int, ...],
    max_object_bytes: int | None,
) -> None:
    if status in accepted:
        return
    if status == 404:
        raise ObjectNotFoundError(operation=operation)
    if status in {401, 403}:
        raise ObjectStorePermissionError(operation=operation)
    if status == 413 and max_object_bytes is not None and operation == "put":
        raise ObjectTooLargeError(limit=max_object_bytes)
    raise ObjectStoreRemoteError(status_code=status, operation=operation)


def _close_response(response: object) -> None:
    close = getattr(response, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        # The response is already unusable after the operation.  Do not mask a
        # more useful typed status/read error with client-library cleanup text.
        return


__all__ = [
    "AwsCredentials",
    "CredentialSource",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "MAX_CONFIGURED_RESPONSE_BYTES",
    "S3CompatibleObjectStore",
    "S3ObjectStore",
]
