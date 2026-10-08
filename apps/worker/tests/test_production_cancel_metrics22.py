"""Cancellation queue errors remain visible independently of job outcome."""
import pytest

from rick_jobs import JobState
from runtime import WorkerCancelled
from test_runtime import FakeQueue, LeaseLost, ManualClock, job, make_runtime


@pytest.mark.parametrize('release', ['error', 'lost', 'running', 'succeeded', 'cancelled'])
def test_cancel_release_counts_queue_error_in_batch_and_metrics(release):
    class CancellationQueue(FakeQueue):
        def cancel_lease(self, lease, *, now, expected_version):
            self.cancel_lease_calls.append(str(lease.job_id))
            if release == 'error':
                raise RuntimeError('synthetic-sensitive-exception-marker')
            if release == 'lost':
                raise LeaseLost('synthetic-sensitive-exception-marker')
            current = self._jobs[str(lease.job_id)]
            if release == 'running':
                return current
            if release == 'succeeded':
                from rick_jobs import JobResult
                result = current.finish_attempt(JobState.SUCCEEDED, now=now, result=JobResult(completed_at=now))
            else:
                result = current.finish_attempt(JobState.CANCELLED, now=now)
            self._jobs[str(lease.job_id)] = result
            return result

    def cancelled_handler(_job, _lease, *, cancelled):
        raise WorkerCancelled('synthetic cancellation')

    original = job(suffix='cancel-metrics')
    queue = CancellationQueue([original])
    events = []
    worker = make_runtime(queue, ManualClock(), cancelled_handler, event_sink=events.append)
    try:
        batch = worker.run_once()
        metrics = worker.metrics()
        errors = int(release == 'error')
        assert batch.queue_errors == metrics.queue_errors == errors
        assert batch.cancelled == metrics.cancelled == int(release in ['error', 'cancelled'])
        assert batch.lease_lost == metrics.lease_lost == int(release in ['lost', 'running'])
        assert batch.succeeded == metrics.succeeded == int(release == 'succeeded')
        assert queue.failures == queue.acknowledged == []
        assert queue.cancel_lease_calls == [str(original.job_id)]
        if release in ['error', 'lost', 'running']:
            assert queue._jobs[str(original.job_id)].state is JobState.RUNNING
        queue_events = [e for e in events if e['event'] == 'worker.queue.error']
        assert len(queue_events) == errors
        assert 'synthetic-sensitive-exception-marker' not in str(events)
        again = worker.run_once()
        assert again.queue_errors == again.cancelled == again.succeeded == 0
        assert worker.metrics().queue_errors == errors
        assert queue.cancel_lease_calls == [str(original.job_id)]
    finally:
        worker.shutdown()
