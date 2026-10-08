"""Recovery confirmation belongs to the execution's complete identity."""
from dataclasses import replace
import pytest

from rick_jobs import JobResult, JobState
from runtime import WorkerCancelled
from test_runtime import FakeQueue, ManualClock, job, make_runtime


@pytest.mark.parametrize('port', ['cancel', 'failure'])
@pytest.mark.parametrize('foreign', ['job_id', 'tenant_id', 'workspace_id', 'collection_id', None])
def test_runtime_recovery_does_not_accept_another_job_or_scope(port, foreign):
    class RecoveryQueue(FakeQueue):
        recovery_calls = 0

        def recover(self, lease, now):
            self.recovery_calls += 1
            original = self._jobs[str(lease.job_id)]
            completed = original.finish_attempt(JobState.SUCCEEDED, now=now, result=JobResult(completed_at=now))
            if foreign:
                return replace(completed, **{foreign:'different-identity'})
            self._jobs[str(lease.job_id)] = completed
            return completed

        def cancel_lease(self, lease, *, now, expected_version):
            return self.recover(lease, now)

        def fail(self, lease, failure, *, now, expected_version):
            return self.recover(lease, now)

    def handler(_job, _lease, *, cancelled):
        if port == 'cancel':
            raise WorkerCancelled('synthetic cancellation')
        raise RuntimeError('synthetic-sensitive-failure-marker')

    original = job(suffix='recovery-scope')
    queue = RecoveryQueue([original])
    events = []
    worker = make_runtime(queue, ManualClock(), handler, event_sink=events.append)
    try:
        batch = worker.run_once()
        assert batch.succeeded == worker.metrics().succeeded == int(foreign is None)
        assert batch.queue_errors == worker.metrics().queue_errors == int(foreign is not None)
        assert batch.cancelled == batch.failed == batch.lease_lost == 0
        assert queue.recovery_calls == 1
        assert queue.acknowledged == []
        if foreign:
            assert queue._jobs[str(original.job_id)].state is JobState.RUNNING
            assert not any(e['event']=='worker.job.succeeded' for e in events)
            assert len([e for e in events if e['event']=='worker.queue.error'])==1
        else:
            assert queue._jobs[str(original.job_id)].state is JobState.SUCCEEDED
        assert 'synthetic-sensitive-failure-marker' not in str(events)
        later = worker.run_once()
        assert later.succeeded == later.queue_errors == 0
        assert queue.recovery_calls == 1
    finally:
        worker.shutdown()
