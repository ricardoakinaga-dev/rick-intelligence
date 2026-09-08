from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


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


if __name__ == "__main__":
    unittest.main()
