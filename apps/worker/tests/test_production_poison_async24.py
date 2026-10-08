"""Canonical poison confirmations and delayed daemon error thresholds."""
from dataclasses import replace
from threading import Event
import pytest
from rick_jobs import JobState, JobResult, JobFailure
from runtime import WorkerCancelled
from test_runtime import FakeQueue, LeaseLost, ManualClock, job, make_runtime, success

MARKER = 'synthetic-I1-raw-secret-token'
DIMENSIONS = [None, 'job_id', 'tenant_id', 'workspace_id', 'collection_id']
STATES = [JobState.RUNNING, JobState.CANCELLED, JobState.FAILED, JobState.SUCCEEDED]


def returned(current, state, now, dimension=None):
    if state is JobState.RUNNING:
        value = current
    elif state is JobState.SUCCEEDED:
        value = current.finish_attempt(state, now=now, result=JobResult(completed_at=now))
    elif state is JobState.FAILED:
        value = current.finish_attempt(state, now=now, failure=JobFailure(code='handler_failed', message='The operation failed.', retryable=False, attempt=current.attempt_count, occurred_at=now))
    else:
        value = current.finish_attempt(state, now=now)
    return replace(value, **{dimension: 'foreign-I1-identity'}) if dimension else value


class ConfirmationQueue(FakeQueue):
    def __init__(self, jobs, state, dimension=None, error=None):
        super().__init__(jobs)
        self.state, self.dimension, self.error = state, dimension, error
        self.calls = []
        self.snapshots = {}

    def confirm(self, port, lease, now):
        key = str(lease.job_id)
        self.calls.append(port)
        self.snapshots[key] = (self._jobs[key], self._leases[key])
        if self.error:
            raise self.error(MARKER)
        # Inject a returned confirmation while intentionally not writing state.
        return returned(self._jobs[key], self.state, now, self.dimension)

    def acknowledge(self, lease, result, *, now, expected_version, deadline=None):
        assert expected_version == self._jobs[str(lease.job_id)].version
        return self.confirm('ack', lease, now)

    def fail(self, lease, failure, *, now, expected_version):
        assert expected_version == self._jobs[str(lease.job_id)].version
        assert MARKER not in failure.message
        return self.confirm('failure', lease, now)

    def cancel_lease(self, lease, *, now, expected_version):
        assert expected_version == self._jobs[str(lease.job_id)].version
        return self.confirm('cancel', lease, now)


def expected_outcome(port, state, dimension=None, error=None):
    if error is LeaseLost:
        return 'lease_lost', 0
    if error:
        return ('cancelled' if port == 'cancel' else 'queue_error'), 1
    if dimension:
        return 'queue_error', 1
    if state is JobState.SUCCEEDED:
        return 'succeeded', 0
    if state is JobState.RUNNING:
        return 'lease_lost', 0
    if port == 'ack':
        return 'queue_error', 1
    if port == 'cancel' or state is JobState.CANCELLED:
        return 'cancelled', 0
    return 'failed', 0


def check_counters(batch, metrics, outcome, errors):
    for name in ('succeeded', 'failed', 'cancelled', 'lease_lost'):
        assert getattr(batch, name) == getattr(metrics, name) == int(name == outcome)
    assert batch.queue_errors == metrics.queue_errors == errors



@pytest.mark.parametrize('trigger', ['unknown_operation', 'payload_too_large'])
@pytest.mark.parametrize('dimension', DIMENSIONS)
@pytest.mark.parametrize('state', STATES)
def test_poison_confirmation_observation(trigger, dimension, state):
    original = job(operation='unknown' if trigger == 'unknown_operation' else 'ingest', payload={'source_key': MARKER * 10}, suffix='I1-poison')
    queue = ConfirmationQueue([original], state, dimension)
    events, executions = [], []
    def handler(j, l, *, cancelled):
        executions.append(j)
        return success(j, l, cancelled=cancelled)
    worker = make_runtime(queue, ManualClock(), handler, event_sink=events.append,
                          max_payload_bytes=32768 if trigger == 'unknown_operation' else 32)
    try:
        batch = worker.run_once()
        assert executions == [] and batch.started == 0 and batch.poisoned == 1
        assert queue.calls == ['failure']
        assert queue._jobs[str(original.job_id)].state is JobState.RUNNING
        assert queue._leases[str(original.job_id)] == queue.snapshots[str(original.job_id)][1]
        assert MARKER not in str(events) and 'foreign-I1-identity' not in str(events)
        # Poison detection and the confirmed resulting state are independent.
        expected, errors = expected_outcome('failure', state, dimension)
        check_counters(batch, worker.metrics(), expected, errors)
        assert len([e for e in events if e['event'] == 'worker.job.poisoned']) == 1
        assert worker.run_once().completed == 0 and queue.calls == ['failure']
    finally:
        worker.shutdown()


