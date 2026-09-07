"""Focused bounded-runner tests for the Phase 1.6 worker seam."""

from __future__ import annotations

import threading
import time

import pytest

from rick_observability import BoundedEventBuffer

from apps.worker.runner import (
    CANCELLED,
    COMPLETED,
    FAILED,
    JobOutcome,
    JobRejected,
    LocalJobRunner,
)


def test_pending_bound_rejects_without_running_and_cancel_frees_capacity() -> None:
    calls: list[str] = []
    runner = LocalJobRunner(max_pending=1, max_workers=1, autostart=False)
    try:
        first = runner.submit(lambda: calls.append("first"), job_id="first")
        assert first == "first"
        with pytest.raises(JobRejected) as rejected:
            runner.submit(lambda: calls.append("second"), job_id="second")
        assert rejected.value.code == "queue_full"
        assert calls == []
        assert runner.cancel("first") is True
        assert runner.get_status("first").status == CANCELLED
        second = runner.submit(lambda: calls.append("second"), job_id="second")
        assert second == "second"
        assert runner.run_next().status == COMPLETED
        assert calls == ["second"]
    finally:
        runner.shutdown()


def test_run_next_failure_is_terminal_and_does_not_leak_exception_text() -> None:
    runner = LocalJobRunner(max_pending=2, max_workers=1, autostart=False)
    try:
        job_id = runner.submit(lambda: (_ for _ in ()).throw(RuntimeError("provider secret https://bad")))
        snapshot = runner.run_next()
        assert snapshot is not None and snapshot.job_id == job_id
        assert snapshot.status == FAILED
        assert snapshot.terminal is True
        assert snapshot.error_code == "job_failed"
        assert snapshot.safe_error_message == "Job failed."
        assert "secret" not in str(snapshot.as_dict()).lower()
        assert runner.cancel(job_id) is False
    finally:
        runner.shutdown()


def test_context_cancellation_is_cooperative_and_published_is_terminal() -> None:
    runner = LocalJobRunner(max_pending=2, max_workers=1, autostart=False)
    try:
        def publish() -> JobOutcome:
            return JobOutcome(status="published", stage="verifying")

        published_id = runner.submit(publish)
        assert runner.run_next().status == "published"
        assert runner.get_status(published_id).terminal is True

        started = threading.Event()
        release = threading.Event()

        def cancellable(context) -> None:
            started.set()
            release.wait(2)
            context.checkpoint()

        cancellable_id = runner.submit(cancellable, with_context=True)
        runner.start()
        assert started.wait(1)
        assert runner.cancel(cancellable_id) is False
        assert runner.get_status(cancellable_id).cancel_requested is True
        release.set()
        assert runner.wait_for_terminal(cancellable_id, timeout=1).status == CANCELLED
    finally:
        runner.shutdown()


def test_progress_history_has_a_strict_finite_cap_and_keeps_safe_values() -> None:
    runner = LocalJobRunner(max_pending=1, max_workers=1, autostart=False)
    try:
        job_id = runner.submit(lambda: None)
        job = runner._jobs[job_id]
        history_limit = job.progress_history.maxlen
        assert history_limit is not None and history_limit > 0

        for index in range(history_limit + 10):
            assert runner.update_progress(
                job_id,
                stage=f"stage-{index}",
                progress=index / (history_limit + 10),
            ) is True

        assert len(job.progress_history) == history_limit
        assert job.progress_history[0] == (
            "stage-10",
            10 / (history_limit + 10),
        )
        assert job.progress_history[-1] == (
            f"stage-{history_limit + 9}",
            (history_limit + 9) / (history_limit + 10),
        )
        snapshot = runner.get_status(job_id)
        assert snapshot is not None
        assert snapshot.stage == f"stage-{history_limit + 9}"
        assert snapshot.progress == (history_limit + 9) / (history_limit + 10)
        assert "progress_history" not in snapshot.as_dict()
        retained = list(job.progress_history)
        assert runner.update_progress(job_id, stage="provider response secret", progress=0.5) is False
        assert list(job.progress_history) == retained
    finally:
        runner.shutdown()


def test_progress_update_and_normal_completion_keep_public_behavior() -> None:
    runner = LocalJobRunner(max_pending=1, max_workers=1, autostart=False)
    try:
        def work(context) -> JobOutcome:
            assert context.update(stage="parsing", progress=0.25) is True
            return JobOutcome(status="published", stage="published")

        job_id = runner.submit(work, with_context=True)
        snapshot = runner.run_next()
        assert snapshot is not None
        assert snapshot.job_id == job_id
        assert snapshot.status == "published"
        assert snapshot.stage == "published"
        assert snapshot.progress == 1.0
        assert list(runner._jobs[job_id].progress_history) == [("parsing", 0.25)]
    finally:
        runner.shutdown()


def test_shutdown_cancels_pending_and_rejects_new_work() -> None:
    runner = LocalJobRunner(max_pending=2, max_workers=1, autostart=False)
    pending_id = runner.submit(lambda: None)
    runner.shutdown()
    assert runner.get_status(pending_id).status == CANCELLED
    with pytest.raises(JobRejected) as rejected:
        runner.submit(lambda: None)
    assert rejected.value.code == "runner_closed"


def test_runner_events_are_bounded_opaque_and_sink_failures_are_isolated() -> None:
    sink = BoundedEventBuffer(max_events=8)
    runner = LocalJobRunner(max_pending=1, max_workers=1, autostart=False, event_sink=sink)
    try:
        job_id = runner.submit(
            lambda: None,
            job_id="job-1",
            metadata={"token": "do-not-emit", "safe": "retained-only-in-status"},
        )
        assert runner.run_next() is not None
        events = sink.snapshot()
        assert [event["event"] for event in events] == [
            "worker.job.enqueued",
            "worker.job.started",
            "worker.job.terminal",
        ]
        serialized = repr(events)
        assert job_id not in serialized
        assert "do-not-emit" not in serialized
        assert all(set(event["fields"]) <= {"job_ref", "status", "stage", "progress"} for event in events)
    finally:
        runner.shutdown()

    class BrokenSink:
        def emit(self, _event: object) -> None:
            raise RuntimeError("telemetry failure")

    broken_runner = LocalJobRunner(max_pending=1, max_workers=1, autostart=False, event_sink=BrokenSink())
    try:
        broken_runner.submit(lambda: None, job_id="job-2")
        assert broken_runner.run_next().status == COMPLETED
    finally:
        broken_runner.shutdown()


def test_runner_started_is_a_barrier_before_worker_started() -> None:
    sink = BoundedEventBuffer(max_events=8)
    runner = LocalJobRunner(max_pending=1, max_workers=1, autostart=False, event_sink=sink)
    try:
        job_id = runner.submit(lambda: None, job_id="barrier-job")
        runner.start()
        assert runner.wait_for_terminal(job_id, timeout=1).status == COMPLETED
        deadline = time.monotonic() + 1
        while len(sink.snapshot()) < 4 and time.monotonic() < deadline:
            time.sleep(0.001)
        assert [event["event"] for event in sink.snapshot()] == [
            "worker.job.enqueued",
            "worker.runner.started",
            "worker.job.started",
            "worker.job.terminal",
        ]
    finally:
        runner.shutdown()
