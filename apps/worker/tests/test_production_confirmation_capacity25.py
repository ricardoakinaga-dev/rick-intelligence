"""Canonical confirmation validity, timeout facts and bounded admission."""
from dataclasses import replace
from threading import Event, Thread
import pytest
from rick_jobs import Job, JobFailure, JobResult, JobState
from runtime import WorkerCancelled, RuntimeConfigurationError
from test_runtime import FakeQueue, ManualClock, job, make_runtime, success
SECRET="synthetic-runtime25-sensitive-marker"
def record(*args, **kwargs): pass

def response(current, state, now, foreign=None):
    if state is JobState.SUCCEEDED:
        value = current.finish_attempt(state, now=now, result=JobResult(completed_at=now))
    elif state in (JobState.FAILED, JobState.RETRYING, JobState.DEAD_LETTER, JobState.QUEUED):
        value = current.finish_attempt(JobState.FAILED, now=now, failure=JobFailure(
            code='handler_failed', message='The operation failed.', retryable=True,
            attempt=current.attempt_count, occurred_at=now))
        if state in (JobState.RETRYING, JobState.DEAD_LETTER):
            value = value.transition(state, now=now)
        elif state is JobState.QUEUED:
            value = value.transition(JobState.RETRYING, now=now).transition(state, now=now)
    elif state is JobState.CANCELLED:
        value = current.finish_attempt(state, now=now)
    elif state is JobState.PENDING:
        value = Job.create(job_id=current.job_id, tenant_id=current.tenant_id,
            workspace_id=current.workspace_id, collection_id=current.collection_id,
            operation=current.operation, idempotency_key=current.idempotency_key,
            payload=current.payload, now=now)
    else:
        value = current
    return replace(value, **{foreign: 'foreign-independent'}) if foreign else value

class ReturningQueue(FakeQueue):
    def __init__(self, jobs, state, foreign=None, invalid=False, error=None):
        super().__init__(jobs)
        self.state, self.foreign, self.invalid, self.error = state, foreign, invalid, error
        self.mutations = []
    def confirm(self, port, lease, now):
        self.mutations.append(port)
        if self.error: raise self.error(SECRET)
        if self.invalid: return None
        return response(self._jobs[str(lease.job_id)], self.state, now, self.foreign)
    def acknowledge(self, lease, result, *, now, expected_version, deadline=None):
        return self.confirm('ack', lease, now)
    def fail(self, lease, failure, *, now, expected_version):
        assert SECRET not in failure.message
        return self.confirm('failure', lease, now)
    def cancel_lease(self, lease, *, now, expected_version):
        return self.confirm('cancel', lease, now)

def handler_for(port):
    def handler(j, l, *, cancelled):
        if port == 'cancel': raise WorkerCancelled(SECRET)
        if port == 'failure': raise RuntimeError(SECRET)
        return success(j, l, cancelled=cancelled)
    return handler

@pytest.mark.parametrize('port', ['ack', 'cancel', 'failure', 'poison'])
def test_missing_canonical_confirmation_is_queue_error(port):
    queue = ReturningQueue([job(operation='unknown' if port == 'poison' else 'ingest')],
                           JobState.RUNNING, invalid=True)
    worker = make_runtime(queue, ManualClock(), handler_for(port))
    try:
        batch = worker.run_once()
        record('missing-confirmation', port=port, batch=batch.as_dict(), metrics=worker.metrics().as_dict())
        assert batch.queue_errors == worker.metrics().queue_errors == 1
        assert batch.failed == batch.cancelled == batch.succeeded == 0
    finally: worker.shutdown(timeout=0)

@pytest.mark.parametrize('port', ['poison', 'failure', 'cancel'])
def test_pending_confirmation_is_rejected(port):
    queue = ReturningQueue([job(operation='unknown' if port == 'poison' else 'ingest')], JobState.PENDING)
    worker = make_runtime(queue, ManualClock(), handler_for(port))
    try:
        batch = worker.run_once()
        record('pending-confirmation', port=port, batch=batch.as_dict(), metrics=worker.metrics().as_dict())
        assert batch.queue_errors == 1
        assert batch.completed == 0
    finally: worker.shutdown(timeout=0)

@pytest.mark.parametrize('state', [JobState.RUNNING, JobState.SUCCEEDED, JobState.CANCELLED,
                                 JobState.FAILED, JobState.DEAD_LETTER, JobState.QUEUED])
@pytest.mark.parametrize('daemon', [False, True])
def test_timeout_reporting_is_independent_of_recovered_outcome(state, daemon):
    released = Event()
    clock = ManualClock()
    queue = ReturningQueue([job(suffix='timeout')], state)
    worker = None
    def handler(j, l, *, cancelled):
        assert released.wait(2)
        return JobResult(completed_at=j.updated_at)
    def controlled_sleep(seconds):
        clock.advance(.02)
        worker.request_stop()
    worker = make_runtime(queue, clock, handler, handler_timeout_seconds=.01,
                          sleep_fn=controlled_sleep)
    try:
        if daemon:
            batch = worker.run_forever(max_runtime_seconds=.02)
        else:
            batch = worker.run_once(wait=True)
        record('timeout-recovery', state=state.value, daemon=daemon,
               batch=batch.as_dict(), metrics=worker.metrics().as_dict(),
               execution_timeout=next(iter(worker._active.values())).timed_out)
        assert worker.metrics().timed_out == 1
        assert batch.timed_out == 1
        assert len(queue.mutations) == 1
    finally:
        released.set()
        for execution in tuple(worker._active.values()): assert execution.handler_done.wait(2)
        worker.shutdown(timeout=0)

