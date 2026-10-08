"""Catalog writers and publication share a real exclusion boundary."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from threading import Event

import pytest

from rick_ingestion import IngestionService
from rick_ingestion.pipeline import _scoped_call
from rick_knowledge import Collection, InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore, SQLiteVectorStore


def test_late_dedup_claim_releases_document_guard_before_collection_guard(tmp_path):
    class OrderedStore(InMemoryKnowledgeStore):
        held = []
        @contextmanager
        def mutation_guard(self, key):
            if key.startswith("collection:"):
                assert not any(held.startswith("document:") for held in self.held), "document -> collection lock inversion"
            with super().mutation_guard(key):
                self.held.append(key)
                try:
                    yield
                finally:
                    assert self.held.pop() == key
    knowledge, vectors = OrderedStore(), InMemoryVectorStore()
    scope = dict(tenant_id="t", workspace_id="w", collection_id="c")
    path = tmp_path / "late-dedup.txt"
    path.write_text("Concurrent publication wins after initial read but before ownership claim. " * 80)
    winner_service = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    winners = []
    class PublishDuringEmbedding(DeterministicHashEmbedding):
        def embed(self, texts):
            if not winners:
                winners.append(winner_service.ingest(path, **scope))
            return super().embed(texts)
    contender = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=PublishDuringEmbedding())
    result = contender.ingest(path, **scope)
    assert winners[0].status == result.status == "published"
    assert result.document_id == winners[0].document_id and result.metadata["deduplicated"]


def exercise_archive_before_decision(knowledge, other, vectors, tmp_path, scope, deduplicated):
    initial = Collection(**scope, title="Reviewed", description="Retention review", version=5,
                         metadata={"retention": {"mode": "hold"}})
    knowledge.upsert_collection(deepcopy(initial))
    service = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    path = tmp_path / "archive-race.txt"
    path.write_text("The catalog archive commits before the publication decision. " * 80)
    before = None
    if deduplicated:
        original = service.ingest(path, **scope)
        assert original.status == "published"
        before = deepcopy((knowledge.get_document(original.document_id), knowledge.get_chunks(original.document_id), vectors.all_points()))
    checked, archived = Event(), Event()
    archive_done = []
    class Guard:
        def __enter__(self):
            return self
        def check(self):
            checked.set()
            assert archived.wait(5), "catalog writer must finish before publication takes its decision lock"
        def __exit__(self, *_):
            return False
    def archive():
        assert checked.wait(5)
        changed = deepcopy(initial)
        changed.status = "archived"
        changed.version = 6
        other.upsert_collection(changed)
        archive_done.append(deepcopy(other.get_collection(scope["workspace_id"], scope["collection_id"], tenant_id=scope["tenant_id"])))
        archived.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(archive)
        result = service.ingest(path, **scope, publication_guard=Guard)
        task.result(timeout=8)
    actual = deepcopy((knowledge.get_document(result.document_id), knowledge.get_chunks(result.document_id), vectors.all_points()))
    assert archive_done and archive_done[0].status == "archived"
    assert knowledge.get_collection(scope["workspace_id"], scope["collection_id"], tenant_id=scope["tenant_id"]) == archive_done[0]
    assert result.status == "failed" and result.error_code == "validation_error"
    if deduplicated:
        assert actual == before
    else:
        assert actual[0].status == "failed" and actual[1] == actual[2] == []
    return result.document_id, actual


@pytest.mark.parametrize("deduplicated", [False, True])
def test_separate_sqlite_archive_commits_before_publication_decision(tmp_path, deduplicated):
    knowledge, other = SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite"), SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite")
    vectors = SQLiteVectorStore(tmp_path / "vectors.sqlite")
    try:
        document_id, actual = exercise_archive_before_decision(knowledge, other, vectors, tmp_path,
            dict(tenant_id="t", workspace_id="w", collection_id="c"), deduplicated)
    finally:
        other.close()
        knowledge.close()
        vectors.close()
    knowledge, vectors = SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite"), SQLiteVectorStore(tmp_path / "vectors.sqlite")
    try:
        assert deepcopy((knowledge.get_document(document_id), knowledge.get_chunks(document_id), vectors.all_points())) == actual
    finally:
        knowledge.close()
        vectors.close()


def exercise_archive_exclusion(knowledge, other, vectors, tmp_path, scope):
    catalog = Collection(**scope, title="Reviewed", version=5, metadata={"retention": "hold"})
    knowledge.upsert_collection(deepcopy(catalog))
    at_commit, release, archive_started, archive_done, commit_done = (Event() for _ in range(5))
    delegate = knowledge.set_document_status
    def paused_commit(document_id, status, **kwargs):
        if status == "published":
            at_commit.set()
            assert release.wait(5)
        _scoped_call(delegate, document_id, status,
                     tenant_id=kwargs.get("tenant_id"), workspace_id=kwargs.get("workspace_id"))
        if status == "published":
            commit_done.set()
    knowledge.set_document_status = paused_commit
    service = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    path = tmp_path / "publication-first.txt"
    path.write_text("A catalog archive must wait while publication commits. " * 80)
    def archive():
        archive_started.set()
        changed = deepcopy(catalog)
        changed.status = "archived"
        changed.version = 6
        other.upsert_collection(changed)
        assert commit_done.is_set(), "archive committed while the final publication interval was protected"
        archive_done.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        publication = pool.submit(service.ingest, path, **scope)
        try:
            assert at_commit.wait(5)
            archival = pool.submit(archive)
            assert archive_started.wait(5)
            assert not archive_done.wait(.15)
        finally:
            release.set()
        result = publication.result(timeout=8)
        archival.result(timeout=8)
    assert commit_done.is_set() and archive_done.is_set()
    assert result.status == knowledge.get_document(result.document_id).status == "published"
    assert knowledge.get_chunks(result.document_id) and vectors.all_points()
    assert knowledge.get_collection(scope["workspace_id"], scope["collection_id"], tenant_id=scope["tenant_id"]).status == "archived"


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_catalog_writer_waits_through_actual_final_commit(tmp_path, kind):
    if kind == "memory":
        knowledge, vectors = InMemoryKnowledgeStore(), InMemoryVectorStore()
        other = knowledge
    else:
        knowledge, other = SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite"), SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite")
        vectors = SQLiteVectorStore(tmp_path / "vectors.sqlite")
    try:
        exercise_archive_exclusion(knowledge, other, vectors, tmp_path,
            dict(tenant_id="t", workspace_id="w", collection_id="c"))
    finally:
        if kind == "sqlite":
            other.close()
            knowledge.close()
            vectors.close()
