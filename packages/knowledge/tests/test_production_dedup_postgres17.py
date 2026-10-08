"""Duplicate publication reaches the real PostgreSQL queue after worker restart."""
from copy import deepcopy
import time

import pytest

from test_prod02_publication_postgres_live import owned_postgres  # noqa: F401


@pytest.mark.parametrize("legacy", [False, True])
def test_duplicate_queue_recovery_preserves_committed_facts(owned_postgres, tmp_path, legacy):
    from canonical_queue import CanonicalIngestionQueueAdapter
    from external_ingestion import ExternalIngestionHandler, _recovery_metadata
    from postgres_jobs import PostgresJobQueue
    from rick_ingestion import IngestionService
    from rick_jobs import Job, JobState
    from rick_knowledge import Collection, PostgresKnowledgeStore
    from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
    from services.ingestion_service import safe_job_json
    from services.postgres_ingestion import PostgresIngestionApplicationService

    with owned_postgres() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id,display_name) VALUES ('t','Synthetic')")
        conn.execute("INSERT INTO rick_users (user_id) VALUES ('u')")
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES ('t','u','w','KNOWLEDGE_MANAGER')")
    scope = dict(tenant_id="t", workspace_id="w", collection_id="c")
    knowledge = PostgresKnowledgeStore(owned_postgres, created_by="u")
    knowledge.ensure_collection(Collection(**scope, metadata={"created_by": "u"}))
    vectors = InMemoryVectorStore()
    source = tmp_path / "source.txt"
    source.write_text("Synthetic stable evidence for an actual PostgreSQL duplicate upload. " * 20)
    service = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    first = service.ingest(source, **scope)
    assert first.status == "published"
    queue = PostgresJobQueue(owned_postgres, max_attempts=1, lease_seconds=30)
    job = Job.create(job_id="dedup-restart", **scope, operation="ingest", idempotency_key="dedup-key",
                     payload={"object_key": "uploads/source"}, now=time.time(), max_attempts=1)
    queue.enqueue(job, expected_version=0)
    running, _ = queue.claim(worker_id="before", scope=job.scope, expected_versions={}, now=time.time())[0]
    published = service.ingest(source, **scope, job_id=str(job.job_id), _recovery_metadata=_recovery_metadata(running))
    assert published.status == "published" and published.document_id == first.document_id
    receipt = knowledge.get_publication(str(job.job_id), **scope)
    checkpoint = knowledge.get_ingestion_checkpoint(str(job.job_id), **scope)
    assert checkpoint["document_id"] == receipt["document_id"]
    if legacy:
        checkpoint.update(document_id=None, fingerprint=None, artifacts={})
        knowledge._write_ingestion_checkpoint(checkpoint)
    before = deepcopy(vectors.all_points())
    source.unlink()

    class NoReplay(DeterministicHashEmbedding):
        def embed(self, texts):
            pytest.fail("recovery must not call a provider")

    class Objects:
        def get(self, *args, **kwargs):
            pytest.fail("recovery must not hydrate the deleted source")

        def put(self, *args, **kwargs):
            pytest.fail("recovery must not overwrite a source")

    restarted_store = PostgresKnowledgeStore(owned_postgres, created_by="u")
    handler = ExternalIngestionHandler(IngestionService(knowledge=restarted_store, vectors=vectors,
        embeddings=NoReplay()), Objects(), temp_root=tmp_path / "worker")
    restarted_queue = PostgresJobQueue(owned_postgres, publication_reconciler=handler.recover_job)
    facade = PostgresIngestionApplicationService(queue=CanonicalIngestionQueueAdapter(restarted_queue),
        object_store=Objects(), knowledge=restarted_store)
    for _ in range(2):
        public = safe_job_json(facade.get_status(str(job.job_id), tenant_id="t", workspace_id="w",
                                               allowed_collection_ids=["c"]))
        terminal = restarted_queue.get(str(job.job_id), **scope)
        assert terminal.state is JobState.SUCCEEDED
        assert terminal.attempt_count == 1
        assert public["status"] == "published" and public["document_id"] == first.document_id
        assert public["metadata"] == dict(execution="external-worker", durability="postgres-s3",
                                           restart_recovery=True, storage="object-store")
        assert public["started_at"] == receipt["job_snapshot"]["started_at"]
        assert public["finished_at"] == receipt["job_snapshot"]["finished_at"]
        assert restarted_store.get_publication(str(job.job_id), **scope) == receipt
        assert vectors.all_points() == before
    assert restarted_store.get_ingestion_checkpoint(str(job.job_id), **scope)["document_id"] == first.document_id
