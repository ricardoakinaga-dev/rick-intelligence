"""AUD03 publication regressions: observe stored effects, not only job ACKs."""
from contextlib import contextmanager
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest

from rick_ingestion import IngestionService
from rick_knowledge import Collection, InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore


def service(knowledge, vectors):
    return IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())


def source(tmp_path):
    path = tmp_path / "guide.txt"
    path.write_text("Canonical publication and citation guidance. " * 80)
    return path


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
@pytest.mark.parametrize("archived", [False, True])
def test_ingestion_preserves_catalog(tmp_path, kind, archived):
    k = InMemoryKnowledgeStore() if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "catalog.sqlite")
    catalog = Collection(tenant_id="t", workspace_id="w", collection_id="c", title="Reviewed", description="Retain", status="archived" if archived else "active", version=8, metadata={"retention": "hold"})
    k.upsert_collection(catalog)
    v = InMemoryVectorStore()
    result = service(k, v).ingest(source(tmp_path), tenant_id="t", workspace_id="w", collection_id="c")
    assert result.status == ("failed" if archived else "published")
    assert k.get_collection("w", "c", tenant_id="t") == catalog
    if archived:
        assert k.list_documents("w", tenant_id="t") == []
        assert v.all_points() == []
    if kind == "sqlite":
        k.close()


@pytest.mark.parametrize("fault", ["cancel", "raise"])
def test_stale_compensation_cannot_remove_winner(tmp_path, fault):
    k = InMemoryKnowledgeStore()
    state = {"lost": False}
    winners = []

    class InterleavingVectors(InMemoryVectorStore):
        hook = None

        def upsert_points(self, points):
            count = super().upsert_points(points)
            if self.hook:
                hook, self.hook = self.hook, None
                hook()
                if fault == "raise":
                    raise RuntimeError("old acknowledgement failed")
            return count

    v = InterleavingVectors()
    a, b = service(k, v), service(k, v)
    path = source(tmp_path)

    def take_over():
        state["lost"] = True
        winners.append(b.ingest(path, tenant_id="t", workspace_id="w", collection_id="c"))

    v.hook = take_over
    loser = a.ingest(path, tenant_id="t", workspace_id="w", collection_id="c", cancel_check=lambda: state["lost"])
    winner = winners[0]
    assert loser.status in {"cancelled", "failed"}
    assert winner.status == "published"
    assert k.get_document(winner.document_id).status == "published"
    assert v.count_for_document(winner.document_id, "c") == len(k.get_chunks(winner.document_id)) > 0


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_two_services_fence_inflight_vector_effect(tmp_path, kind):
    k = InMemoryKnowledgeStore() if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "effects.sqlite")
    other = k if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "effects.sqlite")
    entered, release, started, winner_write = (Event() for _ in range(4))
    lost = Event()

    class PausedVectors(InMemoryVectorStore):
        calls = 0

        def upsert_points(self, points):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert release.wait(5)
            else:
                winner_write.set()
            return super().upsert_points(points)

    v = PausedVectors()
    a, b = service(k, v), service(other, v)
    path = source(tmp_path)
    def run_b():
        started.set()
        return b.ingest(path, tenant_id="t", workspace_id="w", collection_id="c")

    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(a.ingest, path, tenant_id="t", workspace_id="w", collection_id="c", cancel_check=lost.is_set)
        try:
            assert entered.wait(3)
            lost.set()
            new = pool.submit(run_b)
            assert started.wait(3)
            assert not winner_write.wait(0.15)
        finally:
            release.set()
        loser, winner = old.result(timeout=5), new.result(timeout=5)
    assert loser.status == "cancelled"
    assert winner.status == "published"
    assert k.get_document(winner.document_id).status == "published"
    assert v.count_for_document(winner.document_id, "c") == len(k.get_chunks(winner.document_id)) > 0
    if kind == "sqlite":
        other.close()
        k.close()


@pytest.mark.parametrize("deduplicated", [False, True])
def test_guard_exit_failure_reports_real_commit(tmp_path, deduplicated):
    k, v = InMemoryKnowledgeStore(), InMemoryVectorStore()
    s = service(k, v)
    path = source(tmp_path)
    if deduplicated:
        assert s.ingest(path, tenant_id="t", workspace_id="w", collection_id="c").status == "published"

    @contextmanager
    def guard():
        yield
        raise RuntimeError("lease lost on guard exit")

    result = s.ingest(path, tenant_id="t", workspace_id="w", collection_id="c", publication_guard=guard)
    assert result.status == "published"
    assert k.get_document(result.document_id).status == "published"
    assert v.count_for_document(result.document_id, "c") == len(k.get_chunks(result.document_id)) > 0


