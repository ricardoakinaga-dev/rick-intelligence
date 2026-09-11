#!/usr/bin/env python3
"""Run the real Redis lease, namespace, and rate-limit runtime gate.

The gate is fail-closed.  It requires an explicitly supplied URL, refuses a
non-loopback endpoint unless the caller opts in, and never prints credentials.
A local authenticated Redis can prove runtime semantics, but it is not marked
production-promotable unless TLS and production settings are also present.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from urllib.parse import urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-2/redis-runtime-gate.json"
REDIS_FAULT_CASES = ("circuit-breaker-recovery",)


@dataclass(frozen=True)
class GateResult:
    name: str
    result: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        payload = {"name": self.name, "result": self.result}
        if self.detail:
            payload["detail"] = self.detail
        return payload


def _safe_url(url: str, *, allow_nonlocal: bool) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise ValueError("Redis URL must use redis:// or rediss:// with a hostname")
    if not allow_nonlocal and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("refusing non-loopback Redis URL without explicit runtime authority")
    if parsed.query or parsed.fragment:
        raise ValueError("Redis URL must not contain query or fragment data")


async def _run_checks(
    url: str,
    *,
    require_tls: bool,
    allow_nonlocal: bool,
) -> tuple[str, list[GateResult], bool]:
    _safe_url(url, allow_nonlocal=allow_nonlocal)
    try:
        from rick_locking import (
            RedisNamespace,
            RedisSettings,
            create_redis_client,
            create_redis_lease_client,
            create_redis_rate_limiter,
        )
    except ImportError:
        return (
            "BLOCKED_EXTERNAL",
            [GateResult("driver", "BLOCKED_EXTERNAL", "redis client package is not installed")],
            False,
        )

    parsed = urlsplit(url)
    # Local disposable stacks use plain Redis with an explicit password.  A
    # production check is opt-in and requires rediss:// plus the package's
    # production validation rules.
    environment = "production" if require_tls else "local"
    try:
        settings = RedisSettings(
            url=url,
            environment=environment,
            require_tls=True if require_tls else None,
            require_auth=True if parsed.password or require_tls else False,
            verify_tls=True,
            max_connections=8,
            pool_timeout=1.0,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
            operation_timeout=2.0,
            retry_max_attempts=2,
            retry_base_delay_seconds=0.01,
            retry_max_delay_seconds=0.05,
        )
        client = create_redis_client(settings)
    except Exception:
        return (
            "FAIL",
            [GateResult("configuration", "FAIL", "Redis runtime configuration was rejected")],
            False,
        )

    run_id = uuid.uuid4().hex[:12]
    namespace_a = settings.namespace_for(f"runtime-a-{run_id}")
    namespace_b = settings.namespace_for(f"runtime-b-{run_id}")
    lease_a = None
    lease_b = None
    limiter_a = None
    limiter_b = None
    heartbeat = None
    results: list[GateResult] = []
    try:
        lease_a = create_redis_lease_client(settings, namespace_a, client=client)
        lease_b = create_redis_lease_client(settings, namespace_a, client=client)
        limiter_a = create_redis_rate_limiter(settings, namespace_a, client=client)
        limiter_b = create_redis_rate_limiter(settings, namespace_b, client=client)

        health_lease = await lease_a.health_check()
        health_rate = await limiter_a.health_check()
        results.append(GateResult("health", "PASS" if health_lease and health_rate else "FAIL"))
        if not (health_lease and health_rate):
            return "FAIL", results, False

        results.append(
            GateResult(
                "tenant-namespace-isolation",
                "PASS" if namespace_a.key("probe", "same") != namespace_b.key("probe", "same") else "FAIL",
            )
        )

        handle_a = await lease_a.acquire(f"fence-{run_id}", 1_500)
        if handle_a is None:
            raise RuntimeError("first lease acquisition was denied")
        blocked_b = await lease_b.acquire(f"fence-{run_id}", 1_500)
        renewed = await handle_a.renew(1_500)
        heartbeat = handle_a.start_heartbeat(interval_ms=50)
        await asyncio.sleep(0.15)
        await heartbeat.stop()
        heartbeat_renewed = heartbeat.failure is None and await handle_a.renew(1_500)
        results.append(
            GateResult(
                "heartbeat-renewal",
                "PASS" if heartbeat_renewed else "FAIL",
                "caller-owned heartbeat renewed the live lease"
                if heartbeat_renewed
                else "heartbeat failed to renew the live lease",
            )
        )
        released = await handle_a.release()
        acquired_after_release = await lease_b.acquire(f"fence-{run_id}", 1_500)
        results.append(
            GateResult(
                "owner-safe-lease-fencing",
                "PASS"
                if blocked_b is None and renewed and released and acquired_after_release is not None
                else "FAIL",
            )
        )
        if acquired_after_release is not None:
            await acquired_after_release.release()

        request_id = f"runtime-request-{run_id}"
        first = await limiter_a.allow("chat", limit=2, window_seconds=1.0, request_id=request_id)
        replay = await limiter_a.allow("chat", limit=2, window_seconds=1.0, request_id=request_id)
        second = await limiter_a.allow("chat", limit=2, window_seconds=1.0, request_id=f"runtime-request-2-{run_id}")
        denied = await limiter_a.allow("chat", limit=2, window_seconds=1.0, request_id=f"runtime-request-3-{run_id}")
        other_tenant = await limiter_b.allow("chat", limit=1, window_seconds=1.0, request_id=f"runtime-tenant-b-{run_id}")
        results.append(
            GateResult(
                "atomic-rate-limit-and-replay",
                "PASS" if first and replay and second and not denied and other_tenant else "FAIL",
            )
        )

        # Force the real client pool to drop open sockets, then require the
        # next health probe to reconnect.  This exercises recovery through the
        # vendor pool instead of treating a still-open connection as proof.
        pool = getattr(client, "connection_pool", None)
        disconnect = getattr(pool, "disconnect", None)
        if not callable(disconnect):
            results.append(GateResult("reconnect-recovery", "FAIL", "Redis client pool has no disconnect hook"))
        else:
            try:
                disconnected = disconnect(inuse_connections=True)
                if inspect.isawaitable(disconnected):
                    await disconnected
                recovered = await lease_a.health_check() and await limiter_a.health_check()
            except Exception:
                recovered = False
            results.append(
                GateResult(
                    "reconnect-recovery",
                    "PASS" if recovered else "FAIL",
                    "health checks succeeded after the real pool was disconnected"
                    if recovered
                    else "Redis did not recover after the real pool disconnect",
                )
            )

        raw_harness = os.environ.get("RICK_REDIS_FAULT_HARNESS", "").strip()
        if not raw_harness:
            results.extend(
                GateResult(
                    case,
                    "BLOCKED_EXTERNAL",
                    "an explicit disposable fault harness is required; circuit recovery is never inferred from a local mock",
                )
                for case in REDIS_FAULT_CASES
            )
        else:
            try:
                completed = subprocess.run(
                    shlex.split(raw_harness),
                    cwd=ROOT,
                    env={**os.environ, "RICK_REDIS_URL": url, "RICK_REDIS_RUN_ID": run_id},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=180,
                )
                payload = json.loads(completed.stdout)
            except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
                payload = None
                completed = None
            for case in REDIS_FAULT_CASES:
                passed = isinstance(payload, dict) and completed is not None and completed.returncode == 0 and payload.get(case) == "PASS"
                results.append(
                    GateResult(
                        case,
                        "PASS" if passed else "FAIL",
                        "approved disposable fault-harness result"
                        if passed
                        else "fault harness did not prove circuit recovery",
                    )
                )
        production_safe = bool(
            require_tls
            and settings.is_production
            and settings.tls_enabled
            and settings.effective_require_auth
            and lease_a.production_safe
            and limiter_a.production_safe
        )
        results.append(
            GateResult(
                "production-capability",
                "PASS" if production_safe else "PARTIAL",
                "TLS/authenticated production composition is live"
                if production_safe
                else "runtime semantics passed without a production-safe TLS capability",
            )
        )
        status = "FAIL" if any(item.result == "FAIL" for item in results) else (
            "BLOCKED_EXTERNAL" if any(item.result == "BLOCKED_EXTERNAL" for item in results) else "PASS"
        )
        return status, results, production_safe
    except Exception:
        results.append(GateResult("runtime", "FAIL", "live Redis runtime assertion failed"))
        return "FAIL", results, False
    finally:
        if heartbeat is not None:
            try:
                await heartbeat.stop()
            except Exception:
                pass
        for capability in (lease_a, limiter_a, lease_b, limiter_b):
            if capability is not None:
                try:
                    await capability.close()
                except Exception:
                    pass
        closer = getattr(client, "aclose", None)
        if not callable(closer):
            closer = getattr(client, "close", None)
        if callable(closer):
            try:
                result = closer()
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                pass


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-url", default=os.environ.get("RICK_TEST_REDIS_URL", ""))
    parser.add_argument("--require-tls", action="store_true", help="require a production-safe rediss:// capability")
    parser.add_argument("--allow-nonlocal", action="store_true", help="require explicit authority for a non-loopback URL")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if not args.redis_url.strip():
        status = "BLOCKED_EXTERNAL"
        results = [GateResult("redis", status, "RICK_TEST_REDIS_URL or --redis-url is required")]
        production_safe = False
    else:
        try:
            status, results, production_safe = asyncio.run(
                _run_checks(
                    args.redis_url,
                    require_tls=args.require_tls,
                    allow_nonlocal=args.allow_nonlocal,
                )
            )
        except ValueError as exc:
            status = "FAIL"
            results = [GateResult("configuration", status, str(exc))]
            production_safe = False
    payload = {
        "schema_version": "phase-2-redis-runtime-gate.v1",
        "status": status,
        "results": [item.to_dict() for item in results],
        "runtime_claim": status == "PASS",
        "production_safe": production_safe,
    }
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "status": status, "production_safe": production_safe}, sort_keys=True))
    return 0 if status == "PASS" else (2 if status == "BLOCKED_EXTERNAL" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
