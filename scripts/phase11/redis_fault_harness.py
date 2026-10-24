#!/usr/bin/env python3
"""Real disposable Redis fault harness for the runtime gate.

Pauses the named disposable Redis container, observes the lease/limiter
health failing, resumes the container, and requires health recovery. The
container name is explicit (RICK_REDIS_CONTAINER) and defaults to the lab name.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/contracts/src"))
sys.path.insert(0, str(ROOT / "packages/locking/src"))


async def _exercise() -> bool:
    from rick_locking import (
        RedisNamespace,
        RedisSettings,
        create_redis_client,
        create_redis_lease_client,
        create_redis_rate_limiter,
    )

    url = os.environ.get("RICK_REDIS_URL", "").strip()
    container = os.environ.get("RICK_REDIS_CONTAINER", "rick-aud24-redis").strip()
    if not url or not container:
        return False
    parsed = urlsplit(url)
    settings = RedisSettings(
        url=url, environment="local", require_tls=None,
        require_auth=bool(parsed.password), verify_tls=True,
        max_connections=4, pool_timeout=1.0,
        socket_connect_timeout=0.5, socket_timeout=0.5, operation_timeout=1.0,
        retry_max_attempts=1, retry_base_delay_seconds=0.01, retry_max_delay_seconds=0.05,
    )
    run_id = os.environ.get("RICK_REDIS_RUN_ID", "fault")
    client = create_redis_client(settings)
    namespace = RedisNamespace(tenant_id=f"fault-{run_id}", environment="local")
    lease = create_redis_lease_client(settings, namespace, client=client)
    limiter = create_redis_rate_limiter(settings, namespace, client=client)
    try:
        before = bool(await lease.health_check() and await limiter.health_check())
        print(f"debug before={before}", file=sys.stderr)
        if not before:
            return False
        subprocess.run(["docker", "pause", container], check=True, capture_output=True, timeout=20)
        print("debug paused", file=sys.stderr)
        try:
            failed = False
            for _ in range(3):
                try:
                    if not (await lease.health_check() and await limiter.health_check()):
                        failed = True
                        break
                except Exception:
                    failed = True
                    break
                await asyncio.sleep(0.1)
            print(f"debug failed={failed}", file=sys.stderr)
            if not failed:
                return False
        finally:
            subprocess.run(["docker", "unpause", container], check=True, capture_output=True, timeout=20)
            print("debug unpaused", file=sys.stderr)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if await lease.health_check() and await limiter.health_check():
                    print("debug recovered", file=sys.stderr)
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.2)
        return False
    finally:
        for capability in (lease, limiter):
            close = getattr(capability, "close", None)
            if callable(close):
                try:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass


def main() -> int:
    try:
        passed = asyncio.run(_exercise())
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stderr)
        passed = False
    print(json.dumps({"circuit-breaker-recovery": "PASS" if passed else "FAIL"}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
