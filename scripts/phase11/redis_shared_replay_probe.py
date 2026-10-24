#!/usr/bin/env python3
"""Prove the Redis rate-limit decision store is shared across two clients.

Two independent Redis clients and two limiter instances share one tenant
namespace. Replaying the same request ID through the second instance must not
consume another token; two distinct subsequent requests must exhaust the
limit of two. This is the package-level evidence for decision A.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/contracts/src"))
sys.path.insert(0, str(ROOT / "packages/locking/src"))


async def _run(url: str, tenant: str) -> dict[str, bool]:
    from rick_locking import (
        RedisNamespace,
        RedisSettings,
        create_redis_client,
        create_redis_rate_limiter,
    )

    parsed = urlsplit(url)
    settings = RedisSettings(
        url=url,
        environment="local",
        require_tls=None,
        require_auth=bool(parsed.password),
        verify_tls=True,
        max_connections=4,
        pool_timeout=1.0,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        operation_timeout=1.0,
        retry_max_attempts=1,
        retry_base_delay_seconds=0.01,
        retry_max_delay_seconds=0.05,
    )
    namespace = RedisNamespace(tenant_id=tenant, environment="local")
    first_client = create_redis_client(settings)
    second_client = create_redis_client(settings)
    first = create_redis_rate_limiter(settings, namespace, client=first_client)
    second = create_redis_rate_limiter(settings, namespace, client=second_client)
    try:
        replay_a = await first.allow("chat", limit=2, window_seconds=60, request_id="shared-request")
        replay_b = await second.allow("chat", limit=2, window_seconds=60, request_id="shared-request")
        second_unique = await first.allow("chat", limit=2, window_seconds=60, request_id="second-request")
        third_unique = await second.allow("chat", limit=2, window_seconds=60, request_id="third-request")
        return {
            "replay_on_first": replay_a,
            "replay_on_second": replay_b,
            "second_unique": second_unique,
            "third_unique": third_unique,
        }
    finally:
        await first.close()
        await second.close()


def main() -> int:
    url = os.environ.get("RICK_TEST_REDIS_URL", "").strip()
    tenant = os.environ.get("RICK_SHARED_REPLAY_TENANT", "shared-replay-probe").strip()
    if not url:
        print(json.dumps({"error": "RICK_TEST_REDIS_URL is required"}))
        return 2
    result = asyncio.run(_run(url, tenant))
    expected = {
        "replay_on_first": True,
        "replay_on_second": True,
        "second_unique": True,
        "third_unique": False,
    }
    passed = result == expected
    print(json.dumps({"status": "PASS" if passed else "FAIL", "observed": result}, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