@pytest.mark.parametrize('port', ['cancel', 'failure'])
@pytest.mark.parametrize('max_runtime', [.001, .1])
def test_daemon_counts_delayed_confirmation_errors(port, max_runtime):
    clock = ManualClock()
    released = Event()
    calls = []
    queue = ConfirmationQueue([job(suffix='I1-late')], JobState.RUNNING, error=RuntimeError)
    def handler(j, l, *, cancelled):
        calls.append(j)
        assert released.wait(2)
        if port == 'cancel':
            raise WorkerCancelled(MARKER)
        raise RuntimeError(MARKER)
    worker = None
    sleeps = []
    def controlled_sleep(seconds):
        sleeps.append(seconds)
        clock.advance(seconds)
        if len(sleeps) == 1:
            # Initial nonwaiting batch returned before the handler completed.
            execution = next(iter(worker._active.values()))
            released.set()
            assert execution.handler_done.wait(2)
        else:
            worker.request_stop()
    events = []
    worker = make_runtime(queue, clock, handler, sleep_fn=controlled_sleep,
                          max_consecutive_queue_errors=1, event_sink=events.append)
    try:
        totals = worker.run_forever(max_runtime_seconds=max_runtime)
        assert len(calls) == 1 and queue.calls == [port]
        assert worker.metrics().queue_errors == 1
        assert totals.queue_errors == worker.metrics().queue_errors == 1
        assert worker._consecutive_queue_errors == 1 and worker.health().reason == 'queue_unavailable'
        assert totals.cancelled == int(port == 'cancel') and totals.failed == 0
        assert worker.metrics().cancelled == int(port == 'cancel')
        assert worker.active_count == 0
        assert len([e for e in events if e['event'] == 'worker.queue.error']) == 1
        assert MARKER not in str(events)
    finally:
        released.set()
        worker.shutdown()


def test_daemon_counts_mixed_delayed_confirmations_once():
    clock = ManualClock()
    released = Event()
    originals = [job(suffix=f'I1-async-mixed-{n}') for n in range(4)]
    queue = ConfirmationQueue(originals, JobState.SUCCEEDED)
    routes = {str(j.job_id): n for n,j in enumerate(originals)}
    calls = []
    def confirm(port, lease, now):
        n = routes[str(lease.job_id)]
        queue.calls.append(port)
        key = str(lease.job_id)
        queue.snapshots[key] = (queue._jobs[key], queue._leases[key])
        if n == 0:
            raise RuntimeError(MARKER)
        return returned(queue._jobs[key], JobState.RUNNING if n == 3 else JobState.SUCCEEDED,
                        now, 'collection_id' if n == 1 else None)
    queue.confirm = confirm
    def handler(j,l,*,cancelled):
        calls.append(str(j.job_id))
        assert released.wait(2)
        if routes[str(j.job_id)] == 0:
            raise WorkerCancelled(MARKER)
        if routes[str(j.job_id)] == 1:
            raise RuntimeError(MARKER)
        return success(j,l,cancelled=cancelled)
    sleeps = []
    worker = None
    def controlled_sleep(seconds):
        sleeps.append(seconds)
        clock.advance(seconds)
        if len(sleeps) == 1:
            executions = tuple(worker._active.values())
            assert len(executions) == 4
            released.set()
            assert all(e.handler_done.wait(2) for e in executions)
        else:
            worker.request_stop()
    events = []
    worker = make_runtime(queue, clock, handler, sleep_fn=controlled_sleep,
                          max_concurrency=4, max_consecutive_queue_errors=1, event_sink=events.append)
    try:
        totals = worker.run_forever(max_runtime_seconds=.1)
        metrics = worker.metrics()
        assert totals.claimed == totals.started == 4
        assert metrics.queue_errors == 2 and metrics.cancelled == metrics.succeeded == metrics.lease_lost == 1
        assert totals.queue_errors == 2 and totals.cancelled == totals.succeeded == totals.lease_lost == 1
        assert worker.health().reason == 'queue_unavailable' and worker._consecutive_queue_errors == 2
        assert len(calls) == len(set(calls)) == len(queue.calls) == 4
        assert worker.active_count == 0
        assert len([e for e in events if e['event'] == 'worker.queue.error']) == 2
        for key,(original,lease) in queue.snapshots.items():
            assert queue._jobs[key] == original and queue._leases[key] == lease
        assert MARKER not in str(events)
    finally:
        released.set()
        worker.shutdown()
