"""Cancellation releases owned transactions without swallowing process signals."""
import asyncio
from copy import deepcopy

import pytest

from rick_knowledge import Chunk, Collection, Document, InMemoryKnowledgeStore, SQLiteKnowledgeStore


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_cancelled_restore_rolls_back_complete_tombstone(tmp_path, kind):
    store = InMemoryKnowledgeStore() if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "restore.sqlite")
    exercise_cancelled_restore(store, dict(tenant_id="t", workspace_id="w", collection_id="c"))
    if kind == "sqlite":
        assert not store._connection.in_transaction
        tombstone = deepcopy(store.get_document("d"))
        store.close()
        store = SQLiteKnowledgeStore(tmp_path / "restore.sqlite")
        assert store.get_document("d") == tombstone and store.get_chunks("d") == []
        store.close()


def exercise_cancelled_restore(store, scope):
    store.ensure_collection(Collection(**scope))
    store.upsert_document(Document(**scope, document_id="d", status="published"))
    snapshot = deepcopy(store.get_document("d"))
    chunks = [Chunk(tenant_id=scope["tenant_id"], document_id="d", chunk_id="chunk", text="retained")]
    store.replace_document_chunks("d", chunks)
    store.delete_document("d")
    tombstone = deepcopy(store.get_document("d"))
    original = store.replace_document_chunks
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise asyncio.CancelledError()
    store.replace_document_chunks = interrupted
    with pytest.raises(asyncio.CancelledError):
        store.restore_deleted_document(snapshot, chunks)
    assert store.get_document("d") == tombstone and store.get_chunks("d") == []
