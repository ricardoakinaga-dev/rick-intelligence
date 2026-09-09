from __future__ import annotations

from dataclasses import dataclass

import pytest

from rick_knowledge import Chunk, Collection, Document, PostgresKnowledgeError, PostgresKnowledgeStore


@dataclass
class Cursor:
    rows: list[dict]
    calls: list[tuple[str, tuple[object, ...]]]
    description: list[tuple[str]] | None = None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        self.calls.append((query, params))
        if self.rows:
            row = self.rows[0]
            self.description = [(key,) for key in row]

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def close(self):
        return None


class Connection:
    def __init__(self, rows: list[dict]):
        self.cursor_instance = Cursor(rows, [])
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_reads_are_tenant_and_workspace_scoped_and_connections_close() -> None:
    connection = Connection([{
        "tenant_id": "tenant-a", "workspace_id": "workspace-a", "collection_id": "clinical",
        "title": "Clinical", "description": "", "status": "active", "version": 2,
    }])
    store = PostgresKnowledgeStore(lambda: connection)
    item = store.get_collection("workspace-a", "clinical", tenant_id="tenant-a")
    assert item is not None and item.version == 2
    query, params = connection.cursor_instance.calls[0]
    assert "tenant_id = %s" in query and params == ("tenant-a", "workspace-a", "clinical")
    assert connection.closed


def test_upsert_uses_one_transaction_and_deleted_documents_cannot_resurrect() -> None:
    connection = Connection([{"status": "deleted"}])
    store = PostgresKnowledgeStore(lambda: connection, created_by="operator-1")
    document = Document(
        document_id="doc-1", tenant_id="tenant-a", workspace_id="workspace-a", collection_id="clinical",
        document_version="v1", content_checksum="sha256:abc", filename="report.txt",
        display_filename="report.txt", title="Report", mime_type="text/plain", metadata={"byte_size": 12},
    )
    with pytest.raises(PostgresKnowledgeError) as error:
        store.upsert_document(document)
    assert error.value.code == "conflict"
    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_upsert_writes_scoped_document_lineage_columns() -> None:
    connection = Connection([])
    store = PostgresKnowledgeStore(lambda: connection, created_by="operator-1")
    document = Document(
        document_id="doc-lineage",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        collection_id="clinical",
        document_version="document-v7",
        ingestion_version="ingestion-v3",
        object_ref="s3://private/tenant-a/document-v7.pdf",
        created_at="2026-09-09T12:00:00Z",
        published_at="2026-09-09T12:03:00Z",
        status="published",
        metadata={"byte_size": 12},
    )

    store.upsert_document(document)

    query, params = connection.cursor_instance.calls[1]
    assert "object_ref" in query
    assert "ingestion_version" in query
    assert "created_at" in query and "published_at" in query
    assert params[6:9] == (
        "s3://private/tenant-a/document-v7.pdf",
        "s3://private/tenant-a/document-v7.pdf",
        "ingestion-v3",
    )
    assert params[-2:] == ("2026-09-09T12:00:00Z", "2026-09-09T12:03:00Z")
    assert connection.commits == 1


def test_chunk_replacement_is_transactional_and_requires_stable_order() -> None:
    connection = Connection([{"tenant_id": "tenant-a", "workspace_id": "workspace-a", "collection_id": "clinical"}])
    store = PostgresKnowledgeStore(lambda: connection, created_by="operator-1")
    chunk = Chunk(
        chunk_id="chunk-1", document_id="doc-1", tenant_id="tenant-a", chunk_index=1,
        text="evidence", checksum="sha256:chunk", embedding_version="v1", index_version="v1",
    )
    with pytest.raises(PostgresKnowledgeError) as error:
        store.replace_document_chunks("doc-1", [chunk])
    assert error.value.code == "invalid_input"
    assert connection.rollbacks == 1
    assert connection.commits == 0
