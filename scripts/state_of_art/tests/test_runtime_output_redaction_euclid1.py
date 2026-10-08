"""Filesystem, public CLI and fault-cleanup regressions for the Euclid rework."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
# Cited evidence: the policy keeps files referenced from scripts/tests versioned.
HARNESS_SOURCES = (
    "docs/reports/evidence/implementation-aud03-2026-10-03/runtime/redis_fault_harness.py",
    "docs/reports/evidence/implementation-aud03-2026-10-03/runtime/qdrant_fault_harness.py",
    "docs/reports/evidence/implementation-aud03-2026-10-03/runtime/redis_replica_harness.py",
)
GATES = ("redis_runtime_gate", "redis_multi_replica_runtime_gate", "object_qdrant_runtime_gate")
HARNESSES = tuple(Path(source).stem for source in HARNESS_SOURCES)
CANARY = "SYNTHETIC_EUCLID1_NEVER_PERSIST"


def load(name):
    if name in GATES:
        location = f"scripts/phase11/{name}.py"
    else:
        location = next(source for source in HARNESS_SOURCES if source.endswith(f"/{name}.py"))
    spec = importlib.util.spec_from_file_location(f"euclid1_{name}", ROOT / location)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # The evidence tree stays free of bytecode: no __pycache__ under docs/reports.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def args_for(name, output):
    if name == "object_qdrant_runtime_gate":
        return ["--qdrant-url", "", "--object-endpoint", "", "--output", output]
    if name in GATES:
        return ["--redis-url", "", "--output", output]
    return ["--output", output]


@pytest.mark.parametrize("name", GATES + HARNESSES)
@pytest.mark.parametrize("kind", ("existing", "directory", "symlink", "dangling", "parent-link",
                                  "traversal", "outside", "disabled", "parent-file", "unwritable"))
def test_bad_destinations_fail_before_any_work(name, kind, tmp_path, monkeypatch, capsys):
    gate = load(name)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    old = tmp_path / "sentinel"
    old.write_text("old evidence\n")
    output = "result.json"
    target = tmp_path / output
    if kind == "existing":
        target.write_text("original report\n")
    elif kind == "directory":
        target.mkdir()
    elif kind == "symlink":
        target.symlink_to(old)
    elif kind == "dangling":
        target.symlink_to(tmp_path / "absent")
    elif kind == "parent-link":
        (tmp_path / "linked").symlink_to(tmp_path, target_is_directory=True)
        output = "linked/new.json"
    elif kind == "traversal":
        output = "folder/../new.json"
    elif kind == "outside":
        output = str(tmp_path.parent / (tmp_path.name + "-outside.json"))
    elif kind == "disabled":
        output = ""
    elif kind == "parent-file":
        output = "sentinel/new.json"
    elif kind == "unwritable":
        if os.geteuid() == 0:
            pytest.skip("Unix permission rejection requires an unprivileged process")
        (tmp_path / "readonly").mkdir(mode=0o500)
        output = "readonly/new.json"
    def forbidden(*args, **kwargs):
        pytest.fail("runtime/config/fixture work ran before output validation")
    monkeypatch.setattr(gate, "_execute", forbidden)
    argv = args_for(name, output)
    if name in HARNESSES[:2]:
        argv += ["--observations", "new-observations.json"]
    try:
        assert gate.main(argv) == 1
    finally:
        if kind == "unwritable":
            (tmp_path / "readonly").chmod(0o700)
    captured = capsys.readouterr()
    assert "failed" in captured.out and not captured.err
    assert old.read_text() == "old evidence\n"
    if kind == "existing":
        assert target.read_text() == "original report\n"
    if kind == "symlink":
        assert target.is_symlink()
    if kind == "dangling":
        assert target.is_symlink() and not (tmp_path / "absent").exists()
    assert not (tmp_path / "new-observations.json").exists()


@pytest.mark.parametrize("name", HARNESSES[:2])
def test_observation_collision_blocks_faults(name, tmp_path, monkeypatch):
    harness = load(name)
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    old = tmp_path / "observations.json"
    old.write_text("old observations")
    monkeypatch.setattr(harness, "_execute", lambda *a: pytest.fail("fault executed"))
    assert harness.main(["--output", "new.json", "--observations", "observations.json"]) == 1
    assert old.read_text() == "old observations"
    assert (tmp_path / "new.json").read_bytes() == b""


@pytest.mark.parametrize("name", GATES)
def test_missing_capability_retains_code_two_and_cannot_be_reused(name, tmp_path, monkeypatch):
    gate = load(name)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    args = args_for(name, "fresh/nested.json")
    assert gate.main(args) == 2
    before = (tmp_path / "fresh/nested.json").read_bytes()
    assert json.loads(before)["status"] == "BLOCKED_EXTERNAL"
    assert gate.main(args) == 1
    assert (tmp_path / "fresh/nested.json").read_bytes() == before


@pytest.mark.parametrize("name", GATES)
def test_vendor_exception_is_fixed_and_redacted(name, tmp_path, monkeypatch, capsys):
    gate = load(name)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    class SensitiveError(ValueError):
        def __str__(self):
            pytest.fail("vendor exception text was accessed")
    def failure(*args, **kwargs):
        raise SensitiveError(CANARY)
    if name == "redis_runtime_gate":
        async def async_failure(*args, **kwargs):
            failure()
        monkeypatch.setattr(gate, "_run_checks", async_failure)
    elif name == "redis_multi_replica_runtime_gate":
        monkeypatch.setattr(gate, "run_gate", failure)
    else:
        monkeypatch.setattr(gate, "_run_object_gate", failure)
        monkeypatch.setattr(gate, "_run_vector_gate", failure)
    argv = args_for(name, "report.json")
    if name != "object_qdrant_runtime_gate":
        argv[1] = "redis://127.0.0.1:6379/0"
    assert gate.main(argv) == 1
    captured = capsys.readouterr()
    rendered = (tmp_path / "report.json").read_text()
    assert json.loads(rendered)["status"] == "FAIL"
    assert CANARY not in rendered + captured.out + captured.err


@pytest.mark.parametrize("name", GATES)
@pytest.mark.parametrize("status,code", (("PASS", 0), ("FAIL", 1), ("BLOCKED_EXTERNAL", 2)))
def test_public_writer_preserves_runtime_status_and_reserves_before_backend(
    name, status, code, tmp_path, monkeypatch
):
    gate = load(name)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    def backend(*args, **kwargs):
        assert (tmp_path / "result.json").is_file()
        assert (tmp_path / "result.json").read_bytes() == b""
        if name == "object_qdrant_runtime_gate":
            return gate._gate_report(status, [gate.GateResult("runtime", status)], auth_kind="synthetic")
        if name == "redis_multi_replica_runtime_gate":
            return status, [gate.GateResult("runtime", status)], {"replica_count": 2}, False
        return status, [gate.GateResult("runtime", status)], False
    if name == "redis_runtime_gate":
        async def async_backend(*args, **kwargs):
            return backend(*args, **kwargs)
        monkeypatch.setattr(gate, "_run_checks", async_backend)
    elif name == "redis_multi_replica_runtime_gate":
        monkeypatch.setattr(gate, "run_gate", backend)
    else:
        monkeypatch.setattr(gate, "_run_object_gate", backend)
        monkeypatch.setattr(gate, "_run_vector_gate", backend)
    argv = args_for(name, "result.json")
    if name != "object_qdrant_runtime_gate":
        argv[1] = "redis://127.0.0.1:6379/0"
    assert gate.main(argv) == code
    report = json.loads((tmp_path / "result.json").read_text())
    assert report["status"] == status
    assert report["runtime_claim"] is (status == "PASS")


@pytest.mark.parametrize("name", GATES)
def test_public_unicode_url_redaction(name, tmp_path):
    module_name = "scripts.phase11." + name
    runner = ("import importlib,sys; from pathlib import Path; "
              "m=importlib.import_module(sys.argv[1]); m.ROOT=Path(sys.argv[2]); "
              "sys.exit(m.main(sys.argv[3:]))")
    env = {k: v for k, v in os.environ.items() if not any(word in k for word in
        ("REDIS", "QDRANT", "OBJECT_STORE", "OBJECT_STORAGE", "S3_", "AWS_"))}
    url = f"redis://default:{CANARY}@127.0.0.1\uff1a6379/0"
    if name == "object_qdrant_runtime_gate":
        env["RICK_TEST_QDRANT_URL"] = f"http://default:{CANARY}@127.0.0.1\uff1a6333/"
    else:
        env["RICK_TEST_REDIS_URL"] = url
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", runner, module_name, str(tmp_path),
        "--output", "unicode.json"], env=env, cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    report = (tmp_path / "unicode.json").read_text()
    assert CANARY not in report + result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_exclusive_reservation_race_and_symlink_swap(tmp_path):
    gate = load("redis_runtime_gate")
    def attempt(_):
        try:
            with gate._reserve_output(tmp_path, "race.json") as (file, path):
                file.write("winner")
            return True
        except FileExistsError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(32))) == 1
    assert (tmp_path / "race.json").read_text() == "winner"
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("preserve")
    with gate._reserve_output(tmp_path, "swap.json") as (stream, path):
        path.rename(tmp_path / "reserved-inode")
        path.symlink_to(sentinel)
        stream.write("write held descriptor")
    assert sentinel.read_text() == "preserve"
    assert (tmp_path / "reserved-inode").read_text() == "write held descriptor"


def test_parent_link_race_does_not_follow_outside_root(tmp_path, monkeypatch):
    gate = load("redis_runtime_gate")
    parent = tmp_path / "parent"
    parent.mkdir()
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    sentinel = outside / "report.json"
    sentinel.write_text("preserve outside")
    original_open = os.open
    def swapping_open(path, flags, *args, **kwargs):
        if path == "report.json":
            parent.rename(tmp_path / "pinned")
            parent.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(gate.os, "open", swapping_open)
    with gate._reserve_output(tmp_path, "parent/report.json") as (stream, path):
        stream.write("owned")
    assert sentinel.read_text() == "preserve outside"
    assert (tmp_path / "pinned/report.json").read_text() == "owned"


@pytest.mark.parametrize("fault", ("pause-command", "probe"))
def test_redis_fault_always_unpauses_without_live_docker(fault, tmp_path, monkeypatch):
    harness = load("redis_fault_harness")
    monkeypatch.setattr(harness, "OUT", tmp_path)
    (tmp_path / "redis-lab.json").write_text(json.dumps(dict(
        container="rick-aud03-redis-synthetic", image_id="synthetic-image", port=1234)))
    monkeypatch.setenv("RICK_REDIS_URL", "redis://127.0.0.1:1234/0")
    calls = []
    def docker(*args):
        calls.append(args[0])
        if args[0] == "pause" and fault == "pause-command":
            raise subprocess.TimeoutExpired("synthetic docker pause", 1)
        if args[0] == "port":
            return "127.0.0.1:1234"
        if args[0] == "inspect":
            template = args[-1]
            return {"{{.State.Running}}": "true", "{{.State.Paused}}": "false",
                "{{.Image}}": "synthetic-image"}.get(template, "AUD03")
        return ""
    closed = []
    class Client:
        async def aclose(self):
            closed.append("client")
    class Lease:
        def __init__(self, *args, **kwargs):
            self.probes = 0
        async def health_check(self):
            self.probes += 1
            if self.probes > 1:
                raise RuntimeError(CANARY)
            return True
        async def close(self):
            closed.append("lease")
    settings = SimpleNamespace(operation_timeout=.4, retry_policy=None,
        circuit_breaker=lambda: SimpleNamespace(state="closed"), namespace_for=lambda x: x)
    monkeypatch.setitem(sys.modules, "rick_locking", SimpleNamespace(LeaseError=RuntimeError,
        RedisLeaseClient=Lease, RedisSettings=lambda **kw: settings, create_redis_client=lambda s: Client()))
    monkeypatch.setattr(harness, "docker", docker)
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
        asyncio.run(harness.check())
    assert "pause" in calls and "unpause" in calls
    assert calls.index("pause") < calls.index("unpause")
    assert closed == ["lease", "client"]


@pytest.mark.parametrize("fault", ("success", "pause-command", "probe"))
def test_qdrant_fault_returns_original_results_and_always_unpauses(fault, tmp_path, monkeypatch):
    """Test cleanup plumbing only; this makes no live Qdrant runtime claim."""
    harness = load("qdrant_fault_harness")
    monkeypatch.setattr(harness, "OUT", tmp_path)
    monkeypatch.setattr(harness, "ROOT", ROOT)
    (tmp_path / "qdrant-lab.json").write_text(json.dumps(dict(
        container="rick-aud03-qdrant-synthetic", image_id="synthetic-image", port=1234)))
    calls = []
    def docker(*args):
        calls.append(args[0])
        if args[0] == "pause" and fault == "pause-command":
            raise subprocess.TimeoutExpired("synthetic docker pause", 1)
        if args[0] == "port":
            return "127.0.0.1:1234"
        if args[0] == "inspect":
            return {"{{.State.Running}}": "true", "{{.State.Paused}}": "false",
                "{{.Image}}": "synthetic-image"}.get(args[-1], "AUD03")
        return ""
    result = SimpleNamespace(to_dict=lambda: {"result": "FAIL", "name": "real-result-contract"})
    original_return = ([result], True)
    def original(*args, **kwargs):
        if fault == "probe":
            raise RuntimeError(CANARY)
        return original_return
    fake_gate = SimpleNamespace(_run_qdrant_failure_policy=original, _parse_args=lambda args: args)
    def execute(*args):
        received = fake_gate._run_qdrant_failure_policy()
        assert received[0] is original_return[0]
        assert received[1] is original_return[1]
        return 1  # Preserve original FAIL; do not turn it into a harness PASS.
    fake_gate._execute = execute
    spec = SimpleNamespace(name="synthetic_qdrant_gate", loader=SimpleNamespace(exec_module=lambda m: None))
    monkeypatch.setattr(harness.importlib.util, "spec_from_file_location", lambda *args: spec)
    monkeypatch.setattr(harness.importlib.util, "module_from_spec", lambda spec: fake_gate)
    monkeypatch.setattr(harness, "docker", docker)
    import io
    observed = io.StringIO()
    if fault == "success":
        assert harness._execute(io.StringIO(), ROOT / "synthetic-report.json", observed) == 1
        assert json.loads(observed.getvalue())["gate_exit"] == 1
        assert json.loads(observed.getvalue())["fault_results"] == [result.to_dict()]
    else:
        with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
            harness._execute(io.StringIO(), ROOT / "synthetic-report.json", observed)
    assert "pause" in calls and "unpause" in calls
    assert calls.index("pause") < calls.index("unpause")
    assert fake_gate._run_qdrant_failure_policy is original


def test_replica_harness_preserves_original_gate_exit_and_restores_private_env(tmp_path, monkeypatch):
    harness = load("redis_replica_harness")
    monkeypatch.setattr(harness, "OUT", tmp_path)
    monkeypatch.setattr(harness, "PRIVATE", tmp_path / "private-synthetic.json")
    lab = dict(container="rick-aud03-redis-synthetic", image_id="synthetic-image", port=1234)
    (tmp_path / "redis-lab.json").write_text(json.dumps(lab))
    (tmp_path / "private-synthetic.json").write_text(json.dumps(dict(
        **lab, redis_url=f"redis://default:{CANARY}@127.0.0.1:1234/0")))
    def docker(*args):
        if args[0] == "port":
            return "127.0.0.1:1234"
        return {"{{.State.Running}}": "true", "{{.State.Paused}}": "false",
            "{{.Image}}": "synthetic-image"}.get(args[-1], "AUD03")
    monkeypatch.setattr(harness, "docker", docker)
    monkeypatch.setenv("RICK_TEST_REDIS_URL", "original-env-value")
    def execute(args, *unused):
        assert CANARY in args.redis_url
        return 2
    monkeypatch.setattr(harness.gate, "_execute", execute)
    import io
    assert harness._execute(io.StringIO(), ROOT / "synthetic-report.json") == 2
    assert os.environ["RICK_TEST_REDIS_URL"] == "original-env-value"
