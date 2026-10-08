"""Check the real budget test against an in-memory mutant, leaving source intact."""

from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import types
import unittest


def main() -> int:
    evidence = Path(__file__).resolve().parent
    root = next(parent for parent in evidence.parents if (parent / ".agent/state.json").is_file())
    path = root / "infrastructure/docker/tests/test_worker_entrypoint.py"
    spec = importlib.util.spec_from_file_location("budget_contract_probe", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load budget contract tests")
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)
    source_path = tests.ENTRYPOINT_PATH
    original_bytes = source_path.read_bytes()
    source = original_bytes.decode("utf-8")
    needle = "observability.shutdown_sink_delivery(timeout=2.0)"
    if source.count(needle) != 1:
        raise AssertionError("the expected mutation point changed")
    mutant = types.ModuleType("budget_mutant_entrypoint")
    exec(compile(source.replace(needle, "observability.shutdown_sink_delivery(timeout=3.0)"),
                 str(source_path), "exec"), mutant.__dict__)
    tests.ENTRYPOINT = mutant
    stream = io.StringIO()
    suite = unittest.TestSuite([
        tests.WorkerEntrypointTests("test_process_drain_uses_fixed_budget_and_preserves_operational_outcome"),
    ])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    log = stream.getvalue()
    (evidence / "budget-mutation.log").write_text(log, encoding="utf-8")
    if result.testsRun != 1 or len(result.failures) != 9 or result.errors:
        raise AssertionError("all nine outcomes must reject the changed budget")
    for _test, failure in result.failures:
        if "timeout=2.0" not in failure or "timeout=3.0" not in failure:
            raise AssertionError("mutation failed for an unexpected reason")
    if source_path.read_bytes() != original_bytes:
        raise AssertionError("repository source changed during the mutation check")
    conclusion = (
        "PASS: all nine outcome combinations rejected the in-memory 3.0-second mutation; "
        "source unchanged at SHA-256 " + hashlib.sha256(original_bytes).hexdigest() + ".\n"
    )
    with (evidence / "budget-mutation.log").open("a", encoding="utf-8") as handle:
        handle.write("\n" + conclusion)
    print(conclusion, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
