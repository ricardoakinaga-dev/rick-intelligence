"""PROD12-008/009/010 shutdown regressions; Event-controlled, no sleeps."""
import builtins
import importlib.util
import sys
from contextlib import contextmanager
from threading import Event, Thread
import runtime as runtime_module
from types import SimpleNamespace
import pytest
from runtime import CancellationToken, ShutdownReport
from rick_jobs import JobState
from deployment_composition import DeploymentRuntime
from worker.tests.test_runtime import FakeQueue, LeaseLost, ManualClock, SCOPE, job, make_runtime, success


def finish(worker, release):
    release.set()
    for execution in tuple(worker._active.values()):
        if execution.thread is not None and execution.thread.ident is not None:
            execution.thread.join(2)
            assert not execution.thread.is_alive()
    worker.wait_for_idle(timeout=0)


def test_A02_repeated_shutdown_must_not_claim_drain_with_live_handler():
    entered, release = Event(), Event()
    queue = FakeQueue([job(suffix='a02')])
    def handler(j, lease, *, cancelled):
        entered.set()
        assert release.wait(2)
        return success(j, lease, cancelled=cancelled)
    worker = make_runtime(queue, ManualClock(), handler, sleep_fn=lambda _: None)
    try:
        worker.run_once(wait=False)
        assert entered.wait(1)
        first = worker.shutdown(timeout=0)
        idle = worker.wait_for_idle(timeout=0)
        second = worker.shutdown(deadline_seconds=0)
        print('A02', first.as_dict(), second.as_dict(), 'wait_for_idle=', idle,
              'cancel_calls=', len(queue.cancel_lease_calls), 'ack=', len(queue.acknowledged))
        assert first.drained is False and first.active == 1 and first.timed_out
        assert not worker.is_closed
        assert idle is False
        assert second.drained is False and second.active == 1 and second.timed_out
        assert first.cancelled == 1 and second.cancelled == 0
        assert len(queue.cancel_lease_calls) == 1 and not queue.acknowledged
        finish(worker, release)
        final = worker.shutdown(timeout=0)
        assert final == worker.shutdown(timeout=0) == ShutdownReport(True, False, 0, 0)
        assert worker.is_closed and worker.wait_for_idle(timeout=0)
    finally:
        finish(worker, release)
        print('A02 after release', worker.shutdown(timeout=0).as_dict())


def test_A03_claim_inflight_must_count_until_reconciled_and_never_start_handler():
    entered, release, handler_entered = Event(), Event(), Event()
    class HeldClaim(FakeQueue):
        def claim(self, **kwargs):
            entered.set()
            assert release.wait(2)
            return super().claim(**kwargs)
    queue = HeldClaim([job(suffix='a03')])
    def handler(j, lease, *, cancelled):
        handler_entered.set()
        return success(j, lease, cancelled=cancelled)
    worker = make_runtime(queue, ManualClock(), handler, sleep_fn=lambda _: None)
    errors, batches = [], []
    def drive():
        try:
            batches.append(worker.run_once(wait=False))
        except BaseException as error:
            errors.append(type(error).__name__)
    driver = Thread(target=drive)
    try:
        driver.start()
        assert entered.wait(1)
        report = worker.shutdown(timeout=0)
        idle = worker.wait_for_idle(timeout=0)
        release.set()
        driver.join(2)
        assert not driver.is_alive()
        finish(worker, release)
        print('A03', report.as_dict(), 'wait_for_idle=', idle,
              'handler_started=', handler_entered.is_set(), 'cancel=', len(queue.cancel_lease_calls),
              'ack=', len(queue.acknowledged), 'errors=', errors,
              'batches=', [b.as_dict() for b in batches])
        assert not errors
        assert report.drained is False and report.timed_out is True
        assert report.pending_claims == 1 and report.active == 0
        assert worker.shutdown(timeout=0).pending_claims == 0
        assert idle is False
        assert not handler_entered.is_set()
        assert len(queue.cancel_lease_calls) == 1 and not queue.acknowledged
    finally:
        release.set()
        driver.join(2)
        finish(worker, release)
        worker.shutdown(timeout=0)


@pytest.mark.parametrize('report', [ShutdownReport(False, False, 0, 0),
                                    ShutdownReport(True, False, 0, 1)])
def test_A010_inconsistent_or_incomplete_report_must_keep_dependencies_open(report):
    class Spy:
        closes = 0
        def close(self):
            self.closes += 1
    class Worker:
        def shutdown(self, **kwargs):
            return report
    spy = Spy()
    composition = DeploymentRuntime(SimpleNamespace(worker=Worker(), object_store=spy, provider=spy))
    result = composition.shutdown(timeout=1)
    print('A010 injected', report.as_dict(), 'result=', result, 'closes=', spy.closes)
    assert result is False and spy.closes == 0


def test_A010_real_repeated_shutdown_must_keep_stores_open_until_actual_drain():
    entered, release = Event(), Event()
    queue = FakeQueue([job(suffix='a010')])
    def handler(j, lease, *, cancelled):
        entered.set()
        assert release.wait(2)
        return success(j, lease, cancelled=cancelled)
    class Spy:
        closes = 0
        def close(self):
            self.closes += 1
    clock = ManualClock()
    worker = make_runtime(queue, clock, handler, sleep_fn=clock.advance)
    spy = Spy()
    composition = DeploymentRuntime(SimpleNamespace(worker=worker, object_store=spy, provider=spy))
    try:
        worker.run_once(wait=False)
        assert entered.wait(1)
        first = composition.shutdown(timeout=0.01)
        second = composition.shutdown(timeout=1)
        print('A010 real', 'first=', first, 'second=', second,
              'active=', worker.active_count, 'closes=', spy.closes)
        assert first is False
        assert second is False and spy.closes == 0
    finally:
        finish(worker, release)
        final = composition.shutdown(timeout=1)
        print('A010 after release', 'result=', final, 'closes=', spy.closes)
        assert final is True and spy.closes == 1
        assert composition.shutdown(timeout=1) is True and spy.closes == 1


