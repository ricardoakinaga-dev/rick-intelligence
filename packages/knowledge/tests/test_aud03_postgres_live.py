"""Opt-in against Lead's migrated disposable lab; never a default database.

RICK_AUD03_TEST_DATABASE_URL must explicitly name that lab. Each test creates
unique tenant/user rows and removes only its own rows. No migrations run here.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event
from uuid import uuid4
import os
from functools import lru_cache
import importlib.util
from pathlib import Path

import pytest

from rick_knowledge import Chunk, Collection, Document, PostgresKnowledgeError, PostgresKnowledgeStore


@lru_cache
def _owned_probe(relative_path):
    """Reuse the same discriminants against the opt-in real metadata adapter."""
    path = Path(__file__).resolve().parents[3] / relative_path
    spec = importlib.util.spec_from_file_location("aud03_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("category", ["parse", "embedding", "cancel", "runtime", "lease_true"])
@pytest.mark.parametrize("published_check", [1, 2, 3])
def test_postgres_actual_handler_reindex_postcommit(lab, tmp_path, category, published_check):
    from rick_retrieval import InMemoryVectorStore
    store, _, tenant, _, workspace = lab
    probe = _owned_probe("apps/worker/tests/test_external_ingestion_reindex_outcome.py")
    probe.exercise_reindex_outcome(store, InMemoryVectorStore(), tmp_path,
        dict(tenant_id=tenant, workspace_id=workspace, collection_id="c"), category, published_check)


@pytest.mark.parametrize("deduplicated", [False, True])
def test_postgres_separate_archive_before_publication_decision(lab, tmp_path, deduplicated):
    from rick_retrieval import InMemoryVectorStore
    store, connect, tenant, user, workspace = lab
    other = PostgresKnowledgeStore(connect, created_by=user)
    probe = _owned_probe("packages/ingestion/tests/test_aud03_catalog_fence.py")
    probe.exercise_archive_before_decision(store, other, InMemoryVectorStore(), tmp_path,
        dict(tenant_id=tenant, workspace_id=workspace, collection_id="c"), deduplicated)


def test_postgres_archive_writer_waits_through_publication_commit(lab, tmp_path):
    from rick_retrieval import InMemoryVectorStore
    store, connect, tenant, user, workspace = lab
    other = PostgresKnowledgeStore(connect, created_by=user)
    probe = _owned_probe("packages/ingestion/tests/test_aud03_catalog_fence.py")
    probe.exercise_archive_exclusion(store, other, InMemoryVectorStore(), tmp_path,
        dict(tenant_id=tenant, workspace_id=workspace, collection_id="c"))


def test_postgres_service_archive_guard(lab):
    store, connect, tenant, user, workspace = lab
    other = PostgresKnowledgeStore(connect, created_by=user)
    probe = _owned_probe("apps/api/tests/test_aud03_catalog_service.py")
    probe.exercise_service_archive_guard(store, other,
        dict(tenant_id=tenant, workspace_id=workspace, collection_id="c"))


@pytest.mark.parametrize("rollback", [False, True])
def test_postgres_inherited_owner_transaction_keeps_fence_through_outcome(lab, rollback):
    store, connect, tenant, user, workspace = lab
    other = PostgresKnowledgeStore(connect, created_by=user)
    probe = _owned_probe("apps/api/tests/test_aud03_catalog_service.py")
    probe.exercise_inherited_catalog_transaction(store, other,
        dict(tenant_id=tenant, workspace_id=workspace, collection_id="c"), rollback)


@pytest.mark.parametrize("field", ["object_ref", "ingestion_version", "published_at", "created_at", "parser_version",
                                  "chunker_version", "embedding_model", "embedding_version", "metadata", "title"])
def test_postgres_restore_exact_retained_lineage(lab, field):
    store, _, tenant, _, workspace = lab
    probe = _owned_probe("packages/knowledge/tests/test_aud03_rework3.py")
    probe.exercise_restore_lineage(store, dict(tenant_id=tenant, workspace_id=workspace, collection_id="c"), field)


@pytest.mark.parametrize("caller", ["pipeline", "api", "worker"])
@pytest.mark.parametrize("operation", ["ingest", "reindex", "duplicate"])
@pytest.mark.parametrize("category", ["parse", "metadata"])
def test_postgres_completion_public_callers(lab, tmp_path, caller, operation, category):
    from rick_retrieval import InMemoryVectorStore
    store, _, tenant, _, workspace = lab
    probe = _owned_probe("apps/api/tests/test_aud03_completion.py")
    probe.exercise_completion(store, InMemoryVectorStore(), tmp_path,
        dict(tenant_id=tenant, workspace_id=workspace, collection_id="c"), caller, operation, category)


@pytest.fixture
def lab():
    dsn = os.environ.get("RICK_AUD03_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Lead must opt in to the migrated disposable PostgreSQL lab")
    import psycopg
    from psycopg.rows import dict_row
    suffix = uuid4().hex
    tenant, user, workspace = "aud03-" + suffix, "aud03-user-" + suffix, "w"
    def connect():
        return psycopg.connect(dsn, row_factory=dict_row)
    with connect() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id, display_name) VALUES (%s, %s)", (tenant, "AUD03 disposable fixture"))
        conn.execute("INSERT INTO rick_users (user_id) VALUES (%s)", (user,))
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES (%s,%s,%s,'KNOWLEDGE_MANAGER')", (tenant, user, workspace))
    store = PostgresKnowledgeStore(connect, created_by=user)
    try:
        yield store, connect, tenant, user, workspace
    finally:
        with connect() as conn:
            for table in ("rick_chunks", "rick_documents", "rick_collections", "rick_memberships"):
                conn.execute(f"DELETE FROM {table} WHERE tenant_id=%s", (tenant,))
            conn.execute("DELETE FROM rick_users WHERE user_id=%s", (user,))
            conn.execute("DELETE FROM rick_tenants WHERE tenant_id=%s", (tenant,))


def test_postgres_tombstone_and_atomic_delete_compensation(lab):
    k, _, tenant, _, workspace = lab
    k.ensure_collection(Collection(tenant_id=tenant, workspace_id=workspace, collection_id="c"))
    doc = Document(document_id=uuid4().hex, tenant_id=tenant, workspace_id=workspace, collection_id="c", content_checksum="checksum", document_version="v1", status="published", metadata={"_ingestion_attempt": "A"})
    k.upsert_document(deepcopy(doc))
    chunk = Chunk(chunk_id=uuid4().hex, document_id=doc.document_id, tenant_id=tenant, text="evidence")
    k.replace_document_chunks(doc.document_id, [chunk])
    k.delete_document(doc.document_id)
    with pytest.raises(PostgresKnowledgeError) as failure:
        k.upsert_document(deepcopy(doc))
    assert failure.value.code == "conflict"
    with pytest.raises(PostgresKnowledgeError):
        k.replace_document_chunks(doc.document_id, [chunk])
    invalid = deepcopy(doc)
    invalid.metadata["_ingestion_attempt"] = "B"
    with pytest.raises(PostgresKnowledgeError):
        k.restore_deleted_document(invalid, [chunk])
    with pytest.raises(PostgresKnowledgeError):
        k.restore_deleted_document(deepcopy(doc), [Chunk(chunk_id=uuid4().hex, document_id=doc.document_id, tenant_id="foreign")])
    assert k.get_document(doc.document_id).status == "deleted"
    assert k.get_chunks(doc.document_id) == []
    k.restore_deleted_document(deepcopy(doc), [chunk])
    assert k.get_document(doc.document_id).status == "published"
    assert k.get_chunks(doc.document_id) == [chunk]


def test_postgres_concurrent_create_preserves_catalog(lab):
    k, connect, tenant, user, workspace = lab
    other = PostgresKnowledgeStore(connect, created_by=user)
    barrier = Barrier(2)
    def create():
        barrier.wait(timeout=5)
        other.ensure_collection(Collection(tenant_id=tenant, workspace_id=workspace, collection_id="c", title="Default"))
    def review():
        barrier.wait(timeout=5)
        k.upsert_collection(Collection(tenant_id=tenant, workspace_id=workspace, collection_id="c", title="Reviewed", status="archived", version=9, metadata={"retention": "hold"}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(create), pool.submit(review)]
        for task in tasks:
            task.result(timeout=15)
    catalog = k.get_collection(workspace, "c", tenant_id=tenant)
    assert catalog.title == "Reviewed" and catalog.status == "archived" and catalog.version == 9
    assert catalog.metadata == {"retention": "hold"}


def test_postgres_guard_fences_inflight_effect_and_compensation(lab, tmp_path):
    from rick_ingestion import IngestionService
    from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
    k, connect, tenant, user, workspace = lab
    other = PostgresKnowledgeStore(connect, created_by=user)
    entered, release, started, next_write = (Event() for _ in range(4))
    lost = Event()
    class PausedVectors(InMemoryVectorStore):
        writes = 0
        def upsert_points(self, points):
            self.writes += 1
            if self.writes == 1:
                entered.set()
                assert release.wait(10)
            else:
                next_write.set()
            return super().upsert_points(points)
    v = PausedVectors()
    a = IngestionService(knowledge=k, vectors=v, embeddings=DeterministicHashEmbedding())
    b = IngestionService(knowledge=other, vectors=v, embeddings=DeterministicHashEmbedding())
    path = tmp_path / "guide.txt"
    path.write_text("Publication guidance with a real database fence. " * 80)
    def successor():
        started.set()
        return b.ingest(path, tenant_id=tenant, workspace_id=workspace, collection_id="c")
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(a.ingest, path, tenant_id=tenant, workspace_id=workspace, collection_id="c", cancel_check=lost.is_set)
        try:
            assert entered.wait(8)
            lost.set()
            new = pool.submit(successor)
            assert started.wait(5)
            assert not next_write.wait(.2)
        finally:
            release.set()
        loser, winner = old.result(timeout=20), new.result(timeout=20)
    assert loser.status == "cancelled"
    assert winner.status == "published"
    assert k.get_document(winner.document_id).status == "published"
    assert v.count_for_document(winner.document_id, "c") == len(k.get_chunks(winner.document_id)) > 0


def test_postgres_stale_owner_cannot_send_later_batch(lab, tmp_path):
    from rick_ingestion import IngestionService
    from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
    k, connect, tenant, user, workspace = lab
    other = PostgresKnowledgeStore(connect, created_by=user)
    path = tmp_path / "guide.txt"
    path.write_text("Publication guidance with durable attempt ownership. " * 80)
    winners, snapshots = [], []
    class TakeoverVectors(InMemoryVectorStore):
        started = False
        def plan_upsert_batches(self, points):
            if self.started:
                yield points
                return
            self.started = True
            yield points[:1]
            winner = IngestionService(knowledge=other, vectors=self, embeddings=DeterministicHashEmbedding()).ingest(path, tenant_id=tenant, workspace_id=workspace, collection_id="c")
            winners.append(winner)
            snapshots.append(self.all_points())
            yield points[1:]
    v = TakeoverVectors()
    loser = IngestionService(knowledge=k, vectors=v, embeddings=DeterministicHashEmbedding()).ingest(path, tenant_id=tenant, workspace_id=workspace, collection_id="c")
    assert loser.status == "failed" and loser.error_code == "lock_unavailable"
    assert winners[0].status == "published"
    assert v.all_points() == snapshots[0]
    assert k.get_document(winners[0].document_id).status == "published"
