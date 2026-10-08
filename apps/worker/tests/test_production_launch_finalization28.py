"""Pre-launch deadline/shutdown and launcher result share one finalization."""
from threading import Event, Thread
import pytest
import runtime as R
from test_runtime import FakeQueue, ManualClock, job, make_runtime, success


@pytest.mark.parametrize('action', ['timeout', 'shutdown'])
@pytest.mark.parametrize('launch_result', ['failure', 'success'])
def test_prelaunch_finalization_prevents_a_second_mutation_or_handler(monkeypatch, action, launch_result):
    entered, release = Event(), Event()
    mutations, calls, results, errors = [], [], [], []
    class CountingQueue(FakeQueue):
        def fail(self, lease, failure, **kwargs):
            mutations.append('fail')
            return super().fail(lease, failure, **kwargs)
        def cancel_lease(self, lease, **kwargs):
            mutations.append('cancel')
            return super().cancel_lease(lease, **kwargs)
        def acknowledge(self, lease, result, **kwargs):
            mutations.append('ack')
            return super().acknowledge(lease, result, **kwargs)
    queue = CountingQueue([job(suffix='prelaunch-finalization')])
    clock = ManualClock()
    def handler(j,l,*,cancelled):
        calls.append(str(j.job_id))
        return success(j,l,cancelled=cancelled)
    worker = make_runtime(queue, clock, handler, max_concurrency=1)
    original_start = R.Thread.start
    def controlled_start(thread):
        if thread.name.startswith('rick-worker-'):
            entered.set(); assert release.wait(2)
            if launch_result == 'failure': raise RuntimeError('synthetic-launch-private-marker')
        original_start(thread)
    def drive():
        try: results.append(worker.run_once(wait=False))
        except BaseException as error: errors.append(error)
    driver = Thread(target=drive, name='local-admission-driver')
    try:
        with monkeypatch.context() as patch:
            patch.setattr(R.Thread, 'start', controlled_start)
            driver.start(); assert entered.wait(1)
            if action == 'timeout':
                clock.advance(2); worker.wait_for_idle(timeout=.01)
            else: worker.shutdown(timeout=0)
            assert mutations == (['fail'] if action == 'timeout' else ['cancel'])
            release.set(); driver.join(1); assert not driver.is_alive()
        assert errors == [] and len(results) == 1
        for execution in tuple(worker._active.values()):
            if execution.thread.ident is not None: execution.thread.join(1)
        worker.wait_for_idle(timeout=.1)
        batch = results[0];metrics = worker.metrics()
        assert mutations == (['fail'] if action == 'timeout' else ['cancel'])
        assert calls == [] and metrics.queue_errors == batch.queue_errors == 0
        assert metrics.started == batch.started == int(launch_result == 'success')
        assert metrics.failed == batch.failed == int(action == 'timeout')
        assert metrics.cancelled == batch.cancelled == int(action == 'shutdown')
        assert metrics.timed_out == batch.timed_out == int(action == 'timeout')
        assert metrics.poisoned == batch.poisoned == int(launch_result == 'failure')
        assert worker.active_count == 0
    finally:
        release.set()
        if driver.ident is not None: driver.join(2)
        worker.shutdown(timeout=0)


def test_completion_record_keeps_finalization_owned_until_published(monkeypatch):
    completed, publish, duplicate_attempt = Event(), Event(), Event()
    class CountingQueue(FakeQueue):
        ack_attempts = 0
        def acknowledge(self, *args, **kwargs):
            self.ack_attempts += 1
            if self.ack_attempts > 1: duplicate_attempt.set()
            return super().acknowledge(*args, **kwargs)
    queue = CountingQueue([job(suffix='finalization-publication')])
    release_handler = Event()
    def handler(j,l,*,cancelled):
        assert release_handler.wait(2)
        return success(j,l,cancelled=cancelled)
    worker = make_runtime(queue, ManualClock(), handler)
    original_record = worker._record_outcome
    def delayed_record(execution, outcome, *, code=None):
        completed.set(); assert publish.wait(2)
        original_record(execution, outcome, code=code)
    monkeypatch.setattr(worker, '_record_outcome', delayed_record)
    failures = []
    def monitor():
        try: worker._monitor_active()
        except BaseException as error: failures.append(error)
    monitors = [Thread(target=monitor) for _ in range(2)]
    try:
        worker.run_once(wait=False);release_handler.set()
        for execution in tuple(worker._active.values()): assert execution.handler_done.wait(1)
        monitors[0].start(); assert completed.wait(1)
        monitors[1].start()
        duplicate = duplicate_attempt.wait(.05)
        publish.set()
        for thread in monitors: thread.join(1); assert not thread.is_alive()
        assert failures == [] and not duplicate
        assert queue.ack_attempts == worker.metrics().succeeded == 1
        assert worker.metrics().queue_errors == 0
        assert worker.wait_for_idle(timeout=1)
    finally:
        publish.set();release_handler.set()
        for thread in monitors:
            if thread.ident is not None: thread.join(2)
        worker.shutdown(timeout=0)
