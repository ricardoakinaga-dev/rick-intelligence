from __future__ import annotations

import pytest

from infrastructure.compose import bootstrap_qdrant


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "RICK_QDRANT_URL": "http://qdrant:6333",
        "RICK_QDRANT_API_KEY": "disposable-key",
        "RICK_QDRANT_COLLECTION": "rick_dense_v1",
        "EMBEDDING_DIMENSION": "1536",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_bootstrap_rejects_existing_collection_with_wrong_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)

    def request(_endpoint: str, method: str, path: str, *, body=None):
        assert method == "GET"
        assert path == "/collections/rick_dense_v1"
        return 200, {
            "result": {
                "config": {
                    "params": {"vectors": {"dense": {"size": 768, "distance": "Cosine"}}}
                }
            }
        }

    monkeypatch.setattr(bootstrap_qdrant, "_request", request)
    with pytest.raises(RuntimeError, match="schema does not match"):
        bootstrap_qdrant.main()


def test_bootstrap_requires_success_for_collection_and_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    calls: list[tuple[str, str]] = []

    def request(_endpoint: str, method: str, path: str, *, body=None):
        calls.append((method, path))
        if method == "GET":
            return 404, None
        if path.endswith("/index") and body["field_name"] == "workspace_id":
            return 503, None
        return 200, {"result": {"status": "acknowledged"}}

    monkeypatch.setattr(bootstrap_qdrant, "_request", request)
    with pytest.raises(RuntimeError, match="unexpected status"):
        bootstrap_qdrant.main()
    assert calls[:2] == [("GET", "/collections/rick_dense_v1"), ("PUT", "/collections/rick_dense_v1")]


def test_bootstrap_accepts_matching_named_dense_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    calls: list[tuple[str, str]] = []

    def request(_endpoint: str, method: str, path: str, *, body=None):
        calls.append((method, path))
        if method == "GET":
            return 200, {
                "result": {
                    "config": {
                        "params": {"vectors": {"dense": {"size": 1536, "distance": "Cosine"}}}
                    }
                }
            }
        return 200, {"result": {"status": "acknowledged"}}

    monkeypatch.setattr(bootstrap_qdrant, "_request", request)
    assert bootstrap_qdrant.main() == 0
    assert calls == [
        ("GET", "/collections/rick_dense_v1"),
        ("PUT", "/collections/rick_dense_v1/index"),
        ("PUT", "/collections/rick_dense_v1/index"),
        ("PUT", "/collections/rick_dense_v1/index"),
    ]
