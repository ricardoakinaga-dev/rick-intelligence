from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
import hashlib
import hmac
import re
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from rick_storage import (
    AwsCredentials,
    CredentialSource,
    InvalidObjectKeyError,
    InvalidScopeError,
    ObjectIntegrityError,
    ObjectNotFoundError,
    ObjectReadLimitExceededError,
    ObjectScope,
    ObjectStoreClosedError,
    ObjectStoreConfigurationError,
    ObjectStorePermissionError,
    ObjectStoreProtocolError,
    ObjectStoreRemoteError,
    ObjectStoreResponseLimitError,
    ObjectStoreTransportError,
    ObjectTooLargeError,
    S3ObjectStore,
)


NOW = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
ACCESS_KEY = "AKIATESTEXAMPLE"
SECRET_KEY = "test-secret-key"


@dataclass
class FakeResponse:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    read_calls: list[int] = field(default_factory=list)
    closed: bool = False
    _offset: int = 0

    def read(self, size: int = -1) -> bytes:
        self.read_calls.append(size)
        if size < 0:
            size = len(self.body) - self._offset
        start = self._offset
        end = min(len(self.body), start + size)
        self._offset = end
        return self.body[start:end]

    def close(self) -> None:
        self.closed = True


@dataclass
class Request:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None


class FakeTransport:
    def __init__(self, *responses: FakeResponse | BaseException) -> None:
        self.responses = list(responses)
        self.requests: list[Request] = []
        self.closed = False

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> FakeResponse:
        self.requests.append(Request(method, url, dict(headers), body))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def scope() -> ObjectScope:
    return ObjectScope("tenant-a", "workspace-a", "source-a")


def make_store(
    transport: FakeTransport,
    *,
    max_object_bytes: int = 50,
    max_read_bytes: int | None = None,
    max_response_bytes: int = 4_096,
    max_list_items: int = 1_000,
    credentials: CredentialSource | None = None,
) -> S3ObjectStore:
    return S3ObjectStore(
        "https://objects.example.test/s3",
        "rick-test",
        "us-east-1",
        AwsCredentials(ACCESS_KEY, SECRET_KEY) if credentials is None else credentials,
        transport,
        key_prefix="private",
        max_object_bytes=max_object_bytes,
        max_read_bytes=max_read_bytes,
        max_response_bytes=max_response_bytes,
        max_list_items=max_list_items,
        clock=lambda: NOW,
    )


