"""Cancellation metrics never fabricate durable settlement from failed IO.

Candidate3 strengthens legacy error=>cancelled and RUNNING=>lease_lost
measurements: those responses leave the actual row RUNNING and ownership pending.
"""
from threading import Event, current_thread
from types import SimpleNamespace
import pytest

from rick_jobs import JobState
from runtime import WorkerCancelled
from deployment_composition import DeploymentRuntime
from test_runtime import FakeQueue, LeaseLost, ManualClock, job, make_runtime


@pytest.mark.parametrize('release', ['error', 'lost', 'running', 'succeeded', 'cancelled'])
def test_cancel_release_counts_queue_error_in_batch_and_metrics(release):
    class CancellationQueue(FakeQueue):
        allow_retry = False
        def cancel_lease(self, lease, *, now, expected_version):
            assert expected_version == self._jobs[str(lease.job_id)].version
            assert lease.token == self._leases[str(lease.job_id)].token
            if self.allow_retry:
                return super().cancel_lease(lease, now=now, expected_version=expected_version)
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

    threads, entered = [], Event()
    def cancelled_handler(_job, _lease, *, cancelled):
        threads.append(current_thread())
        entered.set()
        raise WorkerCancelled('synthetic cancellation')

    original = job(suffix='cancel-metrics')
    queue = CancellationQueue([original])
    events, clock = [], ManualClock()
    def wait_for_handler(seconds):
        assert entered.wait(1)
        threads[0].join(1)
        assert not threads[0].is_alive()
        clock.advance(seconds)
    worker = make_runtime(queue, clock, cancelled_handler, event_sink=events.append,
        sleep_fn=wait_for_handler)
    try:
        batch = worker.run_once()
        assert len(threads) == 1
        threads[0].join(1)
        assert not threads[0].is_alive()
        worker._reap()
        metrics = worker.metrics()
        pending = release in {'error', 'running'}
        errors = int(pending)
        assert batch.queue_errors == metrics.queue_errors == errors
        assert batch.cancelled == metrics.cancelled == int(release == 'cancelled')
        assert batch.lease_lost == metrics.lease_lost == int(release == 'lost')
        assert batch.succeeded == metrics.succeeded == int(release == 'succeeded')
        assert queue.failures == queue.acknowledged == []
        assert queue.cancel_lease_calls == [str(original.job_id)]
        if release in ['error', 'lost', 'running']:
            assert queue._jobs[str(original.job_id)].state is JobState.RUNNING
        assert len([e for e in events if e['event'] == 'worker.queue.error']) == errors
        assert 'synthetic-sensitive-exception-marker' not in str(events)
        again = worker.run_once()
        assert again.queue_errors == again.cancelled == again.succeeded == 0
        assert worker.metrics().queue_errors == errors
        assert queue.cancel_lease_calls == [str(original.job_id)]
        if pending:
            assert again.backpressured and len(worker._pending_recovery) == 1
            class Store:
                calls = 0
                def close(self):
                    self.calls += 1
            store = Store()
            composition = DeploymentRuntime(SimpleNamespace(worker=worker, object_store=store))
            # Time passing is not an expiry guarantee for this arbitrary port.
            clock.advance(queue.lease_seconds + 1)
            report = worker.shutdown(timeout=0)
            assert not report.drained and report.pending_claims == 1
            assert worker.wait_for_idle(timeout=0) is False
            assert composition.shutdown(timeout=0) is False and store.calls == 0
            assert queue._jobs[str(original.job_id)].state is JobState.RUNNING
            assert worker.metrics().cancelled == worker.metrics().lease_lost == 0
            queue.allow_retry = True
            assert composition.shutdown(timeout=1) is True and store.calls == 1
            assert queue._jobs[str(original.job_id)].state is JobState.CANCELLED
            settled_version = queue._jobs[str(original.job_id)].version
            settled_calls = len(queue.cancel_lease_calls)
            assert composition.shutdown(timeout=1) is True and store.calls == 1
            assert queue._jobs[str(original.job_id)].version == settled_version
            assert len(queue.cancel_lease_calls) == settled_calls
    finally:
        worker.shutdown(timeout=0)
