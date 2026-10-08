"""The store reads that the search lifecycle authority depends on (A02).

``apps/api`` decides whether a collection may be searched by calling
``get_collection`` and ``get_document`` with the full tenant/workspace scope.
These tests pin the read contract that decision rests on: an archived
collection stays archived for a later reader, and a read outside the caller's
scope comes back empty instead of widening.
"""

from __future__ import annotations

import pytest

from rick_knowledge import Collection, Document, InMemoryKnowledgeStore, SQLiteKnowledgeStore

TENANT = "default"
WORKSPACE = "default"
COLLECTION = "lifecycle-a02"


def _stores(tmp_path):
    return {
        "memory": InMemoryKnowledgeStore,
        "sqlite": lambda: SQLiteKnowledgeStore(str(tmp_path / "knowledge.db")),
    }


def _seed(store) -> None:
    store.upsert_collection(Collection(
        tenant_id=TENANT, workspace_id=WORKSPACE, collection_id=COLLECTION,
        title="Lifecycle", status="active",
    ))
    store.upsert_document(Document(
        tenant_id=TENANT, workspace_id=WORKSPACE, collection_id=COLLECTION,
        document_id="doc-lifecycle", status="published", filename="a.txt",
        title="a.txt",
    ))


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_archived_collection_stays_archived_for_a_later_reader(tmp_path, kind):
    store = _stores(tmp_path)[kind]()
    _seed(store)
    active = store.get_collection(WORKSPACE, COLLECTION, tenant_id=TENANT)
    assert active is not None and active.status == "active"

    active.status = "archived"
    store.upsert_collection(active)

    reread = store.get_collection(WORKSPACE, COLLECTION, tenant_id=TENANT)
    assert reread is not None and reread.status == "archived"


def test_archive_survives_a_second_reader_over_the_same_sqlite_file(tmp_path):
    path = tmp_path / "knowledge.db"
    first = SQLiteKnowledgeStore(str(path))
    _seed(first)
    collection = first.get_collection(WORKSPACE, COLLECTION, tenant_id=TENANT)
    collection.status = "archived"
    first.upsert_collection(collection)

    second = SQLiteKnowledgeStore(str(path))
    reread = second.get_collection(WORKSPACE, COLLECTION, tenant_id=TENANT)
    assert reread is not None and reread.status == "archived"


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_lifecycle_reads_never_leave_the_caller_scope(tmp_path, kind):
    store = _stores(tmp_path)[kind]()
    _seed(store)

    assert store.get_collection(WORKSPACE, COLLECTION, tenant_id="other-tenant") is None
    assert store.get_collection("other-workspace", COLLECTION, tenant_id=TENANT) is None
    assert store.get_document("doc-lifecycle", tenant_id="other-tenant",
                              workspace_id=WORKSPACE) is None
    assert store.get_document("doc-lifecycle", tenant_id=TENANT,
                              workspace_id="other-workspace") is None
    assert store.get_document("missing-doc", tenant_id=TENANT,
                              workspace_id=WORKSPACE) is None


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_document_status_changes_are_visible_to_the_next_reader(tmp_path, kind):
    store = _stores(tmp_path)[kind]()
    _seed(store)
    document = store.get_document("doc-lifecycle", tenant_id=TENANT, workspace_id=WORKSPACE)
    assert document is not None and document.status == "published"

    document.status = "processing"
    store.upsert_document(document)

    reread = store.get_document("doc-lifecycle", tenant_id=TENANT, workspace_id=WORKSPACE)
    assert reread is not None and reread.status == "processing"