def checksum(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def object_headers(payload: bytes, *, include_checksum: bool = True) -> dict[str, str]:
    headers = {"Content-Length": str(len(payload)), "x-amz-meta-rick-size": str(len(payload))}
    if include_checksum:
        headers["x-amz-meta-rick-checksum"] = checksum(payload)
    return headers


def list_xml(*items: tuple[str, int], truncated: bool = False, token: str | None = None) -> bytes:
    contents = "".join(
        f"<Contents><Key>{escape(key)}</Key><Size>{size}</Size></Contents>" for key, size in items
    )
    next_token = f"<NextContinuationToken>{escape(token)}</NextContinuationToken>" if token else ""
    return (
        "<ListBucketResult>"
        f"<IsTruncated>{str(truncated).lower()}</IsTruncated>"
        f"{next_token}{contents}</ListBucketResult>"
    ).encode()


def scoped_remote_key(scope: ObjectScope, key: str) -> str:
    return (
        f"private/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/"
        f"sources/{scope.source_id}/objects/{key}"
    )


def test_put_uses_scoped_url_sigv4_and_metadata(scope: ObjectScope) -> None:
    response = FakeResponse(200)
    transport = FakeTransport(response)
    store = make_store(transport)

    metadata = store.put(scope, "docs/report final.txt", b"abc")

    request = transport.requests[0]
    expected_key = scoped_remote_key(scope, "docs/report final.txt")
    assert request.method == "PUT"
    assert urlsplit(request.url).path == f"/s3/rick-test/{quote(expected_key, safe='/')}"
    assert request.body == b"abc"
    assert request.headers["Content-Length"] == "3"
    assert request.headers["x-amz-meta-rick-checksum"] == "sha256:" + hashlib.sha256(b"abc").hexdigest()
    assert request.headers["x-amz-meta-rick-size"] == "3"
    assert request.headers["x-amz-content-sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert request.headers["x-amz-date"] == "20240102T030405Z"
    assert request.headers["Host"] == "objects.example.test"
    assert request.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIATESTEXAMPLE/")
    assert SECRET_KEY not in repr(request.headers)
    assert metadata.size == 3
    assert metadata.checksum == checksum(b"abc")
    assert response.closed


def test_sigv4_signature_is_independently_reproducible(scope: ObjectScope) -> None:
    transport = FakeTransport(FakeResponse(200))
    store = make_store(transport)
    store.put(scope, "object", b"payload")
    request = transport.requests[0]
    lower = {name.lower(): value for name, value in request.headers.items()}
    authorization = lower["authorization"]
    signature = re.search(r"Signature=([0-9a-f]{64})$", authorization)
    assert signature is not None

    credential_scope = "20240102/us-east-1/s3/aws4_request"
    signed_headers = lower["authorization"].split("SignedHeaders=", 1)[1].split(",", 1)[0]
    canonical_headers = "".join(
        f"{name}:{' '.join(lower[name].strip().split())}\n" for name in signed_headers.split(";")
    )
    payload_hash = hashlib.sha256(b"payload").hexdigest()
    parts = urlsplit(request.url)
    canonical_request = "\n".join(
        (
            "PUT",
            parts.path,
            parts.query,
            canonical_headers,
            signed_headers,
            payload_hash,
        )
    )
    string_to_sign = "\n".join(
        (
            "AWS4-HMAC-SHA256",
            "20240102T030405Z",
            credential_scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        )
    )
    date_key = hmac.new(b"AWS4" + SECRET_KEY.encode(), b"20240102", hashlib.sha256).digest()
    region_key = hmac.new(date_key, b"us-east-1", hashlib.sha256).digest()
    service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
    signing_key = hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()
    expected = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    assert signature.group(1) == expected


def test_head_get_list_delete_and_response_closure(scope: ObjectScope) -> None:
    payload = b"abc"
    key = "docs/report.txt"
    list_body = list_xml((scoped_remote_key(scope, key), 3))
    head_response = FakeResponse(200, object_headers(payload))
    get_response = FakeResponse(200, object_headers(payload), payload)
    list_response = FakeResponse(200, {"Content-Length": str(len(list_body))}, list_body)
    listed_head_response = FakeResponse(200, object_headers(payload))
    delete_response = FakeResponse(204)
    transport = FakeTransport(
        head_response,
        get_response,
        list_response,
        listed_head_response,
        delete_response,
    )
    store = make_store(transport)

    assert store.head(scope, key).checksum == checksum(payload)
    assert store.get(scope, key) == payload
    assert [item.key for item in store.list(scope)] == [key]
    assert store.delete(scope, key) is True
    assert [request.method for request in transport.requests] == ["HEAD", "GET", "GET", "HEAD", "DELETE"]
    assert all(
        response.closed
        for response in (head_response, get_response, list_response, listed_head_response, delete_response)
    )


def test_list_filters_outside_scope_and_uses_exact_prefix(scope: ObjectScope) -> None:
    key = "docs/report.txt"
    in_scope = scoped_remote_key(scope, key)
    outside = "private/tenants/tenant-b/workspaces/workspace-a/sources/source-a/objects/other.txt"
    list_body = list_xml((outside, 5), (in_scope, 3))
    list_response = FakeResponse(
        200,
        {"Content-Length": str(len(list_body))},
        list_body,
    )
    transport = FakeTransport(list_response, FakeResponse(200, object_headers(b"abc")))
    store = make_store(transport)

    items = store.list(scope, prefix="docs/", limit=4)

    assert [item.key for item in items] == [key]
    request = transport.requests[0]
    params = parse_qs(urlsplit(request.url).query)
    assert params["list-type"] == ["2"]
    assert params["max-keys"] == ["4"]
    assert params["prefix"] == [in_scope.removesuffix("docs/report.txt") + "docs/"]
    assert all("tenant-b" not in request.url for request in transport.requests[1:])


def test_list_paginates_with_bounded_page_size(scope: ObjectScope) -> None:
    first_key = "a.txt"
    second_key = "b.txt"
    first_remote = scoped_remote_key(scope, first_key)
    second_remote = scoped_remote_key(scope, second_key)
    first_body = list_xml((first_remote, 1), truncated=True, token="next")
    second_body = list_xml((second_remote, 2))
    first_page = FakeResponse(200, {"Content-Length": str(len(first_body))}, first_body)
    second_page = FakeResponse(200, {"Content-Length": str(len(second_body))}, second_body)
    transport = FakeTransport(
        first_page,
        second_page,
        FakeResponse(200, object_headers(b"a")),
        FakeResponse(200, object_headers(b"bb")),
    )
    store = make_store(transport, max_list_items=2)

    items = store.list(scope, limit=2)

    assert [item.key for item in items] == [first_key, second_key]
    assert [request.method for request in transport.requests] == ["GET", "GET", "HEAD", "HEAD"]
    first_query = parse_qs(urlsplit(transport.requests[0].url).query)
    second_query = parse_qs(urlsplit(transport.requests[1].url).query)
    assert first_query["max-keys"] == ["2"]
    assert second_query["continuation-token"] == ["next"]


def test_get_enforces_declared_and_streamed_read_limits(scope: ObjectScope) -> None:
    declared = FakeResponse(200, object_headers(b"12345"), b"12345")
    transport = FakeTransport(declared)
    store = make_store(transport, max_read_bytes=4)

    with pytest.raises(ObjectReadLimitExceededError):
        store.get(scope, "large", max_bytes=100)
    assert declared.read_calls == []
    assert declared.closed

    streamed = FakeResponse(200, {"x-amz-meta-rick-checksum": checksum(b"12345")}, b"12345")
    transport = FakeTransport(streamed)
    store = make_store(transport, max_read_bytes=4)
    with pytest.raises(ObjectReadLimitExceededError):
        store.get(scope, "large")
    assert streamed.read_calls == [5]
    assert streamed.closed


def test_put_and_list_response_limits_are_bounded(scope: ObjectScope) -> None:
    transport = FakeTransport()
    store = make_store(transport, max_object_bytes=4)

    with pytest.raises(ObjectTooLargeError):
        store.put(scope, "too-large", b"12345")
    assert transport.requests == []

    response = FakeResponse(200, {"Content-Length": "100"}, b"<ListBucketResult/>")
    transport = FakeTransport(response)
    store = make_store(transport, max_response_bytes=10)
    with pytest.raises(ObjectStoreResponseLimitError):
        store.list(scope)
    assert response.read_calls == []
    assert response.closed


def test_checksum_mismatch_and_malformed_metadata_fail_closed(scope: ObjectScope) -> None:
    mismatch = FakeResponse(200, object_headers(b"expected"), b"mismatch")
    transport = FakeTransport(mismatch)
    store = make_store(transport)
    with pytest.raises(ObjectIntegrityError):
        store.get(scope, "object")

    missing = FakeResponse(200, {"Content-Length": "3"})
    transport = FakeTransport(missing)
    store = make_store(transport)
    with pytest.raises(ObjectStoreProtocolError):
        store.head(scope, "object")
    assert mismatch.closed and missing.closed


def test_standard_sha256_checksum_header_is_supported(scope: ObjectScope) -> None:
    payload = b"standard checksum"
    headers = {
        "Content-Length": str(len(payload)),
        "x-amz-checksum-sha256": base64.b64encode(hashlib.sha256(payload).digest()).decode(),
    }
    transport = FakeTransport(FakeResponse(200, headers))
    store = make_store(transport)
    assert store.head(scope, "object").checksum == checksum(payload)


def test_remote_statuses_and_transport_failures_are_safe(scope: ObjectScope) -> None:
    missing = FakeResponse(404)
    transport = FakeTransport(missing)
    store = make_store(transport)
    with pytest.raises(ObjectNotFoundError) as not_found:
        store.get(scope, "missing")
    assert "objects.example.test" not in str(not_found.value)
    assert missing.closed

    denied = FakeResponse(403)
    transport = FakeTransport(denied)
    store = make_store(transport)
    with pytest.raises(ObjectStorePermissionError):
        store.head(scope, "denied")
    assert denied.closed

    unavailable = FakeResponse(503)
    transport = FakeTransport(unavailable)
    store = make_store(transport)
    with pytest.raises(ObjectStoreRemoteError) as remote:
        store.delete(scope, "unavailable")
    assert remote.value.status_code == 503
    assert remote.value.retryable
    assert unavailable.closed

    transport = FakeTransport(RuntimeError("secret endpoint and credentials must not escape"))
    store = make_store(transport)
    with pytest.raises(ObjectStoreTransportError) as transport_error:
        store.get(scope, "object")
    assert "secret" not in str(transport_error.value)


def test_delete_maps_not_found_to_false(scope: ObjectScope) -> None:
    response = FakeResponse(404)
    transport = FakeTransport(response)
    store = make_store(transport)
    assert store.delete(scope, "missing") is False
    assert response.closed


def test_scope_and_remote_key_validation_happen_before_transport(scope: ObjectScope) -> None:
    transport = FakeTransport()
    store = make_store(transport)
    for key in ("../escape", "/absolute", "nested//escape", "nested\\escape"):
        with pytest.raises(InvalidObjectKeyError):
            store.put(scope, key, b"data")
    with pytest.raises(InvalidScopeError):
        ObjectScope("tenant/a", "workspace-a", "source-a")
    assert transport.requests == []


def test_configuration_rejects_insecure_or_ambiguous_endpoints() -> None:
    transport = FakeTransport()
    credentials = AwsCredentials(ACCESS_KEY, SECRET_KEY)
    for endpoint in (
        "ftp://objects.example.test",
        "https://user:pass@objects.example.test",
        "https://objects.example.test?x=1",
    ):
        with pytest.raises(ObjectStoreConfigurationError):
            S3ObjectStore(endpoint, "rick-test", "us-east-1", credentials, transport)
    with pytest.raises(ObjectStoreConfigurationError):
        S3ObjectStore(
            "http://objects.example.test",
            "rick-test",
            "us-east-1",
            credentials,
            transport,
            require_https=True,
        )


def test_close_is_idempotent_and_rejects_operations(scope: ObjectScope) -> None:
    transport = FakeTransport()
    store = make_store(transport)
    store.close()
    store.close()
    assert transport.closed
    assert store.closed
    with pytest.raises(ObjectStoreClosedError):
        store.get(scope, "object")


def test_credentials_are_redacted_and_can_rotate() -> None:
    first = AwsCredentials(ACCESS_KEY, SECRET_KEY, "session-secret")
    second = AwsCredentials("AKIASECOND", "second-secret")
    current = [first]
    transport = FakeTransport(FakeResponse(200), FakeResponse(200))
    store = make_store(transport, credentials=lambda: current[0])

    store.put(ObjectScope("tenant-a", "workspace-a", "source-a"), "one", b"1")
    current[0] = second
    store.put(ObjectScope("tenant-a", "workspace-a", "source-a"), "two", b"2")

    assert "session-secret" not in repr(first)
    assert "second-secret" not in repr(second)
    assert "AKIASECOND" in transport.requests[1].headers["Authorization"]
    assert "session-secret" not in transport.requests[0].headers["Authorization"]