def test_claimed_metrics_count_jobs_not_batches():
    queue = FakeQueue([job(suffix=str(n)) for n in range(4)])
    worker = make_runtime(queue, ManualClock(), success, max_concurrency=4)
    try:
        batch = worker.run_once()
        record('claimed-metrics', batch=batch.as_dict(), metrics=worker.metrics().as_dict())
        assert worker.metrics().claimed == batch.claimed == 4
    finally: worker.shutdown(timeout=0)



def test_concurrent_drivers_preserve_capacity_and_remaining_jobs():
    first_claim, second_claim, release_claim, release_handler = (Event() for _ in range(4))
    class BlockedClaimQueue(FakeQueue):
        calls = 0
        def claim(self, **kwargs):
            self.calls += 1
            (first_claim if self.calls == 1 else second_claim).set()
            assert release_claim.wait(2)
            return super().claim(**kwargs)
    queue = BlockedClaimQueue([job(suffix='driver-a'), job(suffix='driver-b')])
    def handler(j, l, *, cancelled):
        assert release_handler.wait(2)
        return success(j, l, cancelled=cancelled)
    worker = make_runtime(queue, ManualClock(), handler, max_concurrency=1)
    batches, failures = [], []
    def drive():
        try: batches.append(worker.run_once(wait=False))
        except BaseException as e: failures.append(e)
    threads = [Thread(target=drive) for _ in range(2)]
    try:
        worker.start()
        threads[0].start(); assert first_claim.wait(1)
        threads[1].start()
        second_claim.wait(.05)
        release_claim.set()
        for thread in threads: thread.join(1); assert not thread.is_alive()
        assert failures == [] and len(batches) == 2
        assert worker.active_count == worker.metrics().max_active == 1
        assert sum(b.claimed for b in batches) == sum(b.started for b in batches) == 1
        assert sum(b.backpressured for b in batches) == 1
        release_handler.set(); assert worker.wait_for_idle(timeout=1)
        remaining = worker.run_once()
        assert remaining.claimed == remaining.succeeded == 1
        assert worker.metrics().claimed == worker.metrics().succeeded == 2
    finally:
        release_claim.set(); release_handler.set()
        for thread in threads:
            if thread.ident is not None: thread.join(2)
        worker.shutdown(timeout=0)

@pytest.mark.parametrize('kind', ['shape', 'scope', 'lease_identity', 'worker_identity', 'expired'])
def test_invalid_claim_poison_counters_match_batch_and_metrics(kind):
    class InvalidClaimQueue(FakeQueue):
        def claim(self, **kwargs):
            items = super().claim(**kwargs)
            if not items: return items
            current, lease = items[0]
            now = kwargs['now']
            if kind == 'shape': return (None,)
            if kind == 'scope': current = replace(current, collection_id='foreign-independent')
            if kind == 'lease_identity': lease = replace(lease, job_id='foreign-independent')
            if kind == 'worker_identity': lease = replace(lease, worker_id='foreign-independent')
            if kind == 'expired': lease = replace(lease, acquired_at=now-2, heartbeat_at=now-1, expires_at=now-.5)
            return ((current, lease),)
    queue = InvalidClaimQueue([job()])
    worker = make_runtime(queue, ManualClock(), success)
    try:
        batch = worker.run_once()
        record('invalid-claim', kind=kind, batch=batch.as_dict(), metrics=worker.metrics().as_dict())
        assert batch.started == batch.completed == 0
        assert batch.queue_errors == worker.metrics().queue_errors == 1
        assert queue.failures == queue.acknowledged == queue.cancel_lease_calls == []
        assert batch.poisoned == worker.metrics().poisoned == 1
    finally: worker.shutdown(timeout=0)


@pytest.mark.parametrize('driver', ['cycle', 'daemon'])
def test_daemon_owns_polling_until_it_returns(driver):
    entered, release = Event(), Event()
    clock = ManualClock()
    queue = FakeQueue([])
    failures = []
    worker = None
    def sleeping(seconds):
        clock.advance(seconds)
        entered.set()
        release.wait(1)
        worker.request_stop()
    worker = make_runtime(queue, clock, success, sleep_fn=sleeping)
    def daemon():
        try: worker.run_forever(max_runtime_seconds=.1)
        except BaseException as error: failures.append(error)
    thread = Thread(target=daemon)
    try:
        thread.start(); assert entered.wait(1)
        with pytest.raises(RuntimeConfigurationError):
            if driver == 'cycle': worker.run_once(wait=False)
            else: worker.run_forever(max_runtime_seconds=.001)
    finally:
        release.set(); thread.join(2); assert not thread.is_alive()
        assert failures == []
        assert worker.run_once().claimed == 0
        worker.shutdown(timeout=0)


def test_invalid_daemon_configuration_releases_poll_owner():
    worker = make_runtime(FakeQueue([job()]), ManualClock(), success)
    try:
        with pytest.raises(RuntimeConfigurationError):
            worker.run_forever(max_runtime_seconds=0)
        assert worker.run_once().succeeded == 1
    finally: worker.shutdown(timeout=0)


def test_mutation_port_cannot_reenter_admission():
    attempts = []
    worker = None
    class ReentrantQueue(FakeQueue):
        def fail(self, lease, failure, *, now, expected_version):
            with pytest.raises(RuntimeConfigurationError):
                worker.run_once(wait=False)
            attempts.append(True)
            return super().fail(lease, failure, now=now, expected_version=expected_version)
    queue = ReentrantQueue([job(operation='unknown'), job(suffix='valid')])
    worker = make_runtime(queue, ManualClock(), success, max_concurrency=1)
    try:
        first = worker.run_once()
        assert attempts == [True] and first.poisoned == first.failed == 1
        assert worker.metrics().started == 0
        assert worker.run_once().succeeded == 1
        assert worker.metrics().max_active == 1
    finally: worker.shutdown(timeout=0)
