"""A handler result is not success until the scoped queue confirms it."""
import pytest

from rick_jobs import JobState
from test_runtime import FakeQueue, ManualClock, job, make_runtime, success


@pytest.mark.parametrize('response', ['running', 'missing', 'foreign_success', 'success'])
def test_runtime_success_requires_terminal_acknowledgement_for_its_job(response):
    class AcknowledgementQueue(FakeQueue):
        def acknowledge(self, lease, result, *, now, expected_version, deadline=None):
            if response == 'success':
                return super().acknowledge(lease, result, now=now,
                                           expected_version=expected_version, deadline=deadline)
            if response == 'missing':
                return None
            if response == 'foreign_success':
                other = job(suffix='other-job').start_attempt(worker_id='worker-a', now=now)
                return other.finish_attempt(JobState.SUCCEEDED, now=now, result=result)
            return self._jobs[str(lease.job_id)]

    original = job(suffix='ack-deferred')
    queue = AcknowledgementQueue([original])
    events = []
    runtime = make_runtime(queue, ManualClock(), success, event_sink=events.append)
    batch = runtime.run_once()
    runtime.shutdown()

    if response == 'success':
        assert batch.succeeded == runtime.metrics().succeeded == 1
        assert queue._jobs[str(original.job_id)].state is JobState.SUCCEEDED
        assert len(queue.acknowledged) == 1
    else:
        assert batch.succeeded == runtime.metrics().succeeded == 0
        assert queue._jobs[str(original.job_id)].state is JobState.RUNNING
        assert queue.acknowledged == []
        assert queue.failures == []
        assert not any(event['event'] == 'worker.job.succeeded' for event in events)
        if response == 'running':
            assert batch.lease_lost == runtime.metrics().lease_lost == 1
            assert batch.queue_errors == runtime.metrics().queue_errors == 0
        else:
            assert batch.queue_errors == runtime.metrics().queue_errors == 1
