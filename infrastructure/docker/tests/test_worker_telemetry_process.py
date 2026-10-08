"""Exercise diagnostic draining through the actual worker process entrypoint."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT = ROOT / "infrastructure/docker/worker-entrypoint.py"
OBSERVABILITY = ROOT / "packages/observability/src"

COMPOSITION = textwrap.dedent(
    """
    import atexit
    import json
    import os
    from pathlib import Path
    import threading
    import time
    from rick_observability import emit_safely, sink_delivery_snapshot

    root = Path(os.environ["RICK_TEST_OUTPUT"])
    mode = os.environ["RICK_TEST_MODE"]
    release = threading.Event()
    started = threading.Event()

    def snapshot():
        result = sink_delivery_snapshot()
        result["live_threads"] = sum(
            thread.is_alive() and thread.name.startswith("rick-observability-sink-")
            for thread in threading.enumerate()
        )
        (root / "snapshot.json").write_text(json.dumps(result))

    atexit.register(snapshot)

    def deliver(event):
        started.set()
        release.wait()
        time.sleep(0.03)
        (root / event["event"]).write_text("delivered")

    class Worker:
        def __init__(self):
            self.stopped = False

        def startup(self):
            for index in range(3):
                emit_safely(deliver, f"test.event.{index}", {}, timeout=0)
            if not started.wait(2.0):
                raise RuntimeError("callback did not start")
            if mode == "startup_failure":
                release.set()
                raise RuntimeError("synthetic-sensitive-marker")

        def readiness_check(self):
            return True

        def run_forever(self):
            (root / "ready").touch()
            if mode == "run_failure":
                raise RuntimeError("synthetic-sensitive-marker")
            if mode == "complete":
                return
            while not self.stopped:
                time.sleep(0.01)

        def stop(self):
            self.stopped = True

        def shutdown(self, *, timeout):
            (root / "worker_closed").write_text(str(timeout))
            emit_safely(deliver, "test.event.final", {}, timeout=0)
            if mode != "blocked":
                release.set()

    def make_worker():
        return Worker()
    """
)


class WorkerTelemetryProcessTests(unittest.TestCase):
    def _run(
        self,
        mode: str,
        *,
        stop_signal: signal.Signals | None = None,
        health_check: bool = False,
        embedded: bool = False,
    ) -> tuple[int, str, dict, list[str], float]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "telemetry_probe.py").write_text(COMPOSITION, encoding="utf-8")
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": os.pathsep.join((directory, str(OBSERVABILITY))),
                "RICK_WORKER_COMPOSITION": "telemetry_probe:make_worker",
                "RICK_TEST_OUTPUT": directory,
                "RICK_TEST_MODE": mode,
            }
            command = [sys.executable, str(ENTRYPOINT)]
            if embedded:
                command = [
                    sys.executable, "-c",
                    "import runpy, sys; "
                    "entry = runpy.run_path(sys.argv[1]); "
                    "result = entry['main']([]); "
                    "from rick_observability import emit_safely; "
                    "from pathlib import Path; "
                    "assert emit_safely(lambda event: Path('test.event.embedded').touch(), "
                    "'test.event.embedded', {}, timeout=1.0); "
                    "raise SystemExit(result)",
                    str(ENTRYPOINT),
                ]
            if health_check:
                command.append("--health-check")
            process = subprocess.Popen(
                command, cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                if stop_signal is not None:
                    deadline = time.monotonic() + 5.0
                    while not (root / "ready").exists():
                        if process.poll() is not None:
                            stdout, stderr = process.communicate()
                            self.fail(f"process exited before ready: {stdout!r} {stderr!r}")
                        if time.monotonic() >= deadline:
                            self.fail("process did not become ready")
                        time.sleep(0.01)
                    began = time.monotonic()
                    process.send_signal(stop_signal)
                else:
                    began = time.monotonic()
                stdout, stderr = process.communicate(timeout=6.0)
                elapsed = time.monotonic() - began
                self.assertEqual(stdout, "")
                self.assertNotIn("synthetic-sensitive-marker", stderr)
                snapshot = json.loads((root / "snapshot.json").read_text())
                delivered = sorted(path.name for path in root.glob("test.event.*"))
                if mode != "startup_failure":
                    self.assertEqual((root / "worker_closed").read_text(), "30.0")
                return process.returncode, stderr, snapshot, delivered, elapsed
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def _assert_drained(self, result, *, exit_code: int = 0, events: int = 4) -> None:
        observed_exit, stderr, snapshot, delivered, _elapsed = result
        self.assertEqual(observed_exit, exit_code, stderr)
        self.assertTrue(snapshot["closed"])
        self.assertEqual(snapshot["queued"], 0)
        self.assertEqual(snapshot["active"], 0)
        self.assertEqual(snapshot["live_threads"], 0)
        self.assertEqual(len(delivered), events)
        counters = {row["name"]: row["total"] for row in snapshot["counters"]}
        self.assertEqual(counters["sink.delivery.emitted"], events)
        self.assertEqual(counters["sink.delivery.shutdown_timeout"], 0)

    def test_sigterm_drains_queued_and_cleanup_events(self) -> None:
        self._assert_drained(self._run("signal", stop_signal=signal.SIGTERM))

    def test_sigint_drains_queued_and_cleanup_events(self) -> None:
        self._assert_drained(self._run("signal", stop_signal=signal.SIGINT))

    def test_normal_completion_drains_events(self) -> None:
        self._assert_drained(self._run("complete"))

    def test_health_check_drains_events(self) -> None:
        self._assert_drained(self._run("health", health_check=True))

    def test_imported_main_keeps_shared_delivery_usable(self) -> None:
        exit_code, stderr, snapshot, delivered, _elapsed = self._run(
            "complete", embedded=True,
        )
        self.assertEqual(exit_code, 0, stderr)
        self.assertFalse(snapshot["closed"])
        self.assertIn("test.event.embedded", delivered)

    def test_run_failure_keeps_exit_status_and_drains_events(self) -> None:
        self._assert_drained(self._run("run_failure"), exit_code=1)

    def test_startup_failure_keeps_exit_status_and_drains_events(self) -> None:
        self._assert_drained(self._run("startup_failure"), exit_code=78, events=3)

    def test_blocked_sink_has_bounded_shutdown_and_safe_diagnostic(self) -> None:
        exit_code, stderr, snapshot, delivered, elapsed = self._run(
            "blocked", stop_signal=signal.SIGTERM,
        )
        self.assertEqual(exit_code, 0, stderr)
        self.assertIn("worker telemetry drain incomplete", stderr)
        self.assertGreaterEqual(elapsed, 1.8)
        self.assertLess(elapsed, 5.0)
        self.assertTrue(snapshot["closed"])
        self.assertEqual(snapshot["queued"], 0)
        self.assertEqual(delivered, [])
        counters = {row["name"]: row["total"] for row in snapshot["counters"]}
        self.assertEqual(counters["sink.delivery.shutdown_timeout"], 1)
        self.assertGreaterEqual(counters["sink.delivery.dropped"], 1)


if __name__ == "__main__":
    unittest.main()
