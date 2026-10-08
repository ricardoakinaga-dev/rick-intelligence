"""Faulty claims and worker launch/context-exit preserve finite capacity."""
from contextlib import contextmanager
from threading import Event, current_thread
import pytest
import runtime as R
from test_runtime import FakeQueue, ManualClock, job, make_runtime, success


@pytest.mark.parametrize('mode', ['batch', 'active'])
def test_duplicate_claim_preserves_original_execution(mode):
    released = Event()
    class DuplicateQueue(FakeQueue):
        calls = 0
        cached = None
        def claim(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                found = super().claim(**dict(kwargs, limit=1))
                self.cached = found[0]
                return found * 2 if mode == 'batch' else found
            if self.calls == 2 and mode == 'active':
                return (self.cached,)
            return super().claim(**kwargs)
    queue = DuplicateQueue([job(suffix='first'), job(suffix='next')])
    calls = []
    def handler(j,l,*,cancelled):
        calls.append(str(j.job_id)); assert released.wait(2)
        return success(j,l,cancelled=cancelled)
    worker = make_runtime(queue, ManualClock(), handler, max_concurrency=2)
    try:
        first = worker.run_once(wait=False)
        original = worker._active[str(queue.cached[0].job_id)]
        if mode == 'batch':
            assert first.started == 1 and first.queue_errors == first.poisoned == 1
        else:
            assert first.started == 1 and first.queue_errors == 0
            second = worker.run_once(wait=False)
            assert second.started == 0 and second.queue_errors == second.poisoned == 1
        assert worker._active[str(queue.cached[0].job_id)] is original
        assert worker.active_count == worker.metrics().max_active == 1
        assert queue.failures == queue.acknowledged == []
        released.set(); assert worker.wait_for_idle(timeout=1)
        assert worker.run_once().succeeded == 1
        assert len(calls) == len(set(calls)) == worker.metrics().started == 2
        assert worker.metrics().succeeded == 2 and worker.metrics().queue_errors == 1
        assert len(queue.acknowledged) == 2
    finally:
        released.set(); worker.shutdown(timeout=0)


def test_failed_thread_launch_releases_reserved_slot(monkeypatch):
    queue = FakeQueue([job(suffix='launch-failed'), job(suffix='next')])
    worker = make_runtime(queue, ManualClock(), success, max_concurrency=1)
    def failed_start(_thread): raise RuntimeError('synthetic-launch-sensitive-marker')
    try:
        with monkeypatch.context() as patch:
            patch.setattr(R.Thread, 'start', failed_start)
            first = worker.run_once(wait=False)
        assert first.claimed == first.failed == first.poisoned == 1
        assert first.started == worker.metrics().started == first.active == worker.active_count == 0
        assert len(queue.failures) == 1 and queue.acknowledged == []
        next_job = worker.run_once()
        assert next_job.claimed == next_job.started == next_job.succeeded == 1
        assert worker.metrics().started == 1 and worker.metrics().claimed == 2
    finally: worker.shutdown(timeout=0)


def test_tracing_exit_keeps_live_thread_in_capacity(monkeypatch):
    entered, release = Event(), Event()
    threads = []
    @contextmanager
    def delayed_exit(_context):
        threads.append(current_thread())
        try: yield
        finally:
            entered.set(); assert release.wait(2)
    queue = FakeQueue([job(suffix='trace'), job(suffix='next')])
    worker = make_runtime(queue, ManualClock(), success, max_concurrency=1)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(R, 'attach_trace_context', delayed_exit)
            assert worker.run_once(wait=False).started == 1
            assert entered.wait(1)
            second = worker.run_once(wait=False)
            assert second.claimed == second.started == 0 and second.backpressured
            assert worker.active_count == worker.metrics().max_active == 1
            assert worker.metrics().succeeded == 1
            assert len(queue.acknowledged) == 1
            release.set(); assert worker.wait_for_idle(timeout=1)
            assert worker.run_once().succeeded == 1
        assert worker.metrics().started == worker.metrics().succeeded == 2
    finally:
        release.set()
        for thread in threads: thread.join(2)
        worker.shutdown(timeout=0)
