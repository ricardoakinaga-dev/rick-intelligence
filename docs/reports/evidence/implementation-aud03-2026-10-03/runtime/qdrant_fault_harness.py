"""Inject a pause at the existing gate's fault boundary in our disposable lab.

All protocol assertions and HTTP calls stay in the unmodified gate functions.
The wrapper adds only resource verification and pause/unpause, never fake I/O.
This is local fault evidence, not installed-system or production acceptance.
"""
from __future__ import annotations

import datetime
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
DEFAULT_OUTPUT = str((OUT / "qdrant-live-fault.json").relative_to(ROOT))
DEFAULT_OBSERVATIONS = str((OUT / "qdrant-fault-observations.json").relative_to(ROOT))
sys.path.insert(0, str(ROOT))
from scripts.phase11.redis_runtime_gate import _reserve_output


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE, timeout=10).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--observations", default=DEFAULT_OBSERVATIONS)
    args = parser.parse_args(argv)
    try:
        with _reserve_output(ROOT, args.output) as (output, destination):
            with _reserve_output(ROOT, args.observations) as (observed, _):
                return _execute(output, destination, observed)
    except Exception:
        print(json.dumps({"status": "FAIL", "error": "output_or_runtime_failed"}))
        return 1


def _execute(output, destination: Path, observed) -> int:
    lab = json.loads((OUT / "qdrant-lab.json").read_text())
    name = lab["container"]
    assert name.startswith("rick-aud03-qdrant-")
    assert docker("inspect", name, "--format", '{{index .Config.Labels "rick.audit"}}') == "AUD03"
    assert docker("inspect", name, "--format", "{{.State.Running}}") == "true"
    assert docker("inspect", name, "--format", "{{.State.Paused}}") == "false"
    assert docker("inspect", name, "--format", "{{.Image}}") == lab["image_id"]
    assert docker("port", name, "6333/tcp") == f'127.0.0.1:{lab["port"]}'
    source = ROOT / "scripts/phase11/object_qdrant_runtime_gate.py"
    spec = importlib.util.spec_from_file_location("aud03_live_qdrant_gate", source)
    assert spec and spec.loader
    gate = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gate
    spec.loader.exec_module(gate)
    original = gate._run_qdrant_failure_policy
    observations = {
        "scope": "own loopback Qdrant paused only during the gate's fault stage",
        "instrumentation": "resource pause/unpause around original _run_qdrant_failure_policy; no assertion/result replacement",
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "image_id": lab["image_id"],
        "gate_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }

    def fault_stage(*args, **kwargs):
        start = time.monotonic()
        try:
            docker("pause", name)
            results, blocked = original(*args, **kwargs)
            observations["fault_results"] = [result.to_dict() for result in results]
            observations["fault_blocked"] = blocked
            return results, blocked
        finally:
            docker("unpause", name)
            observations["paused_seconds"] = time.monotonic() - start
            observations["unpaused"] = docker("inspect", name, "--format", "{{.State.Paused}}") == "false"
            assert observations["unpaused"]

    gate._run_qdrant_failure_policy = fault_stage
    endpoint = f'http://127.0.0.1:{lab["port"]}'
    try:
        args = gate._parse_args([
            "--qdrant-url", endpoint, "--qdrant-fault-url", endpoint,
            "--qdrant-timeout-url", endpoint,
            "--output", str(destination.relative_to(ROOT)),
        ])
        code = gate._execute(args, output, destination)
        observations["gate_exit"] = code
        return code
    finally:
        gate._run_qdrant_failure_policy = original
        observations["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        observed.write(json.dumps(observations, indent=2) + "\n")
        observed.flush()


if __name__ == "__main__":
    raise SystemExit(main())
