"""Run canonical HTTP rate-limit probes with our private Redis fixture config.

Uses actual two-process API and Redis I/O. Dev identity/stub generation means
this is bounded rate-limit evidence, not the installed IdP/revocation gate.
"""
from __future__ import annotations

import json
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
PRIVATE = Path("/tmp/rick-aud03-redis-private-bhvw7ief/private-config.json")
sys.path.insert(0, str(ROOT))
from scripts.phase11 import redis_multi_replica_runtime_gate as gate
from scripts.phase11.redis_runtime_gate import _reserve_output


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE, timeout=10).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        with _reserve_output(ROOT, args.output) as (output, destination):
            return _execute(output, destination)
    except Exception:
        print(json.dumps({"status": "FAIL", "error": "output_or_runtime_failed"}))
        return 1


def _execute(output, destination: Path) -> int:
    lab = json.loads((OUT / "redis-lab.json").read_text())
    config = json.loads(PRIVATE.read_text())
    name = config["container"]
    assert name == lab["container"] and name.startswith("rick-aud03-redis-")
    assert docker("inspect", name, "--format", '{{index .Config.Labels "rick.audit"}}') == "AUD03"
    assert docker("inspect", name, "--format", "{{.State.Running}}") == "true"
    assert docker("inspect", name, "--format", "{{.State.Paused}}") == "false"
    assert docker("inspect", name, "--format", "{{.Image}}") == lab["image_id"]
    assert docker("port", name, "6379/tcp").startswith("127.0.0.1:")
    # Keep credentials in process memory/environment, never in argv or files.
    previous = os.environ.get("RICK_TEST_REDIS_URL")
    os.environ["RICK_TEST_REDIS_URL"] = config["redis_url"]
    try:
        args = gate._parse_args(["--output", str(destination.relative_to(ROOT))])
        return gate._execute(args, output, destination)
    finally:
        if previous is None:
            os.environ.pop("RICK_TEST_REDIS_URL", None)
        else:
            os.environ["RICK_TEST_REDIS_URL"] = previous


if __name__ == "__main__":
    raise SystemExit(main())
