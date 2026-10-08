from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import textwrap
import types
import unittest
from unittest.mock import Mock, patch


ENTRYPOINT_PATH = Path(__file__).resolve().parents[1] / "worker-entrypoint.py"


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location("rec33_worker_entrypoint", ENTRYPOINT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load worker entrypoint")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENTRYPOINT = _load_entrypoint()


class _Worker:
    def __init__(self) -> None:
        self.ran = False

    def health_check(self) -> bool:
        return True

    def run_forever(self) -> None:
        self.ran = True


class _LifecycleWorker(_Worker):
    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.stopped = False
        self.closed = False

    def startup(self) -> None:
        self.started = True

    def readiness_check(self) -> bool:
        return self.started

    def stop(self) -> None:
        self.stopped = True

    def shutdown(self, *, timeout: float) -> None:
        assert timeout > 0
        self.closed = True


class _TimedOutWorker(_Worker):
    def startup(self) -> None:
        return None

    def readiness_check(self) -> bool:
        return True

    def shutdown(self, *, timeout: float):
        return types.SimpleNamespace(timed_out=True)


class WorkerEntrypointTests(unittest.TestCase):
    def test_missing_composition_fails_closed_without_printing_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as raised:
                ENTRYPOINT.main([])
        self.assertEqual(raised.exception.code, ENTRYPOINT.EXIT_CONFIGURATION)

    def test_injected_factory_supports_health_and_run_contract(self) -> None:
        worker = _Worker()
        module = types.ModuleType("rec33_test_composition")
        module.make_worker = lambda: worker
        with patch.dict(sys.modules, {"rec33_test_composition": module}):
            with patch.dict(os.environ, {ENTRYPOINT.COMPOSITION_ENV: "rec33_test_composition:make_worker"}, clear=True):
                self.assertEqual(ENTRYPOINT.main(["--health-check"]), 0)
                self.assertEqual(ENTRYPOINT.main([]), 0)
        self.assertTrue(worker.ran)

    def test_invalid_composition_specification_is_rejected(self) -> None:
        with patch.dict(os.environ, {ENTRYPOINT.COMPOSITION_ENV: "not-a-module"}, clear=True):
            with self.assertRaises(SystemExit) as raised:
                ENTRYPOINT.main([])
        self.assertEqual(raised.exception.code, ENTRYPOINT.EXIT_CONFIGURATION)

    def test_lifecycle_worker_starts_before_run_and_closes_after_run(self) -> None:
        worker = _LifecycleWorker()
        module = types.ModuleType("rec33_lifecycle_composition")
        module.make_worker = lambda: worker
        with patch.dict(sys.modules, {"rec33_lifecycle_composition": module}):
            with patch.dict(os.environ, {ENTRYPOINT.COMPOSITION_ENV: "rec33_lifecycle_composition:make_worker"}, clear=True):
                self.assertEqual(ENTRYPOINT.main(["--health-check"]), 0)
                self.assertEqual(ENTRYPOINT.main([]), 0)
        self.assertTrue(worker.started)
        self.assertTrue(worker.ran)
        self.assertTrue(worker.closed)

    def test_shutdown_budget_does_not_depend_on_uptime(self) -> None:
        for uptime in (0.0, 29.5, 3600.0):
            with self.subTest(uptime=uptime):
                clock = types.SimpleNamespace(now=100.0)
                worker = _LifecycleWorker()

                def run_forever() -> None:
                    clock.now += uptime

                observed = []

                def shutdown(*, timeout: float) -> None:
                    observed.append(timeout)

                worker.run_forever = run_forever
                worker.shutdown = shutdown
                with patch.object(ENTRYPOINT, "_load_worker", return_value=worker):
                    with patch.object(time, "monotonic", side_effect=lambda: clock.now):
                        self.assertEqual(ENTRYPOINT.main([]), 0)
                self.assertEqual(observed, [30.0])

    def test_shutdown_timeout_is_not_reported_as_a_healthy_worker(self) -> None:
        worker = _TimedOutWorker()
        module = types.ModuleType("rec33_timeout_composition")
        module.make_worker = lambda: worker
        with patch.dict(sys.modules, {"rec33_timeout_composition": module}):
            with patch.dict(os.environ, {ENTRYPOINT.COMPOSITION_ENV: "rec33_timeout_composition:make_worker"}, clear=True):
                self.assertEqual(ENTRYPOINT.main(["--health-check"]), 1)

    def test_async_shutdown_result_controls_exit_status(self) -> None:
        for arguments in ([], ["--health-check"]):
            for report, expected in (
                (False, 1),
                (types.SimpleNamespace(timed_out=True), 1),
                (True, 0),
                (types.SimpleNamespace(timed_out=False), 0),
                (None, 0),
            ):
                with self.subTest(arguments=arguments, report=report):
                    worker = _LifecycleWorker()
                    observed = []

                    async def shutdown(*, wait: bool, timeout: float):
                        observed.append((wait, timeout))
                        return report

                    worker.shutdown = shutdown
                    with patch.object(ENTRYPOINT, "_load_worker", return_value=worker):
                        self.assertEqual(ENTRYPOINT.main(arguments), expected)
                    self.assertEqual(observed, [(True, 30.0)])


    def test_process_drain_uses_fixed_budget_and_preserves_operational_outcome(self) -> None:
        for operational_outcome in (0, 1, SystemExit(ENTRYPOINT.EXIT_CONFIGURATION)):
            for delivery_outcome, diagnostic in (
                (True, ""),
                (False, "worker telemetry drain incomplete\n"),
                (RuntimeError("synthetic-sensitive-marker"), "worker telemetry drain failed\n"),
            ):
                with self.subTest(operational_outcome=operational_outcome,
                                  delivery_outcome=delivery_outcome):
                    drain = Mock(return_value=delivery_outcome)
                    if isinstance(delivery_outcome, Exception):
                        drain.side_effect = delivery_outcome
                    observability = types.SimpleNamespace(shutdown_sink_delivery=drain)
                    diagnostic_stream = io.StringIO()
                    outcome = Mock(return_value=operational_outcome)
                    if isinstance(operational_outcome, SystemExit):
                        outcome.side_effect = operational_outcome
                    with (
                        patch.object(ENTRYPOINT, "main", outcome),
                        patch.dict(sys.modules, {"rick_observability": observability}),
                        redirect_stderr(diagnostic_stream),
                    ):
                        if isinstance(operational_outcome, SystemExit):
                            with self.assertRaises(SystemExit) as raised:
                                ENTRYPOINT._run_process()
                            self.assertIs(raised.exception, operational_outcome)
                            self.assertEqual(raised.exception.code, ENTRYPOINT.EXIT_CONFIGURATION)
                        else:
                            self.assertEqual(ENTRYPOINT._run_process(), operational_outcome)
                    drain.assert_called_once_with(timeout=2.0)
                    self.assertEqual(diagnostic_stream.getvalue(), diagnostic)

    def test_sigterm_stops_real_launcher_process_and_runs_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root / "ready"
            closed = root / "closed"
            (root / "signal_probe.py").write_text(
                textwrap.dedent(
                    """
                    import os
                    from pathlib import Path
                    import time

                    class Worker:
                        def __init__(self):
                            self.stopped = False

                        def run_forever(self):
                            Path(os.environ["RICK_WORKER_TEST_READY"]).touch()
                            while not self.stopped:
                                time.sleep(0.01)

                        def stop(self):
                            self.stopped = True

                        def shutdown(self, *, timeout):
                            Path(os.environ["RICK_WORKER_TEST_CLOSED"]).write_text(str(timeout))

                    def make_worker():
                        return Worker()
                    """
                ),
                encoding="utf-8",
            )
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": directory,
                "PYTHONDONTWRITEBYTECODE": "1",
                ENTRYPOINT.COMPOSITION_ENV: "signal_probe:make_worker",
                "RICK_WORKER_TEST_READY": str(ready),
                "RICK_WORKER_TEST_CLOSED": str(closed),
            }
            process = subprocess.Popen(
                [sys.executable, str(ENTRYPOINT_PATH)],
                cwd=root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 5.0
                while not ready.exists() and time.monotonic() < deadline:
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        self.fail(f"launcher exited before ready: {stdout!r} {stderr!r}")
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "launcher did not enter its worker loop")
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5.0)
                self.assertEqual(process.returncode, 0, f"stdout={stdout!r} stderr={stderr!r}")
                self.assertTrue(closed.exists(), "SIGTERM did not complete worker shutdown")
                self.assertEqual(closed.read_text(encoding="utf-8"), "30.0")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
