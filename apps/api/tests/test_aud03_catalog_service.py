"""Service read/modify/write participates before mutating memory aliases."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from threading import Event

import pytest

from rick_knowledge import Collection, InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_knowledge.fencing import collection_guard_key
from services.knowledge_service import KnowledgeApplicationService


@contextmanager
def inherited_owner_transaction(store):
    """The existing seam used by the AUD03-06 owner, without editing its helper."""
    if isinstance(store, SQLiteKnowledgeStore):
        with store._transaction():
            yield store._connection
    else:
        original_error = None
        try:
            with store._session(write=True) as (connection, _cursor):
                previous = getattr(store._restore_sessions, "connection", None)
                store._restore_sessions.connection = connection
                try:
                    yield connection
                except Exception as exc:
                    original_error = exc
                    raise
                finally:
                    store._restore_sessions.connection = previous
        except Exception:
            if original_error is not None:
                raise original_error
            raise


def exercise_inherited_catalog_transaction(store, other, scope, rollback):
    catalog = Collection(**scope, title="Reviewed", version=5, metadata={"retention": "hold"})
    store.upsert_collection(deepcopy(catalog))
    service = KnowledgeApplicationService(store)
    started, done = Event(), Event()
    def competing_create():
        started.set()
        result = other.ensure_collection(Collection(**scope, title="Default"))
        done.set()
        return result
    class CompletionFailure(RuntimeError):
        pass
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.collection_guard(**scope):
            with (pytest.raises(CompletionFailure) if rollback else nullcontext()):
                with inherited_owner_transaction(store):
                    service.archive_collection(**scope)
                    # Adapter read/write sessions must use the borrowed owner;
                    # a separate real adapter cannot observe uncommitted state.
                    assert other.get_collection(scope["workspace_id"], scope["collection_id"], tenant_id=scope["tenant_id"]) == catalog
                    task = pool.submit(competing_create)
                    assert started.wait(5) and not done.wait(.15)
                    if rollback:
                        raise CompletionFailure("Owner completion failed before commit")
            actual = store.get_collection(scope["workspace_id"], scope["collection_id"], tenant_id=scope["tenant_id"])
            assert actual.status == ("active" if rollback else "archived")
            assert actual.version == (5 if rollback else 6)
        winner = task.result(timeout=8)
    assert done.is_set() and winner == actual
    assert winner.title == catalog.title and winner.metadata == catalog.metadata
    if hasattr(store, "_restore_sessions"):
        assert getattr(store._restore_sessions, "connection", None) is None


@pytest.mark.parametrize("rollback", [False, True])
def test_sqlite_inherited_owner_transaction_keeps_fence_through_commit_or_rollback(tmp_path, rollback):
    store, other = SQLiteKnowledgeStore(tmp_path / "catalog.sqlite"), SQLiteKnowledgeStore(tmp_path / "catalog.sqlite")
    try:
        exercise_inherited_catalog_transaction(store, other, dict(tenant_id="t", workspace_id="w", collection_id="c"), rollback)
    finally:
        other.close()
        store.close()


def exercise_service_archive_guard(store, other, scope):
    store.upsert_collection(Collection(**scope, title="Reviewed", version=5))
    service = KnowledgeApplicationService(other)
    started, done = Event(), Event()
    def archive():
        started.set()
        result = service.archive_collection(**scope)
        done.set()
        return result
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.collection_guard(**scope):
            task = pool.submit(archive)
            assert started.wait(5)
            assert not done.wait(.15)
            # The service's read/modify/write must remain guarded, even though
            # public catalog reads now return detached values.
            current = store.get_collection(scope["workspace_id"], scope["collection_id"], tenant_id=scope["tenant_id"])
            assert current.status == "active" and current.version == 5
        result = task.result(timeout=8)
    assert result["status"] == "archived" and result["version"] == 6
    with pytest.raises(ValueError, match="archived"):
        service.update_collection(**scope, title="Resurrected")


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_service_archive_waits_before_mutating_catalog(tmp_path, kind):
    store = InMemoryKnowledgeStore() if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "catalog.sqlite")
    other = store if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "catalog.sqlite")
    try:
        exercise_service_archive_guard(store, other, dict(tenant_id="t", workspace_id="w", collection_id="c"))
    finally:
        if kind == "sqlite":
            other.close()
            store.close()


def test_collection_guard_keys_are_unambiguous_and_separate_from_documents():
    scopes = [("default", "tenant:t:w", "c"), ("t", "w", "c"),
              ("a:b", "c", "d"), ("a", "b:c", "d"),
              ("a", "b", "c:d"), ('a"', "b", "c"), ("a", "b", "ç")]
    keys = [collection_guard_key(tenant_id=t, workspace_id=w, collection_id=c) for t, w, c in scopes]
    assert len(set(keys)) == len(scopes)
    assert all(key.startswith("collection:v1:[") and not key.startswith("document:") for key in keys)
    with pytest.raises(ValueError):
        collection_guard_key(tenant_id="", workspace_id="w", collection_id="c")
