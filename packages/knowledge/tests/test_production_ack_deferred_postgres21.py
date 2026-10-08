"""Actual PostgreSQL deferral must not become worker success telemetry."""
import time

from test_prod02_publication_postgres_live import owned_postgres  # noqa: F401


def test_postgres_authority_deferral_keeps_queue_running_and_worker_unsuccessful(owned_postgres):
    from postgres_jobs import PostgresJobQueue
    from runtime import RealWorkerRuntime
    from rick_jobs import Job, JobResult, JobScope, JobState
    from rick_knowledge import Collection, PostgresKnowledgeStore

    with owned_postgres() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id,display_name) VALUES ('t','Synthetic')")
        conn.execute("INSERT INTO rick_users (user_id) VALUES ('u')")
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES ('t','u','w','KNOWLEDGE_MANAGER')")
    scope = JobScope('t', 'w', 'c')
    knowledge = PostgresKnowledgeStore(owned_postgres, created_by='u')
    knowledge.ensure_collection(Collection(tenant_id='t', workspace_id='w', collection_id='c', metadata={'created_by':'u'}))
    calls = []

    def unavailable_authority(job):
        calls.append(str(job.job_id))
        raise RuntimeError('synthetic authority unavailability')

    queue = PostgresJobQueue(owned_postgres, publication_reconciler=unavailable_authority)
    original = Job.create(job_id='authority-deferred', tenant_id='t', workspace_id='w', collection_id='c',
                          operation='ingest', idempotency_key='authority-deferred-key', payload={}, now=time.time())
    queue.enqueue(original, expected_version=0)

    def handler(job, lease, *, cancelled):
        cancelled.checkpoint()
        return JobResult(completed_at=job.updated_at)

    runtime = RealWorkerRuntime(queue, worker_id='test-worker', scope=scope, handlers={'ingest':handler})
    try:
        batch = runtime.run_once()
        durable = queue.get(str(original.job_id), tenant_id='t', workspace_id='w', collection_id='c')
        assert calls == [str(original.job_id)]
        assert durable.state is JobState.RUNNING
        assert durable.attempt_count == 1
        assert durable.result is None and durable.failure is None
        assert durable.attempts[0].finished_at is None
        assert batch.succeeded == runtime.metrics().succeeded == 0
        assert batch.lease_lost == runtime.metrics().lease_lost == 1
        assert batch.queue_errors == runtime.metrics().queue_errors == 0
        with owned_postgres() as conn:
            row = conn.execute("SELECT lease_owner,lease_until,publication_recovery_at FROM rick_ingestion_jobs WHERE job_id=%s", (str(original.job_id),)).fetchone()
            assert row['lease_owner'] and row['lease_until'] and row['publication_recovery_at']
            assert conn.execute("SELECT count(*) AS count FROM rick_ingestion_job_events WHERE job_id=%s AND event_type='acknowledged'", (str(original.job_id),)).fetchone()['count'] == 0
    finally:
        runtime.shutdown()