class CloseSpy:
    def __init__(self, *, failures=0):
        self.calls = 0
        self.failures = failures

    def close(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError('synthetic close failure')


def driver_for(worker):
    results, errors = [], []
    def drive():
        try:
            results.append(worker.run_once(wait=False))
        except BaseException as error:
            errors.append(type(error).__name__)
    return Thread(target=drive), results, errors


def join_driver(driver):
    if driver.ident is not None:
        driver.join(2)
        assert not driver.is_alive()


@pytest.mark.parametrize('stop', ['request_stop', 'shutdown'])
def test_stop_between_claim_validation_and_execution_admission_is_atomic(monkeypatch, stop):
    entered, release = Event(), Event()
    calls = []
    queue = FakeQueue([job(suffix='admission-gap')])
    def handler(j, lease, *, cancelled):
        calls.append(j.job_id)
        return success(j, lease, cancelled=cancelled)
    worker = make_runtime(queue, ManualClock(), handler, sleep_fn=lambda _: None)
    original_size = worker._payload_size
    def held_validation(j):
        entered.set()
        assert release.wait(2)
        return original_size(j)
    monkeypatch.setattr(worker, '_payload_size', held_validation)
    driver, results, errors = driver_for(worker)
    try:
        driver.start()
        assert entered.wait(1)
        if stop == 'request_stop':
            worker.request_stop()
            worker.request_stop()  # simulated repeated SIGTERM stop callback
        report = worker.shutdown(timeout=0)
        assert report.active == 0 and report.pending_claims == 1 and not report.drained
        release.set()
        join_driver(driver)
        assert errors == [] and len(results) == 1
        assert results[0].started == 0 and results[0].cancelled == 1
        assert calls == [] and not queue.acknowledged and not queue.failures
        assert len(queue.cancel_lease_calls) == 1
        assert worker.shutdown(timeout=0).drained
    finally:
        release.set()
        join_driver(driver)
        worker.shutdown(timeout=0)


@pytest.mark.parametrize('mode', ['success', 'lease_lost', 'error', 'unknown_port'])
def test_late_claim_reconciliation_stays_accounted_and_preserves_lease_outcomes(mode):
    entered, release_claim, reconciling, release_reconcile = (Event() for _ in range(4))
    attempts, handlers = [], []
    allow_retry = False
    class Queue(FakeQueue):
        def claim(self, **kwargs):
            entered.set()
            assert release_claim.wait(2)
            return super().claim(**kwargs)
        def cancel_lease(self, lease, **kwargs):
            attempts.append(lease.token)
            reconciling.set()
            assert release_reconcile.wait(2)
            if mode == 'lease_lost':
                raise LeaseLost('synthetic loss')
            if mode == 'error' and not allow_retry:
                raise RuntimeError('synthetic mutation failure')
            return super().cancel_lease(lease, **kwargs)
    queue = Queue([job(suffix='late-' + mode)])
    if mode == 'unknown_port':
        queue.cancel_lease = None  # No proved expiry owner in this arbitrary fake.
    def handler(j, lease, *, cancelled):
        handlers.append(j.job_id)
        return success(j, lease, cancelled=cancelled)
    clock = ManualClock()
    worker = make_runtime(queue, clock, handler, sleep_fn=clock.advance)
    store, provider = CloseSpy(), CloseSpy()
    composition = DeploymentRuntime(SimpleNamespace(worker=worker, object_store=store, provider=provider))
    driver, results, errors = driver_for(worker)
    try:
        driver.start()
        assert entered.wait(1)
        assert composition.shutdown(timeout=0) is False
        assert store.calls == provider.calls == 0
        report = worker.shutdown(timeout=0)
        assert report.pending_claims == 1 and report.active == 0 and report.timed_out
        release_claim.set()
        if mode != 'unknown_port':
            assert reconciling.wait(1)
            report = worker.shutdown(timeout=0)
            assert report.pending_claims == 1 and report.active == 0 and not report.drained
            assert worker.wait_for_idle(timeout=0) is False
            assert composition.shutdown(timeout=0) is False
            assert store.calls == provider.calls == 0
        release_reconcile.set()
        join_driver(driver)
        assert errors == [] and len(results) == 1
        assert handlers == [] and queue.acknowledged == queue.failures == []
        batch = results[0]
        assert batch.started == 0 and batch.claimed == 1
        assert batch.lease_lost == int(mode == 'lease_lost')
        assert batch.cancelled == int(mode == 'success')
        if mode in {'error', 'unknown_port'}:
            assert batch.queue_errors >= 1 and worker.metrics().queue_errors >= batch.queue_errors
            assert worker.wait_for_idle(timeout=0) is False
            report = worker.shutdown(timeout=0)
            assert report.drained is False and report.pending_claims == 1
            assert composition.shutdown(timeout=0) is False
            assert store.calls == provider.calls == 0
            assert queue._jobs['job-ingest-late-' + mode].state is JobState.RUNNING
            allow_retry = True
            if mode == 'unknown_port':
                queue.cancel_lease = Queue.cancel_lease.__get__(queue, Queue)
        else:
            assert batch.queue_errors == worker.metrics().queue_errors == 0
            assert len(attempts) == 1
        assert worker.wait_for_idle(timeout=0)
        assert composition.shutdown(timeout=1) is True
        assert composition.shutdown(timeout=1) is True
        assert store.calls == provider.calls == 1
        assert len(queue.cancel_lease_calls) == int(mode != 'lease_lost')
    finally:
        release_claim.set()
        release_reconcile.set()
        join_driver(driver)
        worker.shutdown(timeout=0)


@pytest.mark.parametrize('error', [RuntimeError, KeyboardInterrupt])
def test_claim_error_releases_pending_accounting_even_on_base_exception(error):
    entered, release = Event(), Event()
    class Queue(FakeQueue):
        def claim(self, **kwargs):
            entered.set()
            assert release.wait(2)
            raise error('synthetic claim failure')
    worker = make_runtime(Queue([]), ManualClock(), success, sleep_fn=lambda _: None)
    driver, results, errors = driver_for(worker)
    try:
        driver.start()
        assert entered.wait(1)
        assert worker.shutdown(timeout=0).pending_claims == 1
        release.set()
        join_driver(driver)
        if error is RuntimeError:
            assert errors == [] and results[0].queue_errors == 1
        else:
            assert errors == ['KeyboardInterrupt'] and results == []
        assert worker.wait_for_idle(timeout=0)
        report = worker.shutdown(timeout=0)
        assert report.drained and report.pending_claims == report.active == 0
    finally:
        release.set()
        join_driver(driver)
        worker.shutdown(timeout=0)


def test_live_trace_exit_is_not_drained_even_when_both_completion_events_are_set(monkeypatch):
    exiting, release = Event(), Event()
    @contextmanager
    def held_trace_exit(_context):
        try:
            yield
        finally:
            exiting.set()
            assert release.wait(2)
    monkeypatch.setattr(runtime_module, 'attach_trace_context', held_trace_exit)
    queue = FakeQueue([job(suffix='trace-tail')])
    clock = ManualClock()
    worker = make_runtime(queue, clock, success, sleep_fn=clock.advance)
    spy = CloseSpy()
    composition = DeploymentRuntime(SimpleNamespace(worker=worker, object_store=spy))
    try:
        worker.run_once(wait=False)
        assert exiting.wait(1)
        worker._monitor_active()
        execution = next(iter(worker._active.values()))
        assert execution.handler_done.is_set() and execution.logical_done.is_set()
        assert execution.thread.is_alive()
        for _ in range(2):
            report = worker.shutdown(timeout=0)
            assert report.active == 1 and report.pending_claims == 0 and not report.drained
            assert worker.wait_for_idle(timeout=0) is False
            assert composition.shutdown(timeout=0) is False and spy.calls == 0
        assert queue.cancel_lease_calls == [] and len(queue.acknowledged) == 1
        finish(worker, release)
        assert composition.shutdown(timeout=1) is True and spy.calls == 1
    finally:
        finish(worker, release)
        worker.shutdown(timeout=0)


@pytest.mark.parametrize('report', [
    None, False, 1, object(),
    SimpleNamespace(drained=1, timed_out=False, active=0),
    SimpleNamespace(drained=True, timed_out=0, active=0),
    SimpleNamespace(drained=True, timed_out=False, active=False),
    SimpleNamespace(drained=True, timed_out=False, active=0, pending_claims=False),
    ShutdownReport(True, False, 0, 0, 1),
    ShutdownReport(True, True, 0, 0),
])
def test_composition_rejects_unknown_nonboolean_and_pending_reports(report):
    class Worker:
        def shutdown(self, **kwargs):
            return report
    spy = CloseSpy()
    composition = DeploymentRuntime(SimpleNamespace(worker=Worker(), object_store=spy))
    assert composition.shutdown(timeout=1) is False
    assert composition.shutdown(timeout=1) is False
    assert composition.dispose(timeout=1) is False
    assert spy.calls == 0 and not composition._worker_stopped


@pytest.mark.parametrize('report', [True, ShutdownReport(True, False, 0, 0),
    SimpleNamespace(drained=True, timed_out=False, active=0)])
def test_completed_worker_close_retry_never_double_closes_successful_shared_resources(report):
    class Worker:
        calls = 0
        def shutdown(self, **kwargs):
            self.calls += 1
            return report
    worker = Worker()
    completed, failed = CloseSpy(), CloseSpy(failures=1)
    composition = DeploymentRuntime(SimpleNamespace(worker=worker, object_store=completed,
        vector_store=completed, provider=failed))
    assert composition.shutdown(timeout=1) is False
    assert completed.calls == failed.calls == worker.calls == 1
    assert composition.shutdown(timeout=1) is True
    assert composition.shutdown(timeout=1) is True
    assert completed.calls == worker.calls == 1 and failed.calls == 2


def test_shutdown_report_positional_compatibility_and_pending_serialization():
    assert ShutdownReport(True, False, 0, 0).pending_claims == 0
    report = ShutdownReport(False, True, 0, 0, 1)
    assert report.active == 0 and report.as_dict()['pending_claims'] == 1


def test_valid_tuple_launch_interrupt_hands_off_all_owned_leases_and_preserves_interrupt(monkeypatch):
    entered, release = Event(), Event()
    queue = FakeQueue([job(suffix='interrupt-first'), job(suffix='interrupt-rest')])
    events, handlers, interrupts = [], [], []
    original_interrupt = KeyboardInterrupt('synthetic launch interrupt')
    original_start = runtime_module.Thread.start
    def interrupted_start(thread):
        if thread.name.startswith('rick-worker-'):
            entered.set()
            assert release.wait(2)
            raise original_interrupt  # before any native handler thread starts
        return original_start(thread)
    def handler(j, lease, *, cancelled):
        handlers.append(j.job_id)
        return success(j, lease, cancelled=cancelled)
    worker = make_runtime(queue, ManualClock(), handler, max_concurrency=2,
        sleep_fn=lambda _: None, event_sink=events.append)
    def drive():
        try:
            worker.run_once(wait=False)
        except BaseException as error:
            interrupts.append(error)
    driver = Thread(target=drive, name='local-interrupted-admission-driver')
    monkeypatch.setattr(runtime_module.Thread, 'start', interrupted_start)
    try:
        driver.start()
        assert entered.wait(1)
        release.set()
        join_driver(driver)
        assert interrupts == [original_interrupt]
        assert interrupts[0].__traceback__ is not None
        assert handlers == [] and worker.metrics().claimed == 2
        assert queue.acknowledged == queue.cancel_lease_calls == []
        report = worker.shutdown(timeout=0)
        print('CRITIC009', 'interrupt_preserved=', interrupts[0] is original_interrupt,
              'durable_running=', sum(j.state is JobState.RUNNING for j in queue._jobs.values()),
              'report=', report.as_dict(), 'retryable_failures=', len(queue.failures))
        assert len(queue.failures) == worker.metrics().failed == 2
        assert all(f.retryable and f.code == 'handler_failed' for _, f in queue.failures)
        assert len({identity for identity, _ in queue.failures}) == 2
        assert report.drained and report.active == report.pending_claims == 0
    finally:
        release.set()
        join_driver(driver)
        worker.shutdown(timeout=0)


def test_concurrent_shutdown_does_not_enter_the_same_closer_twice():
    entered, release = Event(), Event()
    class Worker:
        def shutdown(self, **kwargs):
            return True
    class HeldClose:
        calls = 0
        def close(self):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert release.wait(2)
    spy = HeldClose()
    composition = DeploymentRuntime(SimpleNamespace(worker=Worker(), object_store=spy, provider=spy))
    first_results, errors = [], []
    def first_shutdown():
        try:
            first_results.append(composition.shutdown(timeout=2))
        except BaseException as error:
            errors.append(type(error).__name__)
    first = Thread(target=first_shutdown)
    try:
        first.start()
        assert entered.wait(1)
        second_result = composition.shutdown(timeout=1)
        print('CRITIC010', 'concurrent_result=', second_result, 'close_calls=', spy.calls)
        assert second_result is False and spy.calls == 1
        release.set()
        join_driver(first)
        assert errors == [] and first_results == [True]
        assert composition.shutdown(timeout=1) is True and spy.calls == 1
    finally:
        release.set()
        join_driver(first)


@pytest.mark.parametrize('secondary_interrupt', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('cancel_result', ['error', 'running'])
def test_interrupted_cleanup_retains_pending_owner_and_never_replaces_original(monkeypatch,
        secondary_interrupt, cancel_result):
    original_interrupt = KeyboardInterrupt('original admission interrupt')
    allow_cancel = False
    class Queue(FakeQueue):
        def fail(self, lease, failure, **kwargs):
            if str(lease.job_id).endswith('first'):
                raise secondary_interrupt('synthetic cleanup interrupt')
            return super().fail(lease, failure, **kwargs)
        def cancel_lease(self, lease, **kwargs):
            if not allow_cancel:
                if cancel_result == 'error':
                    raise RuntimeError('synthetic cancel unavailable')
                return self._jobs[str(lease.job_id)]  # RUNNING is not settlement proof
            return super().cancel_lease(lease, **kwargs)
    queue = Queue([job(suffix='first'), job(suffix='rest')])
    clock = ManualClock()
    worker = make_runtime(queue, clock, success, max_concurrency=2, sleep_fn=clock.advance)
    original_start = runtime_module.Thread.start
    def interrupted_start(thread):
        if thread.name.startswith('rick-worker-'):
            raise original_interrupt
        return original_start(thread)
    monkeypatch.setattr(runtime_module.Thread, 'start', interrupted_start)
    with pytest.raises(KeyboardInterrupt) as caught:
        worker.run_once(wait=False)
    assert caught.value is original_interrupt
    assert len(queue.failures) == worker.metrics().failed == 1
    assert all(f.retryable for _, f in queue.failures)
    assert len(worker._pending_recovery) == 1 and worker.active_count == 0
    spy = CloseSpy()
    composition = DeploymentRuntime(SimpleNamespace(worker=worker, object_store=spy))
    for _ in range(2):
        report = worker.shutdown(timeout=0)
        assert not report.drained and report.pending_claims == 1 and report.active == 0
        assert not worker.is_closed and worker.wait_for_idle(timeout=0) is False
        assert composition.shutdown(timeout=0) is False and spy.calls == 0
    assert queue.cancel_lease_calls == [] and queue.acknowledged == []
    allow_cancel = True
    assert composition.shutdown(timeout=1) is True
    assert composition.shutdown(timeout=1) is True
    assert spy.calls == 1 and len(queue.cancel_lease_calls) == 1
    assert worker.wait_for_idle(timeout=0) and worker.shutdown(timeout=0).drained


@pytest.mark.parametrize('max_attempts', [1, 2])
def test_interrupted_valid_canonical_batch_uses_actual_retryable_failure_fences(monkeypatch, max_attempts):
    from worker.tests.test_postgres_jobs import make_queue, make_job
    queue, connection = make_queue()
    queued = [queue.enqueue(make_job(job_id=f'job-interrupt-{i}', key=f'idem-interrupt-{i}',
        max_attempts=max_attempts), expected_version=0) for i in range(2)]
    connection.database_now = 104.0
    clock = ManualClock(104.0)
    worker = make_runtime(queue, clock, success, max_concurrency=2, sleep_fn=clock.advance)
    original_interrupt = KeyboardInterrupt('canonical launch interrupt')
    entered = Event()
    original_start = runtime_module.Thread.start
    def interrupted_start(thread):
        if thread.name.startswith('rick-worker-'):
            entered.set()
            raise original_interrupt
        return original_start(thread)
    monkeypatch.setattr(runtime_module.Thread, 'start', interrupted_start)
    with pytest.raises(KeyboardInterrupt) as caught:
        worker.run_once(wait=False)
    assert caught.value is original_interrupt and entered.is_set()
    assert worker.metrics().failed == 2 and worker.metrics().started == 0
    assert worker.wait_for_idle(timeout=0)
    for j in queued:
        row = connection.jobs[str(j.job_id)]
        assert row['contract_state'] == ('QUEUED' if max_attempts == 2 else 'DEAD_LETTER')
        assert row['lease_owner'] is None and row['attempts'] == 1
        attempt = connection.attempts[(str(j.job_id), 1)]
        assert attempt['state'] == 'FAILED'
        assert attempt['failure']['code'] == 'handler_failed' and attempt['failure']['retryable']
    connection.database_now = 105.0
    retried = queue.claim(worker_id='worker-b', scope=queued[0].scope, expected_versions={},
        now=105.0, limit=2)
    assert len(retried) == (2 if max_attempts == 2 else 0)
    assert all(j.attempt_count == 2 and lease.worker_id == 'worker-b' for j, lease in retried)
    assert worker.shutdown(timeout=0).drained


def test_interrupt_after_native_start_keeps_live_handler_owner_and_settles_remaining_only(monkeypatch):
    entered, release = Event(), Event()
    handlers = []
    queue = FakeQueue([job(suffix='native-first'), job(suffix='native-rest')])
    original_interrupt = KeyboardInterrupt('post native start interrupt')
    original_start = runtime_module.Thread.start
    def handler(j, lease, *, cancelled):
        handlers.append(j.job_id)
        entered.set()
        assert release.wait(2)
        return success(j, lease, cancelled=cancelled)
    def interrupted_start(thread):
        result = original_start(thread)
        if thread.name.startswith('rick-worker-'):
            assert entered.wait(1)
            raise original_interrupt
        return result
    worker = make_runtime(queue, ManualClock(), handler, max_concurrency=2, sleep_fn=lambda _: None)
    monkeypatch.setattr(runtime_module.Thread, 'start', interrupted_start)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            worker.run_once(wait=False)
        assert caught.value is original_interrupt
        assert worker.active_count == worker.metrics().started == len(handlers) == 1
        assert len(queue.failures) == 1 and queue.failures[0][0].endswith('native-rest')
        assert queue.failures[0][1].retryable
        assert queue.cancel_lease_calls == [] and queue.acknowledged == []
        report = worker.shutdown(timeout=0)
        assert not report.drained and report.active == 1 and report.pending_claims == 0
        finish(worker, release)
        assert len(queue.cancel_lease_calls) == 1 and worker.shutdown(timeout=0).drained
    finally:
        finish(worker, release)
        worker.shutdown(timeout=0)


def test_interrupted_batch_cleanup_deduplicates_and_never_mutates_foreign_claim(monkeypatch):
    from dataclasses import replace
    from rick_jobs import JobScope
    foreign_scope = JobScope('foreign-tenant', 'foreign-workspace', 'foreign-collection')
    class Queue(FakeQueue):
        def claim(self, **kwargs):
            items = super().claim(**kwargs)
            first, second = items
            j, lease = second
            foreign = replace(j, tenant_id=foreign_scope.tenant_id,
                workspace_id=foreign_scope.workspace_id, collection_id=foreign_scope.collection_id)
            return (first, first, (foreign, replace(lease, scope=foreign_scope)))
    queue = Queue([job(suffix='owned'), job(suffix='foreign')])
    worker = make_runtime(queue, ManualClock(), success, max_concurrency=3, sleep_fn=lambda _: None)
    original_interrupt = KeyboardInterrupt('scoped launch interrupt')
    original_start = runtime_module.Thread.start
    def interrupted_start(thread):
        if thread.name.startswith('rick-worker-'):
            raise original_interrupt
        return original_start(thread)
    monkeypatch.setattr(runtime_module.Thread, 'start', interrupted_start)
    with pytest.raises(KeyboardInterrupt) as caught:
        worker.run_once(wait=False)
    assert caught.value is original_interrupt
    assert len(queue.failures) == 1 and queue.failures[0][0].endswith('owned')
    assert queue.failures[0][1].retryable
    assert queue.cancel_lease_calls == queue.acknowledged == []
    assert worker.shutdown(timeout=0).drained


@pytest.mark.parametrize('failure', [RuntimeError, KeyboardInterrupt])
def test_lifecycle_reservation_releases_on_failed_closer_and_reentrant_calls_return_busy(failure):
    class Worker:
        def shutdown(self, **kwargs):
            return True
    calls, reentrant = [], []
    composition = None
    class Closer:
        def close(self):
            calls.append('close')
            reentrant.append(composition.shutdown(timeout=1))
            reentrant.append(composition.dispose(timeout=1))
            if len(calls) == 1:
                raise failure('synthetic closer interruption')
    composition = DeploymentRuntime(SimpleNamespace(worker=Worker(), object_store=Closer()))
    if failure is RuntimeError:
        assert composition.shutdown(timeout=1) is False
    else:
        with pytest.raises(KeyboardInterrupt):
            composition.shutdown(timeout=1)
    assert not composition._shutdown_in_progress and reentrant == [False, False]
    assert composition.shutdown(timeout=1) is True
    assert composition.shutdown(timeout=1) is True
    assert len(calls) == 2 and reentrant == [False, False, False, False]


def test_dispose_is_busy_during_concurrent_shutdown_without_entering_closer():
    entered, release = Event(), Event()
    class Worker:
        def shutdown(self, **kwargs):
            return True
    class Closer:
        calls = 0
        def close(self):
            self.calls += 1
            entered.set()
            assert release.wait(2)
    closer = Closer()
    composition = DeploymentRuntime(SimpleNamespace(worker=Worker(), object_store=closer))
    results = []
    owner = Thread(target=lambda: results.append(composition.shutdown(timeout=2)))
    try:
        owner.start()
        assert entered.wait(1)
        assert composition.dispose(timeout=1) is False and closer.calls == 1
        release.set()
        join_driver(owner)
        assert results == [True]
        assert composition.dispose(timeout=1) is True and closer.calls == 1
    finally:
        release.set()
        join_driver(owner)


def test_shutdown_during_launch_interrupt_cancels_remaining_valid_owned_batch_once(monkeypatch):
    entered, release = Event(), Event()
    queue = FakeQueue([job(suffix='stop-first'), job(suffix='stop-rest')])
    original_interrupt = KeyboardInterrupt('stopped admission interrupt')
    original_start = runtime_module.Thread.start
    def interrupted_start(thread):
        if thread.name.startswith('rick-worker-'):
            entered.set()
            assert release.wait(2)
            raise original_interrupt
        return original_start(thread)
    handlers, interrupts = [], []
    def handler(j, lease, *, cancelled):
        handlers.append(j.job_id)
        return success(j, lease, cancelled=cancelled)
    worker = make_runtime(queue, ManualClock(), handler, max_concurrency=2, sleep_fn=lambda _: None)
    def drive():
        try:
            worker.run_once(wait=False)
        except BaseException as error:
            interrupts.append(error)
    driver = Thread(target=drive, name='stop-during-launch-driver')
    monkeypatch.setattr(runtime_module.Thread, 'start', interrupted_start)
    try:
        driver.start()
        assert entered.wait(1)
        report = worker.shutdown(timeout=0)
        assert not report.drained and report.pending_claims == 1 and report.active == 1
        assert len(queue.cancel_lease_calls) == 1
        release.set()
        join_driver(driver)
        assert interrupts == [original_interrupt] and handlers == []
        assert len(queue.cancel_lease_calls) == 2 and len(set(queue.cancel_lease_calls)) == 2
        assert queue.acknowledged == queue.failures == []
        assert worker.shutdown(timeout=0).drained and worker.wait_for_idle(timeout=0)
    finally:
        release.set()
        join_driver(driver)
        worker.shutdown(timeout=0)


def test_interrupted_batch_preserves_completed_owner_after_concurrent_monitor_reaps_it(monkeypatch):
    attempts = []
    class Queue(FakeQueue):
        def fail(self, lease, failure, **kwargs):
            attempts.append(str(lease.job_id))
            return super().fail(lease, failure, **kwargs)
    queue = Queue([job(suffix='reaped-first'), job(suffix='reaped-rest')])
    worker = make_runtime(queue, ManualClock(), success, max_concurrency=2, sleep_fn=lambda _: None)
    original_interrupt = KeyboardInterrupt('reaped launch interrupt')
    original_start = runtime_module.Thread.start
    def interrupted_start(thread):
        if thread.name.startswith('rick-worker-'):
            raise original_interrupt
        return original_start(thread)
    recover = worker._recover_interrupted_batch
    def monitor_before_recover(*args, **kwargs):
        worker._monitor_active()
        assert worker.active_count == 0 and len(queue.failures) == 1
        return recover(*args, **kwargs)
    monkeypatch.setattr(runtime_module.Thread, 'start', interrupted_start)
    monkeypatch.setattr(worker, '_recover_interrupted_batch', monitor_before_recover)
    with pytest.raises(KeyboardInterrupt) as caught:
        worker.run_once(wait=False)
    assert caught.value is original_interrupt
    assert len(attempts) == len(set(attempts)) == len(queue.failures) == worker.metrics().failed == 2
    assert worker.shutdown(timeout=0).drained and not worker._pending_recovery


class Spy:
    def __init__(self):
        self.calls = 0
    def close(self):
        self.calls += 1


@pytest.mark.parametrize('mode', ['error', 'unknown', 'no_port', 'lease_lost', 'success'])
def test_late_claim_requires_actual_cancel_settlement_or_proven_handoff(mode):
    claim_entered, claim_release, cancel_entered, cancel_release = (Event() for _ in range(4))
    attempts, errors, batches, handlers = [], [], [], []
    class Queue(FakeQueue):
        def claim(self, **kwargs):
            claim_entered.set()
            assert claim_release.wait(2)
            return super().claim(**kwargs)
        def cancel_lease(self, lease, **kwargs):
            attempts.append(str(lease.job_id))
            cancel_entered.set()
            assert cancel_release.wait(2)
            if mode == 'error':
                raise RuntimeError('synthetic cancel unavailable')
            if mode == 'unknown':
                return object()
            if mode == 'lease_lost':
                raise LeaseLost('synthetic fenced lease loss')
            return super().cancel_lease(lease, **kwargs)
    queue = Queue([job(suffix='candidate3-' + mode)])
    if mode == 'no_port':
        queue.cancel_lease = None  # FakeQueue has no durable-expiry contract/owner.
    def handler(j, lease, *, cancelled):
        handlers.append(j.job_id)
        return success(j, lease, cancelled=cancelled)
    clock = ManualClock()
    worker = make_runtime(queue, clock, handler, sleep_fn=clock.advance)
    store, provider = Spy(), Spy()
    composition = DeploymentRuntime(SimpleNamespace(worker=worker, object_store=store, provider=provider))
    def drive():
        try:
            batches.append(worker.run_once(wait=False))
        except BaseException as error:
            errors.append(type(error).__name__)
    driver = Thread(target=drive)
    try:
        driver.start()
        assert claim_entered.wait(1)
        assert composition.shutdown(timeout=0) is False
        claim_release.set()
        if mode != 'no_port':
            assert cancel_entered.wait(1)
            assert worker.shutdown(timeout=0).drained is False
            assert store.calls == provider.calls == 0
        cancel_release.set()
        driver.join(2)
        assert not driver.is_alive() and errors == [] and len(batches) == 1
        report = worker.shutdown(timeout=0)
        closed = composition.shutdown(timeout=1)
        live_rows = sum(j.state is JobState.RUNNING for j in queue._jobs.values())
        print('CANDIDATE3 CANCEL', mode, 'report=', report.as_dict(),
              'running_rows=', live_rows, 'stores_closed=', store.calls,
              'close_result=', closed, 'cancelled_metric=', worker.metrics().cancelled,
              'queue_errors=', worker.metrics().queue_errors)
        assert handlers == [] and queue.acknowledged == []
        if mode in {'error', 'unknown', 'no_port'}:
            assert live_rows == 1
            assert report.drained is False and report.pending_claims > 0
            assert worker.wait_for_idle(timeout=0) is False
            assert closed is False and store.calls == provider.calls == 0
            assert worker.metrics().cancelled == 0
        else:
            assert report.drained and closed is True and store.calls == provider.calls == 1
            assert worker.metrics().lease_lost == int(mode == 'lease_lost')
            assert worker.metrics().cancelled == int(mode == 'success')
    finally:
        claim_release.set()
        cancel_release.set()
        if driver.ident is not None:
            driver.join(2)
            assert not driver.is_alive()
        worker.shutdown(timeout=0)


def load_exact_optional_observability_fallback(monkeypatch):
    original_import = builtins.__import__
    def absent_optional(name, *args, **kwargs):
        if name == 'rick_observability':
            raise ImportError('controlled optional package absence')
        return original_import(name, *args, **kwargs)
    spec = importlib.util.spec_from_file_location('prod12_runtime_optional_fallback', runtime_module.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, '__import__', absent_optional)
        spec.loader.exec_module(module)
    return module


def test_exact_minimal_fallback_sink_wait_does_not_hold_execution_state_lock(monkeypatch):
    fallback = load_exact_optional_observability_fallback(monkeypatch)
    handler_entered, handler_release, sink_entered, sink_release = (Event() for _ in range(4))
    errors, lock_observations = [], []
    queue = FakeQueue([job(suffix='fallback-lock')])
    clock = ManualClock()
    def handler(j, lease, *, cancelled):
        handler_entered.set()
        assert handler_release.wait(2)
        return success(j, lease, cancelled=cancelled)
    def sink(event):
        if event['event'] == 'worker.job.succeeded':
            sink_entered.set()
            assert sink_release.wait(2)
    worker = fallback.RealWorkerRuntime(queue, worker_id='worker-a', scope=SCOPE,
        handlers={'ingest': handler}, max_concurrency=1, clock=clock, sleep_fn=clock.advance,
        event_sink=sink)
    store = Spy()
    composition = DeploymentRuntime(SimpleNamespace(worker=worker, object_store=store))
    def monitor():
        try:
            worker._monitor_active()
        except BaseException as error:
            errors.append(type(error).__name__)
    monitor_thread = Thread(target=monitor)
    try:
        worker.run_once(wait=False)
        assert handler_entered.wait(1)
        execution = next(iter(worker._active.values()))
        handler_release.set()
        execution.thread.join(1)
        assert not execution.thread.is_alive() and execution.handler_done.is_set()
        monitor_thread.start()
        assert sink_entered.wait(1)
        def inspect_state():
            execution_access = execution.lock.acquire(blocking=False)
            runtime_access = worker._lock.acquire(blocking=False)
            lock_observations.append((execution_access, runtime_access))
            if execution_access:
                assert execution.logical_done.is_set() and execution.outcome == 'succeeded'
                execution.lock.release()
            if runtime_access:
                worker._lock.release()
        probe = Thread(target=inspect_state)
        probe.start()
        probe.join(1)
        assert not probe.is_alive()
        print('CANDIDATE3 FALLBACK LOCK', 'cross_thread_execution_runtime_lock_access=', lock_observations)
        assert lock_observations == [(True, True)]
        assert worker.wait_for_idle(timeout=0) is False
        assert composition.shutdown(timeout=0) is False and store.calls == 0
        assert len(queue.acknowledged) == 1
    finally:
        sink_release.set()
        if monitor_thread.ident is not None:
            monitor_thread.join(2)
            assert not monitor_thread.is_alive()
        handler_release.set()
        for execution in tuple(worker._active.values()):
            if execution.thread is not None and execution.thread.ident is not None:
                execution.thread.join(2)
                assert not execution.thread.is_alive()
        worker.shutdown(timeout=0)
        assert errors == []
        assert composition.shutdown(timeout=1) is True and store.calls == 1
        assert composition.shutdown(timeout=1) is True and store.calls == 1
        assert len(queue.acknowledged) == 1


class Round4Store:
    def __init__(self): self.calls = 0
    def close(self): self.calls += 1


@pytest.mark.parametrize('response', ['error', 'running', 'lease_lost', 'success'])
@pytest.mark.parametrize('stop', [True, False])
def test_expired_owned_tuple_is_not_discarded_or_executed(response, stop):
    entered, release = Event(), Event()
    handlers, results, errors, calls = [], [], [], []
    class Queue(FakeQueue):
        def claim(self, **kwargs):
            batch = super().claim(**kwargs)  # actual RUNNING owner acquired at100
            entered.set()
            assert release.wait(2)
            return batch
        def settle(self, lease, kwargs):
            calls.append((str(lease.job_id), kwargs['expected_version'], lease.token))
            assert kwargs['expected_version'] == self._jobs[str(lease.job_id)].version
            if response == 'error': raise RuntimeError('synthetic expired settlement unavailable')
            if response == 'running': return self._jobs[str(lease.job_id)]
            if response == 'lease_lost': raise LeaseLost('authoritative fixture lease loss')
        def cancel_lease(self, lease, **kwargs):
            result = self.settle(lease, kwargs)
            return result if response == 'running' else super().cancel_lease(lease, **kwargs)
        def fail(self, lease, failure, **kwargs):
            assert failure.retryable
            result = self.settle(lease, kwargs)
            return result if response == 'running' else super().fail(lease, failure, **kwargs)
    queue = Queue([job(suffix='expired-' + response + '-' + str(stop))])
    clock = ManualClock()
    def handler(j, lease, *, cancelled):
        handlers.append(j.job_id)
        return success(j, lease, cancelled=cancelled)
    worker = make_runtime(queue, clock, handler, sleep_fn=clock.advance)
    store = Round4Store()
    composition = DeploymentRuntime(SimpleNamespace(worker=worker, object_store=store))
    def drive():
        try: results.append(worker.run_once(wait=False))
        except BaseException as error: errors.append(type(error).__name__)
    driver = Thread(target=drive)
    try:
        driver.start(); assert entered.wait(1)
        if stop: assert composition.shutdown(timeout=0) is False
        clock.advance(31)  # lease expires130, tuple returned131
        release.set(); driver.join(2)
        assert not driver.is_alive() and errors == [] and len(results) == 1
        assert handlers == [] and queue.acknowledged == []
        batch = results[0]
        report = worker.shutdown(timeout=0)
        closed = composition.shutdown(timeout=1)
        print('ROUND4 EXPIRED', response, stop, 'batch=', batch.as_dict(), 'report=', report.as_dict(),
              'running=', sum(j.state is JobState.RUNNING for j in queue._jobs.values()),
              'settle_calls=', len(calls), 'close=', closed, 'stores=', store.calls)
        assert calls, 'owned tuple dropped solely on local expiry'
        assert batch.started == batch.poisoned == 0
        if response in {'error', 'running'}:
            assert not report.drained and report.pending_claims == 1
            assert worker.wait_for_idle(timeout=0) is False
            assert closed is False and store.calls == 0
            assert all(j.state is JobState.RUNNING for j in queue._jobs.values())
            assert worker.metrics().lease_lost == worker.metrics().cancelled == 0
        else:
            assert report.drained
            assert batch.lease_lost == int(response == 'lease_lost')
            if response == 'success':
                assert all(j.state is (JobState.CANCELLED if stop else JobState.FAILED) for j in queue._jobs.values())
    finally:
        release.set()
        if driver.ident is not None: driver.join(2); assert not driver.is_alive()
        worker.shutdown(timeout=0)


@pytest.mark.parametrize('response', ['error', 'running'])
def test_live_unsettled_cancel_blocks_spare_capacity_until_confirmation(response):
    entered, release = Event(), Event()
    handlers = []
    class Queue(FakeQueue):
        recover = False
        claim_count = 0
        def claim(self, **kwargs):
            self.claim_count += 1
            kwargs['limit'] = min(kwargs['limit'], 1)  # compliant short batch
            return super().claim(**kwargs)
        def cancel_lease(self, lease, **kwargs):
            if not self.recover:
                if response == 'error': raise RuntimeError('synthetic cancel failure')
                return self._jobs[str(lease.job_id)]
            return super().cancel_lease(lease, **kwargs)
    queue = Queue([job(suffix='live-first'), job(suffix='live-second')])
    clock = ManualClock()
    def handler(j, lease, *, cancelled):
        handlers.append(str(j.job_id))
        if str(j.job_id).endswith('live-first'):
            entered.set(); assert release.wait(2)
        return success(j, lease, cancelled=cancelled)
    worker = make_runtime(queue, clock, handler, max_concurrency=2, sleep_fn=clock.advance)
    try:
        first = worker.run_once(wait=False); assert entered.wait(1)
        execution = worker._active['job-ingest-live-first']
        assert worker.cancel(execution.job.job_id)
        worker._monitor_active()
        assert execution.admission_interrupted and execution.thread.is_alive()
        assert worker._pending_recovery == {} and not execution.logical_done.is_set()
        second = worker.run_once(wait=False)
        print('ROUND4 LIVE PENDING', response, 'second=', second.as_dict(),
              'claims=', queue.claim_count, 'handlers=', handlers, 'active=', worker.active_count)
        assert second.backpressured and second.claimed == second.started == 0
        assert queue.claim_count == 1 and handlers == ['job-ingest-live-first']
        assert queue._jobs['job-ingest-live-first'].state is JobState.RUNNING
        queue.recover = True; worker._monitor_active()
        assert execution.logical_done.is_set() and queue._jobs['job-ingest-live-first'].state is JobState.CANCELLED
        third = worker.run_once(wait=False)
        assert third.claimed == third.started == 1 and queue.claim_count == 2
    finally:
        release.set()
        for execution in tuple(worker._active.values()):
            if execution.thread is not None and execution.thread.ident is not None:
                execution.thread.join(2); assert not execution.thread.is_alive()
        worker.shutdown(timeout=0)


def round4_execution(queue, clock, worker):
    j, lease = queue.claim(worker_id=worker.worker_id, scope=SCOPE, limit=1, now=clock(),
        expected_versions={j.job_id: j.version for j in queue._jobs.values()})[0]
    execution = runtime_module._Execution(job=j, lease=lease, handler=None,
        token=CancellationToken(), started_at=clock(), deadline=clock()+1, next_heartbeat_at=clock()+10)
    worker._active[str(j.job_id)] = execution
    return execution


@pytest.mark.parametrize('operation', ['is_alive', 'join', 'recover_is_alive'])
def test_thread_lifecycle_observations_do_not_hold_state_locks(operation):
    entered, release = Event(), Event()
    observations, errors = [], []
    queue, clock = FakeQueue([job(suffix='thread-lock')]), ManualClock()
    worker = make_runtime(queue, clock, success)
    execution = round4_execution(queue, clock, worker)
    class ObservedThread:
        ident = None if operation == 'recover_is_alive' else 123
        def is_alive(self):
            if operation != 'join':
                entered.set(); assert release.wait(2)
            return False
        def join(self, timeout):
            assert timeout == 0
            entered.set(); assert release.wait(2)
    execution.thread = ObservedThread()
    if operation != 'recover_is_alive':
        queue.cancel_lease(execution.lease, now=clock(), expected_version=execution.job.version)
        execution.handler_done.set(); execution.logical_done.set(); execution.outcome = 'cancelled'
    def operate():
        try:
            if operation == 'recover_is_alive':
                worker._recover_interrupted_batch(((execution.job, execution.lease),), clock(),
                    KeyboardInterrupt('original'), set(), {str(execution.job.job_id): execution})
            else: worker._reap()
        except BaseException as error: errors.append(type(error).__name__)
    driver = Thread(target=operate)
    try:
        driver.start(); assert entered.wait(1)
        def probe():
            global_access = worker._lock.acquire(blocking=False)
            execution_access = execution.lock.acquire(blocking=False)
            observations.append((global_access, execution_access))
            if execution_access: execution.lock.release()
            if global_access: worker._lock.release()
        inspector = Thread(target=probe); inspector.start(); inspector.join(1)
        assert not inspector.is_alive()
        print('ROUND4 THREAD LOCK', operation, observations)
        assert observations == [(True, True)]
    finally:
        release.set(); driver.join(2); assert not driver.is_alive()
        worker._reap()
        assert errors == []


# Additional canonical snapshot/recheck and in-flight admission evidence.

@pytest.mark.parametrize('operation', ['is_alive', 'join', 'recover_is_alive'])
def test_thread_observation_rechecks_replaced_thread_or_completed_owner(operation):
    entered, release = Event(), Event()
    queue, clock = FakeQueue([job(suffix='identity-thread')]), ManualClock()
    worker = make_runtime(queue, clock, success)
    execution = round4_execution(queue, clock, worker)
    class OldThread:
        ident = None if operation == 'recover_is_alive' else 123
        def is_alive(self):
            if operation != 'join': entered.set(); assert release.wait(2)
            return False
        def join(self, timeout):
            assert timeout == 0
            if operation == 'join': entered.set(); assert release.wait(2)
    class NewThread:
        ident = 456
        alive = True
        def is_alive(self): return self.alive
        def join(self, timeout): assert timeout == 0
    execution.thread = OldThread()
    if operation != 'recover_is_alive':
        queue.cancel_lease(execution.lease, now=clock(), expected_version=execution.job.version)
        execution.outcome = 'cancelled'; execution.logical_done.set(); execution.handler_done.set()
    errors = []
    def observe():
        try:
            if operation == 'recover_is_alive':
                worker._recover_interrupted_batch(((execution.job, execution.lease),), clock(),
                    KeyboardInterrupt('primary'), set(), {str(execution.job.job_id): execution})
            else: worker._reap()
        except BaseException as error: errors.append(type(error).__name__)
    driver = Thread(target=observe)
    replacement = NewThread()
    try:
        driver.start(); assert entered.wait(1)
        if operation == 'recover_is_alive':
            # Complete authoritatively while its external observation is held.
            queue.cancel_lease(execution.lease, now=clock(), expected_version=execution.job.version)
            with execution.lock:
                execution.outcome = 'cancelled'; execution.logical_done.set(); execution.handler_done.set()
        else:
            with execution.lock: execution.thread = replacement
        release.set(); driver.join(2); assert not driver.is_alive() and errors == []
        assert queue.failures == [] and len(queue.cancel_lease_calls) == 1
        if operation != 'recover_is_alive':
            assert worker._active[str(execution.job.job_id)] is execution
            assert worker.wait_for_idle(timeout=0) is False
        assert worker._pending_recovery == {}
    finally:
        release.set(); driver.join(2)
        replacement.alive = False
        worker._reap()
        assert not driver.is_alive() and errors == []


def test_unsettled_owner_published_during_claim_prevents_late_second_handler():
    first_entered, first_release, claim_entered, claim_release = (Event() for _ in range(4))
    handlers, results, errors = [], [], []
    class Queue(FakeQueue):
        count = 0
        def claim(self, **kwargs):
            self.count += 1
            kwargs['limit'] = 1
            batch = super().claim(**kwargs)
            if self.count == 2:
                claim_entered.set(); assert claim_release.wait(2)
            return batch
        def cancel_lease(self, lease, **kwargs):
            raise RuntimeError('synthetic unresolved live owner')
    queue = Queue([job(suffix='race-first'), job(suffix='race-second')])
    clock = ManualClock()
    def handler(j, lease, *, cancelled):
        handlers.append(str(j.job_id)); first_entered.set(); assert first_release.wait(2)
        return success(j, lease, cancelled=cancelled)
    worker = make_runtime(queue, clock, handler, max_concurrency=2, sleep_fn=clock.advance)
    def drive():
        try: results.append(worker.run_once(wait=False))
        except BaseException as error: errors.append(type(error).__name__)
    driver = Thread(target=drive)
    try:
        worker.run_once(wait=False); assert first_entered.wait(1)
        driver.start(); assert claim_entered.wait(1)
        assert worker.cancel('job-ingest-race-first')
        worker._monitor_active()
        assert worker._active['job-ingest-race-first'].admission_interrupted
        claim_release.set(); driver.join(2)
        assert not driver.is_alive() and errors == [] and len(results) == 1
        assert results[0].claimed == 1 and results[0].started == 0 and results[0].failed == 1
        assert handlers == ['job-ingest-race-first']
        assert len(queue.failures) == 1 and queue.failures[0][1].retryable
        assert queue._jobs['job-ingest-race-second'].state is JobState.FAILED
        assert queue._jobs['job-ingest-race-first'].state is JobState.RUNNING
        assert queue.acknowledged == []
    finally:
        claim_release.set(); first_release.set()
        if driver.ident is not None: driver.join(2); assert not driver.is_alive()
        for execution in tuple(worker._active.values()):
            if execution.thread is not None and execution.thread.ident is not None:
                execution.thread.join(2); assert not execution.thread.is_alive()
        worker.shutdown(timeout=0)


# Actual unchanged PostgresJobQueue lease-loss / recovery policy over SQL-port fake.

@pytest.mark.parametrize('max_attempts', [1, 2])
def test_expired_returned_native_claim_uses_authoritative_fence_and_existing_expiry_policy(max_attempts):
    from worker.tests.test_postgres_jobs import make_queue, make_job
    native, connection = make_queue()
    queued = native.enqueue(make_job(job_id='job-expired-native', key='idem-expired-native',
        max_attempts=max_attempts), expected_version=0)
    connection.database_now = 104.0
    clock = ManualClock(104.0)
    entered, release = Event(), Event()
    handler_calls, batches, errors = [], [], []
    class HeldPort:
        def __getattr__(self, name): return getattr(native, name)
        def claim(self, **kwargs):
            batch = native.claim(**kwargs)
            assert len(batch) == 1 and batch[0][1].expires_at == 114.0
            entered.set(); assert release.wait(2)
            return batch
    def handler(j, lease, *, cancelled):
        handler_calls.append(j.job_id)
        return success(j, lease, cancelled=cancelled)
    worker = make_runtime(HeldPort(), clock, handler, sleep_fn=clock.advance)
    def drive():
        try: batches.append(worker.run_once(wait=False))
        except BaseException as error: errors.append(type(error).__name__)
    driver = Thread(target=drive)
    try:
        driver.start(); assert entered.wait(1)
        assert not worker.shutdown(timeout=0).drained
        clock.advance(11); connection.database_now = 115.0
        release.set(); driver.join(2)
        assert not driver.is_alive() and errors == [] and len(batches) == 1
        assert handler_calls == [] and batches[0].started == batches[0].poisoned == 0
        assert batches[0].lease_lost == 1 and worker.metrics().queue_errors == 0
        # Drain follows the actual SQL lease guard error, not clock-only discard.
        assert worker.shutdown(timeout=0).drained
        row = connection.jobs[str(queued.job_id)]
        assert row['contract_state'] == 'RUNNING' and row['lease_until'] == 114.0
        assert any('lease_until >' in sql and 'FOR UPDATE' in sql for sql, _ in connection.trace)
        assert native.claim(worker_id='worker-b', scope=queued.scope, expected_versions={},
            now=115.0, limit=1) == ()
        row = connection.jobs[str(queued.job_id)]
        assert row['lease_owner'] is None and row['attempts'] == 1
        assert row['contract_state'] == ('QUEUED' if max_attempts == 2 else 'DEAD_LETTER')
        assert connection.attempts[(str(queued.job_id), 1)]['state'] == 'FAILED'
        connection.database_now = 116.0
        reclaimed = native.claim(worker_id='worker-b', scope=queued.scope, expected_versions={},
            now=116.0, limit=1)
        assert len(reclaimed) == int(max_attempts == 2)
        assert all(j.attempt_count == 2 and lease.worker_id == 'worker-b' for j, lease in reclaimed)
    finally:
        release.set()
        if driver.ident is not None: driver.join(2); assert not driver.is_alive()
        worker.shutdown(timeout=0)


@pytest.mark.parametrize('seam', ['native_start', 'trace_entry', 'fault_hook'])
@pytest.mark.parametrize('response', ['success', 'error', 'running', 'lease_lost'])
@pytest.mark.parametrize('expired', [True, False])
def test_actual_handler_entry_rechecks_lease_after_native_or_trace_yield(monkeypatch, seam, response, expired):
    entered, release = Event(), Event()
    invocations, batches, errors, settlements = [], [], [], []
    class Queue(FakeQueue):
        def check(self, lease, expected_version, kind):
            current = self._jobs[str(lease.job_id)]
            assert expected_version == current.version
            assert lease.token == self._leases[str(lease.job_id)].token
            assert lease.scope == current.scope and lease.job_id == current.job_id
            settlements.append(kind)
            if response == 'error': raise RuntimeError('synthetic entry settlement unavailable')
            if response == 'running': return current
            if response == 'lease_lost': raise LeaseLost('authoritative fixture ownership loss')
        def fail(self, lease, failure, **kwargs):
            assert failure.retryable
            current = self.check(lease, kwargs['expected_version'], 'fail')
            return current if response == 'running' else super().fail(lease, failure, **kwargs)
        def cancel_lease(self, lease, **kwargs):
            current = self.check(lease, kwargs['expected_version'], 'cancel')
            return current if response == 'running' else super().cancel_lease(lease, **kwargs)
    queue = Queue([job(suffix='entry-' + seam + '-' + response + '-' + str(expired))])
    clock = ManualClock()
    def handler(j, lease, *, cancelled):
        invocations.append(clock())
        return success(j, lease, cancelled=cancelled)
    def pause():
        entered.set(); assert release.wait(2)
    original_start = runtime_module.Thread.start
    if seam == 'native_start':
        def delayed_start(thread):
            worker_thread = thread.name.startswith('rick-worker-')
            if worker_thread: pause()
            result = original_start(thread)
            if worker_thread:
                # Freeze a legitimate scheduling order: native invocation ends
                # before the caller can run its post-launch heartbeat monitor.
                thread.join(2); assert not thread.is_alive()
            return result
        monkeypatch.setattr(runtime_module.Thread, 'start', delayed_start)
    elif seam == 'trace_entry':
        original_span = runtime_module.stage_span
        @contextmanager
        def delayed_span(name, **kwargs):
            with original_span(name, **kwargs) as span:
                if name == 'worker.ingestion': pause()
                yield span
        monkeypatch.setattr(runtime_module, 'stage_span', delayed_span)
    def fault(point, current_job, current_lease):
        if seam == 'fault_hook' and point == 'during_handler': pause()
    worker = make_runtime(queue, clock, handler, handler_timeout_seconds=300,
        sleep_fn=clock.advance, fault_injector=fault)
    def drive():
        try: batches.append(worker.run_once(wait=False))
        except BaseException as error: errors.append(type(error).__name__)
    driver = Thread(target=drive)
    class Store:
        calls = 0
        def close(self): self.calls += 1
    store = Store()
    composition = DeploymentRuntime(SimpleNamespace(worker=worker, object_store=store))
    try:
        driver.start(); assert entered.wait(1)
        execution = next(iter(worker._active.values()))
        if seam != 'native_start':
            driver.join(2); assert not driver.is_alive()
        clock.advance(31 if expired else 29)
        # Deliberately no shutdown, heartbeat or monitor before native/trace resume.
        release.set(); driver.join(2)
        assert not driver.is_alive() and errors == [] and len(batches) == 1
        execution.thread.join(2); assert not execution.thread.is_alive()
        print('ROUND5 ENTRY', seam, response, expired, 'handler_times=', invocations,
              'settlements=', settlements, 'state=', next(iter(queue._jobs.values())).state.value)
        if expired:
            assert invocations == [], 'actual callable ran after the fresh lease deadline'
            assert queue.acknowledged == [] and execution.admission_interrupted
            assert settlements == ['fail']  # open admission uses retryable failure
            assert worker.metrics().timed_out == 0  # handler deadline400, lease130
            if response in {'error', 'running'}:
                assert next(iter(queue._jobs.values())).state is JobState.RUNNING
                report = worker.shutdown(timeout=0)
                assert not report.drained and report.pending_claims == 1
                assert worker.wait_for_idle(timeout=0) is False
                assert composition.shutdown(timeout=0) is False and store.calls == 0
                assert worker.metrics().cancelled == worker.metrics().lease_lost == 0
            else:
                assert worker.wait_for_idle(timeout=0)
                assert worker.metrics().lease_lost == int(response == 'lease_lost')
                if response == 'success':
                    assert next(iter(queue._jobs.values())).state is JobState.FAILED
                    assert queue.failures[0][1].retryable and queue.cancel_lease_calls == []
        else:
            assert invocations == [129.0] and settlements == []
            worker._monitor_active()
            assert worker.metrics().succeeded == 1 and len(queue.acknowledged) == 1
    finally:
        release.set()
        if driver.ident is not None: driver.join(2); assert not driver.is_alive()
        for execution in tuple(worker._active.values()):
            if execution.thread is not None and execution.thread.ident is not None:
                execution.thread.join(2); assert not execution.thread.is_alive()
        worker.shutdown(timeout=0)


# Exact exclusive expiry, requested-stop policy, and verified renewal controls.

@pytest.mark.parametrize('case', ['exact_expiry', 'stop_success', 'stop_error', 'stop_running', 'stop_lease_lost', 'renewed'])
def test_handler_entry_gate_exact_boundary_stop_policy_and_known_renewal(monkeypatch, case):
    entered, release = Event(), Event()
    invocations, batches, errors, settlements, received_leases = [], [], [], [], []
    class Queue(FakeQueue):
        def cancel_lease(self, lease, **kwargs):
            assert kwargs['expected_version'] == self._jobs[str(lease.job_id)].version
            assert lease.token == self._leases[str(lease.job_id)].token
            assert lease.scope == self._jobs[str(lease.job_id)].scope
            settlements.append('cancel')
            if case == 'stop_error': raise RuntimeError('synthetic stop settlement error')
            if case == 'stop_running': return self._jobs[str(lease.job_id)]
            if case == 'stop_lease_lost': raise LeaseLost('authoritative fixture stop loss')
            return super().cancel_lease(lease, **kwargs)
        def fail(self, lease, failure, **kwargs):
            assert failure.retryable and kwargs['expected_version'] == self._jobs[str(lease.job_id)].version
            settlements.append('fail')
            return super().fail(lease, failure, **kwargs)
    queue, clock = Queue([job(suffix='entry-policy-' + case)]), ManualClock()
    def handler(j, lease, *, cancelled):
        invocations.append(clock())
        received_leases.append(lease)
        return success(j, lease, cancelled=cancelled)
    original_span = runtime_module.stage_span
    @contextmanager
    def delayed_span(name, **kwargs):
        with original_span(name, **kwargs) as span:
            if name == 'worker.ingestion': entered.set(); assert release.wait(2)
            yield span
    monkeypatch.setattr(runtime_module, 'stage_span', delayed_span)
    worker = make_runtime(queue, clock, handler, handler_timeout_seconds=300, sleep_fn=clock.advance)
    def drive():
        try: batches.append(worker.run_once(wait=False))
        except BaseException as error: errors.append(type(error).__name__)
    driver = Thread(target=drive)
    try:
        driver.start(); assert entered.wait(1)
        execution = next(iter(worker._active.values()))
        driver.join(2); assert not driver.is_alive()
        if case == 'renewed':
            clock.advance(25)
            worker._heartbeat(execution, clock())
            assert execution.lease.expires_at == 155.0 and worker.metrics().heartbeats == 1
            clock.advance(6)
        else:
            clock.advance(30 if case == 'exact_expiry' else 31)
            if case.startswith('stop_'): worker.request_stop()
        release.set(); driver.join(2); execution.thread.join(2)
        assert not driver.is_alive() and not execution.thread.is_alive() and errors == []
        assert worker.metrics().timed_out == 0 and len(batches) == 1
        if case == 'renewed':
            assert invocations == [131.0] and settlements == []
            received = received_leases[0]
            print('ROUND6 RENEWED handler_expiry=', received.expires_at,
                  'gate_expiry=', execution.lease.expires_at, 'entry_time=', invocations[0])
            assert received.expires_at == 155.0 and received.active_at(131.0)
            assert received is execution.lease
            assert received.token == queue._leases[str(execution.job.job_id)].token
            assert received.job_id == execution.job.job_id and received.scope == execution.job.scope
            assert received.worker_id == execution.lease.worker_id
            worker._monitor_active()
            assert worker.metrics().succeeded == 1 and len(queue.acknowledged) == 1
        else:
            assert invocations == [] and queue.acknowledged == []
            assert settlements == ['fail' if case == 'exact_expiry' else 'cancel']
            if case in {'stop_error', 'stop_running'}:
                report = worker.shutdown(timeout=0)
                assert not report.drained and report.pending_claims == 1
                assert next(iter(queue._jobs.values())).state is JobState.RUNNING
                assert worker.metrics().cancelled == worker.metrics().lease_lost == 0
            else:
                assert worker.wait_for_idle(timeout=0)
                assert worker.metrics().lease_lost == int(case == 'stop_lease_lost')
                if case != 'stop_lease_lost':
                    assert next(iter(queue._jobs.values())).state is (
                        JobState.FAILED if case == 'exact_expiry' else JobState.CANCELLED)
                    assert worker.metrics().cancelled == int(case == 'stop_success')
    finally:
        release.set()
        if driver.ident is not None: driver.join(2); assert not driver.is_alive()
        for execution in tuple(worker._active.values()):
            if execution.thread is not None and execution.thread.ident is not None:
                execution.thread.join(2); assert not execution.thread.is_alive()
        worker.shutdown(timeout=0)


# Actual canonical expired ownership fence after native trace entry, no monitor.

@pytest.mark.parametrize('max_attempts', [1, 2])
def test_native_handler_entry_expiry_uses_real_queue_fence_not_clock_authority(monkeypatch, max_attempts):
    from worker.tests.test_postgres_jobs import make_queue, make_job
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(job_id='job-launch-native', key='idem-launch-native',
        max_attempts=max_attempts), expected_version=0)
    clock = ManualClock(104.0)
    entered, release = Event(), Event()
    calls, batches, errors = [], [], []
    original_span = runtime_module.stage_span
    @contextmanager
    def delayed_span(name, **kwargs):
        with original_span(name, **kwargs) as span:
            if name == 'worker.ingestion': entered.set(); assert release.wait(2)
            yield span
    monkeypatch.setattr(runtime_module, 'stage_span', delayed_span)
    def handler(j, lease, *, cancelled):
        calls.append(j.job_id)
        return success(j, lease, cancelled=cancelled)
    worker = make_runtime(queue, clock, handler, handler_timeout_seconds=300, sleep_fn=clock.advance)
    def drive():
        try: batches.append(worker.run_once(wait=False))
        except BaseException as error: errors.append(type(error).__name__)
    driver = Thread(target=drive)
    try:
        driver.start(); assert entered.wait(1)
        execution = worker._active[str(queued.job_id)]
        assert execution.lease.expires_at == 114.0
        driver.join(2); assert not driver.is_alive()
        clock.advance(11); connection.database_now = 115.0
        release.set(); driver.join(2); execution.thread.join(2)
        assert not driver.is_alive() and not execution.thread.is_alive() and errors == []
        assert calls == [] and len(batches) == 1
        assert worker.metrics().timed_out == worker.metrics().succeeded == 0
        assert worker.metrics().lease_lost == 1 and worker.metrics().queue_errors == 0
        assert execution.admission_interrupted and execution.logical_done.is_set()
        assert worker.wait_for_idle(timeout=0)
        assert connection.jobs[str(queued.job_id)]['contract_state'] == 'RUNNING'
        assert any('lease_until >' in sql and 'FOR UPDATE' in sql for sql, _ in connection.trace)
        assert queue.claim(worker_id='worker-b', scope=queued.scope, expected_versions={},
            now=115.0, limit=1) == ()
        row = connection.jobs[str(queued.job_id)]
        assert row['lease_owner'] is None and row['attempts'] == 1
        assert row['contract_state'] == ('QUEUED' if max_attempts == 2 else 'DEAD_LETTER')
        assert connection.attempts[(str(queued.job_id), 1)]['state'] == 'FAILED'
        connection.database_now = 116.0
        reclaimed = queue.claim(worker_id='worker-b', scope=queued.scope, expected_versions={},
            now=116.0, limit=1)
        assert len(reclaimed) == int(max_attempts == 2)
        assert all(j.attempt_count == 2 and lease.worker_id == 'worker-b' for j, lease in reclaimed)
    finally:
        release.set()
        if driver.ident is not None: driver.join(2); assert not driver.is_alive()
        for execution in tuple(worker._active.values()):
            if execution.thread is not None and execution.thread.ident is not None:
                execution.thread.join(2); assert not execution.thread.is_alive()
        worker.shutdown(timeout=0)
