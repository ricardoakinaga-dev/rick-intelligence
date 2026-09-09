"""Restart and isolation checks for the local durable knowledge adapter."""

from __future__ import annotations

import sqlite3

import pytest

from rick_knowledge import Chunk, Collection, Document, SQLiteKnowledgeStore


def _document(document_id: str, *, tenant_id: str = "tenant-a", collection_id: str = "c1") -> Document:
    return Document(
        document_id=document_id, workspace_id="workspace-a", collection_id=collection_id,
        tenant_id=tenant_id, title=document_id, status="published", metadata={"source": "test"},
    )


def test_documents_and_chunks_survive_reopen_with_acl_filters(tmp_path):
    database = tmp_path / "knowledge" / "state.sqlite3"
    first = SQLiteKnowledgeStore(database)
    first.upsert_collection(Collection(workspace_id="workspace-a", collection_id="c1", tenant_id="tenant-a", title="C1"))
    first.upsert_document(_document("doc-b"))
    first.upsert_document(_document("doc-a", collection_id="c2"))
    first.replace_document_chunks("doc-b", [Chunk(chunk_id="chunk-b-0", document_id="doc-b", tenant_id="tenant-a", text="evidence")])
    first.close()

    second = SQLiteKnowledgeStore(database)
    assert [item.document_id for item in second.list_documents("workspace-a", tenant_id="tenant-a", allowed_collection_ids=["c1"])] == ["doc-b"]
    assert second.get_document("doc-b").metadata == {"source": "test"}
    assert second.get_chunks("doc-b")[0].text == "evidence"
    assert second.list_documents("workspace-a", tenant_id="tenant-b") == []
    second.close()


def test_collections_are_tenant_scoped_and_v1_migrates_without_overwrite(tmp_path):
    database = tmp_path / "knowledge" / "state.sqlite3"
    first = SQLiteKnowledgeStore(database)
    first.upsert_collection(Collection(workspace_id="workspace-a", collection_id="shared", tenant_id="tenant-a", title="A"))
    first.upsert_collection(Collection(workspace_id="workspace-a", collection_id="shared", tenant_id="tenant-b", title="B"))
    assert first.get_collection("workspace-a", "shared", tenant_id="tenant-a").title == "A"
    assert first.get_collection("workspace-a", "shared", tenant_id="tenant-b").title == "B"
    with pytest.raises(TypeError):
        first.get_collection("workspace-a", "shared")
    with pytest.raises(ValueError, match="tenant_id is required"):
        first.list_collections("workspace-a", tenant_id=None)
    with pytest.raises(TypeError):
        first.list_collections("workspace-a")
    first.close()

    # Build the previous schema shape independently, then prove opening it
    # performs the tenant-key migration without discarding its row.
    legacy = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(legacy)
    connection.executescript(
        """
        CREATE TABLE collections (
            workspace_id TEXT NOT NULL,
            collection_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY (workspace_id, collection_id)
        );
        CREATE TABLE documents (
            document_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            collection_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            document_version TEXT NOT NULL,
            content_checksum TEXT NOT NULL,
            filename TEXT NOT NULL,
            display_filename TEXT NOT NULL,
            title TEXT NOT NULL,
            source_type TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            language TEXT,
            status TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            chunker_version TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding_version TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            parent_chunk_id TEXT,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            page_start INTEGER,
            page_end INTEGER,
            section TEXT,
            heading TEXT,
            token_count INTEGER NOT NULL,
            checksum TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            chunker_version TEXT NOT NULL,
            embedding_version TEXT NOT NULL,
            index_version TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        INSERT INTO collections VALUES ('workspace-a', 'shared', 'tenant-a', 'legacy', '', '{}');
        PRAGMA user_version = 1;
        """
    )
    connection.commit()
    connection.close()

    migrated = SQLiteKnowledgeStore(legacy)
    with sqlite3.connect(legacy) as check:
        assert check.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {row[1] for row in check.execute("PRAGMA table_info(documents)")}
        assert {"ingestion_version", "object_ref", "created_at", "published_at"} <= columns
    assert migrated.get_collection("workspace-a", "shared", tenant_id="tenant-a").title == "legacy"
    migrated.close()


def test_lineage_fields_round_trip_with_scope_and_publication_state(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "lineage.sqlite3")
    document = Document(
        document_id="doc-lineage",
        workspace_id="workspace-a",
        collection_id="collection-a",
        tenant_id="tenant-a",
        document_version="document-v7",
        ingestion_version="ingestion-v3",
        object_ref="objects/tenant-a/document-v7.pdf",
        created_at="2026-09-09T12:00:00Z",
        published_at="2026-09-09T12:03:00Z",
        status="published",
    )

    store.upsert_document(document)
    stored = store.get_document("doc-lineage", tenant_id="tenant-a", workspace_id="workspace-a")

    assert stored is not None
    assert stored.tenant_id == "tenant-a"
    assert stored.workspace_id == "workspace-a"
    assert stored.collection_id == "collection-a"
    assert stored.ingestion_version == "ingestion-v3"
    assert stored.object_ref == "objects/tenant-a/document-v7.pdf"
    assert stored.created_at == "2026-09-09T12:00:00Z"
    assert stored.published_at == "2026-09-09T12:03:00Z"
    store.close()


def test_delete_is_tombstone_and_cannot_be_resurrected(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "state.sqlite3")
    store.upsert_document(_document("doc-delete"))
    store.replace_document_chunks("doc-delete", [Chunk(chunk_id="chunk", document_id="doc-delete", tenant_id="tenant-a", text="x")])
    assert store.delete_document("doc-delete") == 1
    assert store.get_chunks("doc-delete") == []
    assert store.list_documents("workspace-a", tenant_id="tenant-a") == []
    with pytest.raises(TypeError):
        store.list_documents("workspace-a")
    with pytest.raises(ValueError, match="tenant_id is required"):
        store.list_documents("workspace-a", tenant_id=None)
    assert store.get_document("doc-delete").status == "deleted"
    with pytest.raises(ValueError, match="deleted documents"):
        store.set_document_status("doc-delete", "published")
    with pytest.raises(ValueError, match="deleted documents"):
        store.upsert_document(_document("doc-delete"))
    store.close()


def test_replace_chunks_is_atomic_on_invalid_child(tmp_path):
    store = SQLiteKnowledgeStore(tmp_path / "state.sqlite3")
    store.upsert_document(_document("doc-atomic"))
    store.replace_document_chunks("doc-atomic", [Chunk(chunk_id="old", document_id="doc-atomic", tenant_id="tenant-a", text="old")])
    with pytest.raises(ValueError, match="does not match"):
        store.replace_document_chunks("doc-atomic", [Chunk(chunk_id="new", document_id="other", tenant_id="tenant-a", text="bad")])
    assert [chunk.chunk_id for chunk in store.get_chunks("doc-atomic")] == ["old"]
    store.close()
