"""Partial launch and tracing faults remain inside the worker boundary."""
from contextlib import contextmanager
from threading import Event
import threading
import pytest
import runtime as R
from test_runtime import FakeQueue, ManualClock, job, make_runtime, success

MARKER = 'synthetic-tracing-sensitive-marker'


@pytest.mark.parametrize('finished', [False, True])
def test_post_launch_exception_keeps_one_owner_and_one_ack(monkeypatch, finished):
    entered, release = Event(), Event()
    queue = FakeQueue([job(suffix='post-launch')])
    def handler(j,l,*,cancelled):
        entered.set()
        if not finished: assert release.wait(2)
        return success(j,l,cancelled=cancelled)
    worker = make_runtime(queue, ManualClock(), handler, max_concurrency=1)
    original = R.Thread.start
    def after_launch(thread):
        original(thread); assert entered.wait(1)
        if finished: thread.join(1); assert not thread.is_alive()
        raise RuntimeError(MARKER)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(R.Thread, 'start', after_launch)
            first = worker.run_once(wait=False)
        assert first.started == worker.metrics().started == 1
        assert first.failed == first.poisoned == worker.metrics().failed == 0
        assert queue.failures == []
        release.set(); assert worker.wait_for_idle(timeout=1)
        assert len(queue.acknowledged) == worker.metrics().succeeded == 1
        assert worker.metrics().queue_errors == 0 and queue.failures == []
    finally:
        release.set(); worker.shutdown(timeout=0)


@pytest.mark.parametrize('which', ['attach_enter','span_enter','attach_exit','span_exit','recorder'])
def test_tracing_faults_never_escape_thread_or_hold_dead_slot(monkeypatch, which):
    unhandled = []
    monkeypatch.setattr(threading, 'excepthook', lambda args: unhandled.append(str(args.exc_value)))
    @contextmanager
    def broken_context(*args, **kwargs):
        if which.endswith('enter'): raise RuntimeError(MARKER)
        try: yield None
        finally:
            if which.endswith('exit'): raise RuntimeError(MARKER)
    if which.startswith('attach'): monkeypatch.setattr(R, 'attach_trace_context', broken_context)
    elif which.startswith('span'): monkeypatch.setattr(R, 'stage_span', broken_context)
    else:
        def broken_recorder(*args): raise RuntimeError(MARKER)
        monkeypatch.setattr(R, 'record_safe_exception', broken_recorder)
    calls = []
    def handler(j,l,*,cancelled):
        calls.append(str(j.job_id))
        if which == 'recorder': raise ValueError(MARKER)
        return success(j,l,cancelled=cancelled)
    queue = FakeQueue([job(suffix=which)])
    worker = make_runtime(queue, ManualClock(), handler, max_concurrency=1)
    try:
        worker.run_once(wait=False)
        assert worker.wait_for_idle(timeout=.05)
        assert unhandled == []
        assert worker.active_count == 0 and worker.metrics().timed_out == 0
        expected_failed = which.endswith('enter') or which == 'recorder'
        assert worker.metrics().failed == len(queue.failures) == int(expected_failed)
        assert worker.metrics().succeeded == len(queue.acknowledged) == int(not expected_failed)
        assert len(calls) == int(not which.endswith('enter'))
        assert all(MARKER not in failure.message for _,failure in queue.failures)
        assert worker.run_once().started == 0
    finally: worker.shutdown(timeout=0)
