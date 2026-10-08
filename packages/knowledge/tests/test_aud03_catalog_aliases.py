"""Aliases share admission and fencing, including catalog rows predating normalization."""
from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from rick_knowledge import Collection, InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_knowledge.fencing import collection_guard_key


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    result = InMemoryKnowledgeStore() if request.param == "memory" else SQLiteKnowledgeStore(tmp_path / "catalog.sqlite")
    yield result
    close = getattr(result, "close", None)
    if close:
        close()


def seed_historical(store, collection):
    """Fixture only: bypass today's writers to represent an installed alias row."""
    if isinstance(store, InMemoryKnowledgeStore):
        store._collections[(collection.tenant_id, collection.workspace_id, collection.collection_id)] = deepcopy(collection)
    elif isinstance(store, SQLiteKnowledgeStore):
        with store._transaction():
            store._connection.execute("INSERT INTO collections (tenant_id,workspace_id,collection_id,title,description,metadata_json) VALUES (?,?,?,?,?,?)",
                (collection.tenant_id, collection.workspace_id, collection.collection_id, collection.title, collection.description,
                 json.dumps({**collection.metadata, "__rick_status": collection.status, "__rick_version": collection.version})))
    else:
        with store._session(write=True) as (_, cursor):
            store._execute(cursor, "INSERT INTO rick_collections (tenant_id,workspace_id,collection_id,title,description,status,version,created_by,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb))",
                (collection.tenant_id, collection.workspace_id, collection.collection_id, collection.title, collection.description,
                 collection.status, collection.version, store._created_by, json.dumps(collection.metadata)))


@pytest.mark.parametrize("alias", ["cvg_master_rag", "rickvet_documents"])
def test_alias_guard_key_is_canonical_and_scope_safe(alias):
    scope = dict(tenant_id="t", workspace_id="w")
    assert collection_guard_key(**scope, collection_id=alias) == collection_guard_key(**scope, collection_id="rag_phase0")
    assert collection_guard_key(tenant_id="a:b", workspace_id="c", collection_id=alias) != collection_guard_key(tenant_id="a", workspace_id="b:c", collection_id=alias)


@pytest.mark.parametrize("alias", ["cvg_master_rag", "rickvet_documents"])
def test_new_alias_write_creates_only_canonical_catalog(store, alias):
    c = Collection(tenant_id="t", workspace_id="w", collection_id=alias, title="Reviewed", version=17, metadata={"retention": {"days": 365}})
    store.upsert_collection(c)
    assert c.collection_id == alias, "Writers must not mutate caller objects"
    rows = store.list_collections("w", tenant_id="t")
    assert len(rows) == 1 and rows[0].collection_id == "rag_phase0"
    for key in (alias, "rag_phase0", "rickvet_documents", "cvg_master_rag"):
        assert store.get_collection("w", key, tenant_id="t") == rows[0]


@pytest.mark.parametrize("alias", ["cvg_master_rag", "rickvet_documents"])
@pytest.mark.parametrize("canonical_exists", [False, True])
def test_archived_historical_alias_cannot_be_ensured_or_reactivated(store, alias, canonical_exists):
    exercise_archived_alias(store, dict(tenant_id="t", workspace_id="w"), alias, canonical_exists)


def exercise_archived_alias(store, scope, alias, canonical_exists):
    legacy = Collection(**scope, collection_id=alias, status="archived", title="Historical archive", version=19, metadata={"retention": {"days": 720}})
    if canonical_exists:
        store.upsert_collection(Collection(**scope, collection_id="rag_phase0", title="Canonical active"))
    seed_historical(store, legacy)
    before = [asdict(c) for c in store.list_collections(scope["workspace_id"], tenant_id=scope["tenant_id"])]
    for key in (alias, "rag_phase0", "rickvet_documents", "cvg_master_rag"):
        assert store.get_collection(scope["workspace_id"], key, tenant_id=scope["tenant_id"]) == legacy
        assert store.ensure_collection(Collection(**scope, collection_id=key)) == legacy
        with pytest.raises(ValueError, match="archived"):
            store.upsert_collection(Collection(**scope, collection_id=key, status="active"))
    assert [asdict(c) for c in store.list_collections(scope["workspace_id"], tenant_id=scope["tenant_id"])] == before


@pytest.mark.parametrize("alias", ["cvg_master_rag", "rickvet_documents"])
def test_active_historical_alias_retains_metadata_and_physical_history(store, alias):
    exercise_active_alias(store, dict(tenant_id="t", workspace_id="w"), alias)


def exercise_active_alias(store, scope, alias):
    legacy = Collection(**scope, collection_id=alias, title="Historical active", description="Retained description", version=19, metadata={"retention": {"days": 720}})
    seed_historical(store, legacy)
    canonical = store.ensure_collection(Collection(**scope, collection_id="rag_phase0", title="Unreviewed"))
    assert canonical.collection_id == "rag_phase0"
    assert {k: v for k, v in asdict(canonical).items() if k != "collection_id"} == {k: v for k, v in asdict(legacy).items() if k != "collection_id"}
    rows = store.list_collections(scope["workspace_id"], tenant_id=scope["tenant_id"])
    assert legacy in rows and len(rows) == 2
    before = deepcopy(rows)
    assert store.ensure_collection(Collection(**scope, collection_id=alias, title="Unreviewed")) == canonical
    assert store.list_collections(scope["workspace_id"], tenant_id=scope["tenant_id"]) == before
