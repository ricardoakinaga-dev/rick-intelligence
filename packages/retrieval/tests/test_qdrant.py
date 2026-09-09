"""Hermetic contract/security tests for the live Qdrant HTTP adapter."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rick_retrieval.qdrant import (  # noqa: E402
    HttpResponse,
    QdrantBoundsError,
    QdrantClosedError,
    QdrantConfigurationError,
    QdrantCircuitOpenError,
    QdrantHttpVectorStore,
    QdrantLimits,
    QdrantMalformedResponseError,
    QdrantResponseTooLargeError,
    QdrantStatusError,
    QdrantTimeoutError,
    QdrantValidationError,
)


class FakeTransport:
    """In-memory synchronous transport; it never opens a socket."""

    def __init__(self, handler: Callable[[str, str, Mapping[str, str], bytes], HttpResponse]) -> None:
        self.handler = handler
        self.requests: list[tuple[str, str, Mapping[str, str], bytes]] = []
        self.close_calls = 0

    def request(self, method: str, url: str, *, headers, content, timeout: float) -> HttpResponse:
        self.requests.append((method, url, headers, content))
        return self.handler(method, url, headers, content)

    def close(self) -> None:
        self.close_calls += 1


def _json_response(value: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status, json.dumps(value).encode("utf-8"))


def _point(point_id: str = "p-1", *, text: str = "allowed text") -> dict[str, object]:
    return {
        "point_id": point_id,
        "vector": [1.0, 0.0],
        "payload": {
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "collection_id": "public",
            "document_id": "doc-1",
            "chunk_id": point_id,
            "text": text,
        },
    }


def test_configuration_requires_explicit_destination_and_collection() -> None:
    transport = FakeTransport(lambda *_: _json_response({"result": True}))
    with pytest.raises(QdrantConfigurationError):
        QdrantHttpVectorStore(collection="public", transport=transport)
    with pytest.raises(QdrantConfigurationError):
        QdrantHttpVectorStore(base_url="http://qdrant.test", transport=transport)
    with pytest.raises(QdrantConfigurationError):
        QdrantHttpVectorStore(
            base_url="http://user:password@qdrant.test",
            collection="public",
            transport=transport,
        )
    assert transport.requests == []


def test_health_upsert_query_search_delete_and_deterministic_close() -> None:
    def handler(method: str, url: str, headers: Mapping[str, str], content: bytes) -> HttpResponse:
        assert headers["accept"] == "application/json"
        if url.endswith("/healthz"):
            return HttpResponse(200, b"healthz check passed")
        if url.endswith("/points?wait=true"):
            body = json.loads(content)
            assert body["points"][0]["vector"] == {"dense": [1.0, 0.0]}
            assert body["points"][0]["payload"]["tenant_id"] == "tenant-a"
            return _json_response({"result": True, "status": "acknowledged"})
        if url.endswith("/points/query") or url.endswith("/points/search"):
            body = json.loads(content)
            assert body["filter"]["must"][:3] == [
                {"key": "tenant_id", "match": {"value": "tenant-a"}},
                {"key": "workspace_id", "match": {"value": "workspace-a"}},
                {"key": "collection_id", "match": {"any": ["public"]}},
            ]
            return _json_response(
                {
                    "result": {
                        "points": [
                            {
                                "id": "allowed",
                                "score": 0.9,
                                "payload": {
                                    "tenant_id": "tenant-a",
                                    "workspace_id": "workspace-a",
                                    "collection_id": "public",
                                    "text": "allowed text",
                                },
                            },
                            {
                                "id": "foreign-collection",
                                "score": 1.0,
                                "payload": {
                                    "tenant_id": "tenant-a",
                                    "workspace_id": "workspace-a",
                                    "collection_id": "private",
                                    "text": "PRIVATE-SECRET-COLLECTION",
                                },
                            },
                            {
                                "id": "foreign-workspace",
                                "score": 1.0,
                                "payload": {
                                    "tenant_id": "tenant-a",
                                    "workspace_id": "workspace-b",
                                    "collection_id": "public",
                                    "text": "PRIVATE-SECRET-WORKSPACE",
                                },
                            },
                        ]
                    }
                }
            )
        if url.endswith("/points/delete"):
            body = json.loads(content)
            keys = [condition["key"] for condition in body["filter"]["must"]]
            assert keys == ["tenant_id", "workspace_id", "collection_id", "document_id"]
            return _json_response({"result": {"operation_id": 7, "status": "acknowledged"}})
        raise AssertionError(f"unexpected route {method} {url}")

    transport = FakeTransport(handler)
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        api_key="qdrant-secret",
        transport=transport,
    )

    assert bool(store.health()) is True
    assert store.upsert_points([_point()]) == 1
    hits = store.query(
        [1.0, 0.0],
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        allowed_collection_ids=["public"],
        limit=5,
    )
    assert [hit.point_id for hit in hits] == ["allowed"]
    assert "PRIVATE-SECRET" not in repr(hits)

    search_hits = store.search(
        vector=[1.0, 0.0],
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        allowed_collection_ids=["public"],
        limit=5,
    )
    assert [hit.point_id for hit in search_hits] == ["allowed"]
    deleted = store.delete_by_filter(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        allowed_collection_ids=["public"],
        document_id="doc-1",
    )
    assert deleted.acknowledged is True and deleted.operation_id == 7

    store.close()
    store.close()
    assert transport.close_calls == 1
    with pytest.raises(QdrantClosedError):
        store.health()


def test_empty_acl_is_authoritative_deny_without_remote_probe() -> None:
    transport = FakeTransport(lambda *_: pytest.fail("empty scope must not make HTTP request"))
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        transport=transport,
    )
    assert store.query(
        [1.0, 0.0],
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        allowed_collection_ids=[],
    ) == []
    assert transport.requests == []


@pytest.mark.parametrize(
    ("handler", "error_type"),
    [
        (lambda *_: (_ for _ in ()).throw(TimeoutError("api-key=qdrant-secret")), QdrantTimeoutError),
        (lambda *_: HttpResponse(503, b"password=qdrant-secret"), QdrantStatusError),
    ],
)
def test_timeout_and_status_errors_are_typed_and_redacted(handler, error_type) -> None:
    secret = "qdrant-secret"
    transport = FakeTransport(handler)
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        api_key=secret,
        transport=transport,
    )
    with pytest.raises(error_type) as caught:
        store.health()
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    if isinstance(caught.value, QdrantStatusError):
        assert caught.value.status_code == 503


def test_transient_qdrant_failures_retry_with_bounded_backoff() -> None:
    responses: list[object] = [
        HttpResponse(503, b"temporary"),
        HttpResponse(200, b"healthy"),
    ]
    transport = FakeTransport(lambda *_: responses.pop(0))
    delays: list[float] = []
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        transport=transport,
        max_attempts=2,
        retry_backoff_seconds=0.25,
        sleeper=delays.append,
    )

    assert store.health().ok is True
    assert len(transport.requests) == 2
    assert delays == [0.25]


def test_qdrant_circuit_fails_closed_and_allows_one_recovery_probe() -> None:
    now = [0.0]
    responses: list[object] = [
        TimeoutError("secret=must-not-leak"),
        HttpResponse(200, b"healthy"),
    ]
    transport = FakeTransport(lambda *_: (_ for _ in ()).throw(responses.pop(0))
                              if isinstance(responses[0], BaseException)
                              else responses.pop(0))
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        transport=transport,
        max_attempts=1,
        circuit_failure_threshold=1,
        circuit_reset_seconds=10,
        clock=lambda: now[0],
    )

    with pytest.raises(QdrantTimeoutError):
        store.health()
    assert store.circuit_open is True
    with pytest.raises(QdrantCircuitOpenError):
        store.health()
    assert len(transport.requests) == 1

    now[0] = 10.0
    assert store.health().ok is True
    assert store.circuit_open is False
    assert len(transport.requests) == 2


def test_collection_schema_index_and_alias_operations_are_bounded() -> None:
    def handler(method: str, url: str, headers: Mapping[str, str], content: bytes) -> HttpResponse:
        if method == "GET" and url.endswith("/collections/rag_phase0"):
            return _json_response(
                {
                    "result": {
                        "status": "green",
                        "optimizer_status": "ok",
                        "vectors_count": 12,
                        "points_count": 12,
                    }
                }
            )
        if method == "PUT" and url.endswith("/collections/rag_phase0"):
            body = json.loads(content)
            assert body == {"vectors": {"dense": {"distance": "Cosine", "size": 1536}}}
            return _json_response({"result": True})
        if method == "PUT" and url.endswith("/collections/rag_phase0/index"):
            body = json.loads(content)
            assert body == {"field_name": "tenant_id", "field_schema": "keyword", "wait": True}
            return _json_response({"result": True})
        if method == "GET" and url.endswith("/aliases"):
            return _json_response(
                {"result": [{"alias_name": "rag_current", "collection_name": "rag_phase0"}]}
            )
        if method == "POST" and url.endswith("/collections/aliases"):
            body = json.loads(content)
            assert body == {
                "actions": [
                    {"action": "delete_alias", "alias_name": "rag_current"},
                    {
                        "action": "create_alias",
                        "alias_name": "rag_current",
                        "collection_name": "rag_phase1",
                    },
                ]
            }
            return _json_response({"result": True})
        raise AssertionError(f"unexpected route {method} {url}")

    transport = FakeTransport(handler)
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        transport=transport,
    )

    info = store.collection_info()
    assert info.status == "green" and info.points_count == 12
    assert store.create_collection(vector_dimensions=1536) is True
    assert store.create_payload_index(field_name="tenant_id") is True
    assert store.list_aliases()[0].collection_name == "rag_phase0"
    assert store.replace_alias(
        alias_name="rag_current",
        collection_name="rag_phase1",
        old_collection_name="rag_phase0",
    ) is True


def test_collection_operations_reject_unsafe_inputs_before_http() -> None:
    transport = FakeTransport(lambda *_: pytest.fail("invalid control operation must not probe Qdrant"))
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        transport=transport,
    )
    with pytest.raises(QdrantBoundsError):
        store.create_collection(vector_dimensions=20_000)
    with pytest.raises(QdrantValidationError):
        store.create_payload_index(field_name="tenant_id\nsecret")
    with pytest.raises(QdrantValidationError):
        store.replace_alias(alias_name="rag_current", collection_name="rag_current")
    assert transport.requests == []


def test_malformed_and_oversized_success_responses_are_safe_errors() -> None:
    malformed = FakeTransport(lambda *_: HttpResponse(200, b'{"result": {}}'))
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        transport=malformed,
    )
    with pytest.raises(QdrantMalformedResponseError):
        store.upsert_points([_point()])

    oversized = FakeTransport(lambda *_: HttpResponse(200, b"x" * 33))
    bounded = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        max_response_bytes=32,
        transport=oversized,
    )
    with pytest.raises(QdrantResponseTooLargeError):
        bounded.health()


def test_points_query_payload_and_response_bounds_are_enforced() -> None:
    transport = FakeTransport(lambda *_: _json_response({"result": True}))
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        max_points=1,
        max_payload_bytes=64,
        limits=QdrantLimits(max_query_results=1),
        transport=transport,
    )
    with pytest.raises(QdrantBoundsError):
        store.upsert_points([_point("one"), _point("two")])
    with pytest.raises(QdrantBoundsError):
        store.upsert_points([_point(text="x" * 100)])

    with pytest.raises(QdrantBoundsError):
        store.query(
            [1.0, 0.0],
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            allowed_collection_ids=["public"],
            limit=2,
        )

    oversized_query = FakeTransport(
        lambda *_: _json_response(
            {
                "result": {
                    "points": [
                        {
                            "id": "1",
                            "score": 0.9,
                            "payload": {
                                "tenant_id": "tenant-a",
                                "workspace_id": "workspace-a",
                                "collection_id": "public",
                            },
                        },
                        {
                            "id": "2",
                            "score": 0.8,
                            "payload": {
                                "tenant_id": "tenant-a",
                                "workspace_id": "workspace-a",
                                "collection_id": "public",
                            },
                        },
                    ]
                }
            }
        )
    )
    bounded_results = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        limits=QdrantLimits(max_query_results=1),
        transport=oversized_query,
    )
    with pytest.raises(QdrantBoundsError):
        bounded_results.query(
            [1.0, 0.0],
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            allowed_collection_ids=["public"],
            limit=1,
        )


def test_api_key_and_server_body_do_not_leak_through_repr_or_errors() -> None:
    secret = "super-secret-api-key"
    transport = FakeTransport(lambda *_: HttpResponse(500, f"document={secret}"))
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        api_key=secret,
        transport=transport,
    )
    assert secret not in repr(store)
    with pytest.raises(QdrantStatusError) as caught:
        store.health()
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


def test_delete_requires_scope_and_count_uses_the_same_acl_shape() -> None:
    transport = FakeTransport(lambda *_: _json_response({"result": {"count": 2}}))
    store = QdrantHttpVectorStore(
        base_url="http://qdrant.test",
        collection="rag_phase0",
        transport=transport,
    )
    with pytest.raises(QdrantValidationError):
        store.delete_document("doc-1", "public", tenant_id=None)
    assert transport.requests == []

    assert store.count_for_document(
        "doc-1",
        "public",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
    ) == 2
    request = json.loads(transport.requests[-1][3])
    assert [condition["key"] for condition in request["filter"]["must"][:3]] == [
        "tenant_id",
        "workspace_id",
        "collection_id",
    ]