def test_stale_attempt_cannot_write_the_next_batch_even_without_cancel_signal(tmp_path):
    k = InMemoryKnowledgeStore()
    winners, snapshots = [], []
    path = source(tmp_path)

    class TakeoverBetweenBatches(InMemoryVectorStore):
        started = False

        def plan_upsert_batches(self, points):
            if self.started:
                yield points
                return
            self.started = True
            yield points[:1]
            winners.append(service(k, self).ingest(path, tenant_id="t", workspace_id="w", collection_id="c"))
            snapshots.append(self.all_points())
            yield points[1:]  # stale A must fail before sending this effect

    v = TakeoverBetweenBatches()
    loser = service(k, v).ingest(path, tenant_id="t", workspace_id="w", collection_id="c")
    assert loser.status == "failed" and loser.error_code == "lock_unavailable"
    assert winners[0].status == "published"
    assert v.all_points() == snapshots[0]
    assert k.get_document(winners[0].document_id).status == "published"


def test_takeover_during_partial_write_compensation_preserves_winner(tmp_path):
    k = InMemoryKnowledgeStore()
    path = source(tmp_path)
    winners = []
    class CompensationTakeover(InMemoryVectorStore):
        fault = True
        hook = None
        def upsert_points(self, points):
            count = super().upsert_points(points)
            if self.fault:
                self.fault = False
                self.hook = lambda: winners.append(service(k, self).ingest(path, tenant_id="t", workspace_id="w", collection_id="c"))
                raise RuntimeError("partial vector write")
            return count
        def delete_document(self, document_id, collection_id):
            count = super().delete_document(document_id, collection_id)
            if self.hook:
                hook, self.hook = self.hook, None
                hook()
            return count
    v = CompensationTakeover()
    loser = service(k, v).ingest(path, tenant_id="t", workspace_id="w", collection_id="c")
    assert loser.status == "failed" and winners[0].status == "published"
    assert k.get_document(winners[0].document_id).status == "published"
    assert v.count_for_document(winners[0].document_id, "c") == len(k.get_chunks(winners[0].document_id)) > 0


def test_cancel_during_guard_exit_cannot_relabel_committed_job(tmp_path):
    k, v = InMemoryKnowledgeStore(), InMemoryVectorStore()
    s = service(k, v)
    committed, release = Event(), Event()

    @contextmanager
    def guard():
        yield
        committed.set()
        assert release.wait(5)
        raise RuntimeError("lease lost after commit")

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(s.ingest, source(tmp_path), tenant_id="t", workspace_id="w", collection_id="c", job_id="terminal", publication_guard=guard)
        try:
            assert committed.wait(3)
            assert s.cancel("terminal") is False
            assert k.get_document(s.get_status("terminal").document_id).status == "published"
        finally:
            release.set()
        published = result.result(timeout=5)
    assert published.status == "published"


@pytest.mark.parametrize("deduplicated", [False, True])
def test_archive_at_publication_entry_denies_commit_without_overwriting_catalog(tmp_path, deduplicated):
    k, v = InMemoryKnowledgeStore(), InMemoryVectorStore()
    s = service(k, v)
    path = source(tmp_path)
    if deduplicated:
        first = s.ingest(path, tenant_id="t", workspace_id="w", collection_id="c")
        before = v.all_points()
    @contextmanager
    def guard():
        catalog = k.get_collection("w", "c", tenant_id="t")
        catalog.status = "archived"
        catalog.title = "Archived review"
        k.upsert_collection(catalog)
        yield
    result = s.ingest(path, tenant_id="t", workspace_id="w", collection_id="c", publication_guard=guard)
    assert result.status == "failed" and result.error_code == "validation_error"
    catalog = k.get_collection("w", "c", tenant_id="t")
    assert catalog.status == "archived" and catalog.title == "Archived review"
    if deduplicated:
        assert k.get_document(first.document_id).status == "published"
        assert v.all_points() == before
    else:
        assert k.get_document(result.document_id).status == "failed"
        assert v.all_points() == []


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_legacy_fixture_keeps_document_chunk_and_point_references(tmp_path, kind):
    from rick_knowledge import Chunk, Document, content_checksum, legacy_document_id_for_content, point_id_for_chunk
    path = source(tmp_path)
    checksum = content_checksum(path.read_bytes())
    legacy_id = legacy_document_id_for_content(tenant_id="t", workspace_id="w", collection_id="c", checksum=checksum)
    k = InMemoryKnowledgeStore() if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "legacy.sqlite")
    k.upsert_collection(Collection(tenant_id="t", workspace_id="w", collection_id="c"))
    k.upsert_document(Document(document_id=legacy_id, tenant_id="t", workspace_id="w", collection_id="c", content_checksum=checksum, status="published"))
    chunk = Chunk(chunk_id="legacy-citation", document_id=legacy_id, tenant_id="t", text="published guidance")
    k.replace_document_chunks(legacy_id, [chunk])
    v = InMemoryVectorStore()
    point = {"point_id": point_id_for_chunk(chunk.chunk_id), "vector": [1.0], "payload": {"document_id": legacy_id, "tenant_id": "t", "workspace_id": "w", "collection_id": "c"}}
    v.upsert_points([point])
    result = service(k, v).ingest(path, tenant_id="t", workspace_id="w", collection_id="c")
    assert result.status == "published" and result.document_id == legacy_id
    assert result.metadata["identity_encoding"] == "legacy-v1"
    assert k.get_chunks(legacy_id) == [chunk]
    assert v.all_points() == [point]
    if kind == "sqlite":
        k.close()
