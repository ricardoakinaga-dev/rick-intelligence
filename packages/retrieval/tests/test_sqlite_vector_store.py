from __future__ import annotations

import os

import pytest

from rick_retrieval import SQLiteVectorStore
from rick_retrieval.sqlite_vector_store import SQLiteVectorStoreConfigurationError, SQLiteVectorStoreError, SQLiteVectorStoreValidationError


def _point(point_id: str = "point-1") -> dict[str, object]:
    return {
        "point_id": point_id,
        "vector": [0.1, 0.2, 0.3],
        "payload": {
            "tenant_id": "tenant-1",
            "workspace_id": "workspace-1",
            "collection_id": "collection-1",
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "text": "safe evidence",
        },
    }


def test_sqlite_vector_points_survive_reopen_and_converge(tmp_path):
    path = tmp_path / "vectors.sqlite3"
    first = SQLiteVectorStore(path, mode="test")
    assert first.upsert_points([_point()]) == 1
    assert first.count_for_document("doc-1", "collection-1") == 1
    first.close()

    second = SQLiteVectorStore(path, mode="test")
    assert second.all_points() == [_point()]
    assert second.upsert_points([{**_point(), "payload": {**_point()["payload"], "text": "updated"}}]) == 1
    assert second.all_points()[0]["payload"]["text"] == "updated"
    assert second.delete_document("doc-1", "collection-1") == 1
    assert second.all_points() == []
    second.close()


def test_sqlite_vector_store_rejects_unbounded_or_non_finite_input(tmp_path):
    store = SQLiteVectorStore(tmp_path / "vectors.sqlite3", mode="test")
    with pytest.raises(SQLiteVectorStoreValidationError):
        store.upsert_points([{**_point(), "vector": [float("nan")]}])
    with pytest.raises(SQLiteVectorStoreValidationError):
        store.upsert_points([{**_point(), "payload": {"raw": object()}}])
    store.close()


def test_sqlite_vector_store_reads_are_explicitly_bounded(tmp_path):
    store = SQLiteVectorStore(tmp_path / "vectors.sqlite3", mode="test")
    points = [{**_point(f"point-{index}"), "payload": {**_point()["payload"], "chunk_id": f"chunk-{index}"}} for index in range(3)]
    store.upsert_points(points)
    with pytest.raises(SQLiteVectorStoreValidationError, match="complete point snapshot"):
        store.all_points(limit=2)
    assert len(store.all_points(limit=3)) == 3
    with pytest.raises(SQLiteVectorStoreValidationError):
        store.all_points(limit=100_001)
    store.close()


def test_sqlite_vector_store_detects_tampering_and_refuses_production(monkeypatch, tmp_path):
    with pytest.raises(SQLiteVectorStoreConfigurationError):
        SQLiteVectorStore(tmp_path / "vectors.sqlite3", mode="production")
    monkeypatch.setenv("RICK_ENV", "production")
    with pytest.raises(SQLiteVectorStoreConfigurationError):
        SQLiteVectorStore(tmp_path / "vectors-prod.sqlite3", mode="test")
    monkeypatch.delenv("RICK_ENV")

    path = tmp_path / "vectors.sqlite3"
    store = SQLiteVectorStore(path, mode="test")
    store.upsert_points([_point()])
    store.close()
    import sqlite3

    connection = sqlite3.connect(path)
    connection.execute("UPDATE vector_points SET payload_checksum = 'tampered'")
    connection.commit()
    connection.close()
    reopened = SQLiteVectorStore(path, mode="test")
    with pytest.raises(SQLiteVectorStoreError):
        reopened.all_points()
    reopened.close()
