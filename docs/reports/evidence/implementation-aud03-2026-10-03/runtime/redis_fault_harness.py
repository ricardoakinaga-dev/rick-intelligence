"""Pause/recover only the Lead-owned disposable Redis and observe real circuit calls.

This local resource-bounded probe is not an installed-system chaos acceptance.
The private URL is inherited through the gate; it is never printed or recorded.
"""
from __future__ import annotations

import asyncio
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

OUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
DEFAULT_OUTPUT = str((OUT / "redis-fault-result.json").relative_to(ROOT))
DEFAULT_OBSERVATIONS = str((OUT / "redis-fault-observations.json").relative_to(ROOT))
sys.path.insert(0, str(ROOT))
from scripts.phase11.redis_runtime_gate import _reserve_output


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE, timeout=10).strip()


async def check() -> dict:
    from rick_locking import LeaseError, RedisLeaseClient, RedisSettings, create_redis_client

    lab = json.loads((OUT / "redis-lab.json").read_text())
    name = lab["container"]
    assert name.startswith("rick-aud03-redis-")
    assert docker("inspect", name, "--format", '{{index .Config.Labels "rick.audit"}}') == "AUD03"
    assert docker("inspect", name, "--format", '{{.State.Running}}') == "true"
    assert docker("inspect", name, "--format", '{{.State.Paused}}') == "false"
    assert docker("inspect", name, "--format", '{{.Image}}') == lab["image_id"]
    assert docker("port", name, "6379/tcp") == f'127.0.0.1:{lab["port"]}'
    settings = RedisSettings(url=os.environ["RICK_REDIS_URL"], environment="local",
        require_auth=True, max_connections=2, pool_timeout=0.1,
        socket_connect_timeout=0.2, socket_timeout=0.25, operation_timeout=0.4,
        retry_max_attempts=1, retry_base_delay_seconds=0.0, retry_max_delay_seconds=0.0,
        circuit_failure_threshold=1, circuit_cooldown_seconds=1.0)
    client = create_redis_client(settings)
    breaker = settings.circuit_breaker()
    lease = RedisLeaseClient(client, namespace=settings.namespace_for("aud03-fault-" + uuid.uuid4().hex[:12]),
        timeout=settings.operation_timeout, retry_policy=settings.retry_policy, circuit_breaker=breaker)
    observations = {"started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "own disposable loopback Redis; no TLS or installed deployment",
        "image_id": lab["image_id"], "operation_timeout_seconds": 0.4,
        "max_attempts": 1, "cooldown_seconds": 1.0}
    paused = False
    try:
        assert await lease.health_check()
        observations["initial_circuit"] = breaker.state
        assert breaker.state == "closed"
        # Even a timed-out pause may have reached Docker; cleanup must run.
        paused = True
        docker("pause", name)
        start = time.monotonic()
        assert await lease.health_check() is False
        observations["failed_probe_seconds"] = time.monotonic() - start
        observations["failed_probe_circuit"] = breaker.state
        assert observations["failed_probe_seconds"] < 1.5
        assert breaker.state == "open"
        start = time.monotonic()
        try:
            await lease.acquire("blocked-by-real-open-circuit", 1_000)
        except LeaseError as error:
            observations["open_circuit_error"] = error.error_code
            assert error.error_code == "unavailable"
        else:
            raise AssertionError("open circuit admitted a lease")
        observations["open_circuit_denial_seconds"] = time.monotonic() - start
        assert observations["open_circuit_denial_seconds"] < 0.25
        docker("unpause", name)
        assert docker("inspect", name, "--format", '{{.State.Paused}}') == "false"
        paused = False
        await asyncio.sleep(1.05)
        observations["before_recovery_circuit"] = breaker.state
        assert breaker.state == "half_open"
        assert await lease.health_check()
        observations["recovered_circuit"] = breaker.state
        assert breaker.state == "closed"
        handle = await lease.acquire("recovered-real-lease", 1_000)
        assert handle is not None and await handle.release()
        observations["post_recovery_acquire_release"] = "PASS"
        observations["status"] = "PASS"
        return observations
    finally:
        try:
            if paused:
                docker("unpause", name)
                assert docker("inspect", name, "--format", '{{.State.Paused}}') == "false"
        finally:
            try:
                await lease.close()
            finally:
                await client.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--observations", default=DEFAULT_OBSERVATIONS)
    args = parser.parse_args(argv)
    try:
        with _reserve_output(ROOT, args.output) as (output, _):
            with _reserve_output(ROOT, args.observations) as (observed, _):
                return _execute(output, observed)
    except Exception:
        print(json.dumps({"circuit-breaker-recovery": "FAIL", "error": "output_or_runtime_failed"}))
        return 1


def _execute(output, observed) -> int:
    try:
        observations = asyncio.run(check())
        code = 0
    except Exception:
        observations = {"status": "FAIL", "error": "Redis fault verification failed"}
        code = 1
    observations["harness_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    observations["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    observed.write(json.dumps(observations, indent=2) + "\n")
    observed.flush()
    payload = {"circuit-breaker-recovery": observations["status"]}
    output.write(json.dumps(payload) + "\n")
    output.flush()
    print(json.dumps(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
