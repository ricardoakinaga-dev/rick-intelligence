#!/usr/bin/env python3
"""Run the real two-process Redis multi-replica rate-limit gate.

The gate starts two independent API-shaped processes against the same Redis
URL and proves that they consume one atomic, tenant-scoped bucket.  It never
uses the in-memory limiter and never treats a missing URL, driver, or runtime
as a pass; unavailable external capability is reported as
``BLOCKED_EXTERNAL``.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import inspect
import ipaddress
import json
import multiprocessing as multiprocessing_module
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-3/redis-multi-replica-runtime-gate.json"
WINDOW_SECONDS = 5.0
BUCKET_LIMIT = 2
WORKER_WAIT_SECONDS = 30.0
PROCESS_JOIN_SECONDS = 5.0


class _BlockedExternal(Exception):
    """The caller did not provide an approved executable runtime."""


class _InvalidConfiguration(Exception):
    """The supplied runtime configuration violates the gate contract."""


@dataclass(frozen=True)
class GateResult:
    name: str
    result: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        value = {"name": self.name, "result": self.result}
        if self.detail:
            value["detail"] = self.detail
        return value


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_url(url: str, *, allow_nonlocal: bool) -> None:
    """Validate URL shape without ever returning it in a diagnostic."""

    if not isinstance(url, str) or not url.strip():
        raise _BlockedExternal()
    try:
        parsed = urlsplit(url.strip())
        if parsed.scheme not in {"redis", "rediss"} or not parsed.netloc or not parsed.hostname:
            raise _InvalidConfiguration()
        if parsed.query or parsed.fragment:
            raise _InvalidConfiguration()
        if parsed.port is not None and not 1 <= parsed.port <= 65_535:
            raise _InvalidConfiguration()
    except (TypeError, UnicodeError, ValueError):
        raise _InvalidConfiguration() from None
    if not allow_nonlocal and not _is_loopback(parsed.hostname):
        raise _BlockedExternal()


def _runtime_dependencies() -> tuple[Any, ...] | None:
    """Load package composition helpers without importing the vendor eagerly."""

    sys.path[:0] = [
        str(ROOT / "packages/contracts/src"),
        str(ROOT / "packages/locking/src"),
    ]
    try:
        from rick_locking import RedisSettings, create_redis_client, create_redis_rate_limiter
    except ImportError:
        return None
    return RedisSettings, create_redis_client, create_redis_rate_limiter


def _send(channel: Any, value: Mapping[str, object]) -> None:
    """Send only bounded, sanitized observations over the private pipe."""

    try:
        channel.send(dict(value))
    except (BrokenPipeError, EOFError, OSError):
        pass


async def _close_client(client: object | None) -> None:
    if client is None:
        return
    closer = getattr(client, "aclose", None)
    if not callable(closer):
        closer = getattr(client, "close", None)
    if not callable(closer):
        return
    try:
        result = closer()
        if inspect.isawaitable(result):
            await result
    except Exception:
        # Cleanup is best effort; the gate's assertions have already been
        # emitted and no vendor exception text is safe to persist.
        return


def _settings_for(url: str, *, require_tls: bool, dependencies: tuple[Any, ...]) -> Any:
    settings_type = dependencies[0]
    parsed = urlsplit(url)
    environment = "production" if require_tls else "local"
    return settings_type(
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
        retry_max_attempts=1,
        retry_base_delay_seconds=0.0,
        retry_max_delay_seconds=0.0,
    )


async def _replica_process(
    url: str,
    run_id: str,
    replica: str,
    require_tls: bool,
    start_event: Any,
    continue_event: Any,
    channel: Any,
) -> None:
    """Exercise one API replica using its own Redis client and event loop."""

    client: Any | None = None
    limiter: Any | None = None
    tenant_limiter: Any | None = None
    try:
        dependencies = _runtime_dependencies()
        if dependencies is None:
            _send(channel, {"kind": "blocked", "reason": "redis_driver_unavailable"})
            return
        settings = _settings_for(url, require_tls=require_tls, dependencies=dependencies)
        create_client = dependencies[1]
        create_limiter = dependencies[2]
        client = create_client(settings)
        tenant_a = settings.namespace_for(f"runtime-tenant-a-{run_id}")
        tenant_b = settings.namespace_for(f"runtime-tenant-b-{run_id}")
        limiter = create_limiter(settings, tenant_a, client=client)
        tenant_limiter = create_limiter(settings, tenant_b, client=client)

        healthy = await limiter.health_check()
        production_safe = bool(getattr(limiter, "production_safe", False))
        production_ready = not require_tls
        if require_tls:
            production_ready = bool(await limiter.readiness_check())
        if not healthy or not production_ready:
            _send(channel, {"kind": "error", "error": "redis_health_failed"})
            return
        _send(
            channel,
            {
                "kind": "ready",
                "replica": replica,
                "pid": os.getpid(),
                "healthy": True,
                "tenant_namespace": tenant_a.scope_fingerprint,
                "other_namespace": tenant_b.scope_fingerprint,
                "production_safe": production_safe,
            },
        )
        if not start_event.wait(WORKER_WAIT_SECONDS):
            _send(channel, {"kind": "error", "error": "start_barrier_timeout"})
            return

        request_ids = (
            f"{replica}-request-1-{run_id}",
            f"{replica}-request-2-{run_id}",
        )
        first = [
            bool(
                await limiter.allow(
                    "chat",
                    limit=BUCKET_LIMIT,
                    window_seconds=WINDOW_SECONDS,
                    request_id=request_id,
                )
            )
            for request_id in request_ids
        ]
        _send(channel, {"kind": "first", "replica": replica, "first": first})
        if not continue_event.wait(WORKER_WAIT_SECONDS):
            _send(channel, {"kind": "error", "error": "continuation_barrier_timeout"})
            return

        other_replica = "api-b" if replica == "api-a" else "api-a"
        replay = bool(
            await limiter.allow(
                "chat",
                limit=BUCKET_LIMIT,
                window_seconds=WINDOW_SECONDS,
                request_id=f"{other_replica}-request-1-{run_id}",
            )
        )
        overflow = bool(
            await limiter.allow(
                "chat",
                limit=BUCKET_LIMIT,
                window_seconds=WINDOW_SECONDS,
                request_id=f"{replica}-overflow-{run_id}",
            )
        )
        other_tenant = bool(
            await tenant_limiter.allow(
                "chat",
                limit=BUCKET_LIMIT,
                window_seconds=WINDOW_SECONDS,
                request_id=f"{replica}-other-tenant-{run_id}",
            )
        )
        _send(
            channel,
            {
                "kind": "complete",
                "replica": replica,
                "replay": replay,
                "overflow": overflow,
                "other_tenant": other_tenant,
            },
        )
    except ImportError:
        _send(channel, {"kind": "blocked", "reason": "redis_driver_unavailable"})
    except Exception as exc:  # pragma: no cover - exercised by a live Redis.
        if type(exc).__name__ == "RedisDependencyError":
            _send(channel, {"kind": "blocked", "reason": "redis_driver_unavailable"})
        else:
            _send(channel, {"kind": "error", "error": type(exc).__name__})
    finally:
        if limiter is not None:
            try:
                await limiter.close()
            except Exception:
                pass
        if tenant_limiter is not None:
            try:
                await tenant_limiter.close()
            except Exception:
                pass
        await _close_client(client)
        try:
            channel.close()
        except (AttributeError, OSError):
            pass


def _replica_target(
    url: str,
    run_id: str,
    replica: str,
    require_tls: bool,
    start_event: Any,
    continue_event: Any,
    channel: Any,
) -> None:
    asyncio.run(
        _replica_process(
            url,
            run_id,
            replica,
            require_tls,
            start_event,
            continue_event,
            channel,
        )
    )


def _receive(channel: Any, timeout: float) -> dict[str, object]:
    if not channel.poll(timeout):
        return {"kind": "error", "error": "replica_result_timeout"}
    try:
        value = channel.recv()
    except (EOFError, OSError):
        return {"kind": "error", "error": "replica_result_unreadable"}
    return dict(value) if isinstance(value, dict) else {"kind": "error", "error": "replica_result_invalid"}


def _finish_process(process: Any) -> None:
    if getattr(process, "pid", None) is None:
        return
    process.join(PROCESS_JOIN_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(PROCESS_JOIN_SECONDS)


def _stop_processes(processes: list[Any], channels: list[Any]) -> None:
    for process in processes:
        _finish_process(process)
    for channel in channels:
        try:
            channel.close()
        except (AttributeError, OSError):
            pass


def _local_results(observations: list[dict[str, object]]) -> tuple[list[GateResult], dict[str, object], bool]:
    """Derive bounded checks from both replica observations."""

    metrics: dict[str, object] = {
        "replica_count": len(observations),
        "distinct_processes": len({item.get("pid") for item in observations}) == 2,
        "shared_tenant_namespace": len({item.get("tenant_namespace") for item in observations}) == 1,
        "shared_other_tenant_namespace": len({item.get("other_namespace") for item in observations}) == 1,
        "tenant_namespace_differs": len(observations) == 2 and all(
            item.get("tenant_namespace") != item.get("other_namespace")
            for item in observations
        ),
    }
    results = [
        GateResult(
            "two-api-processes",
            "PASS" if metrics["distinct_processes"] else "FAIL",
            "two independent API-shaped processes produced the observations"
            if metrics["distinct_processes"]
            else "replica observations did not come from two distinct processes",
        ),
        GateResult(
            "tenant-namespace-isolation",
            "PASS"
            if metrics["shared_tenant_namespace"]
            and metrics["shared_other_tenant_namespace"]
            and metrics["tenant_namespace_differs"]
            else "FAIL",
            "both replicas share the tenant bucket while a second tenant has a different namespace",
        ),
    ]

    first = [item.get("first") for item in observations]
    valid_first = all(
        isinstance(values, list) and len(values) == 2 and all(type(value) is bool for value in values)
        for values in first
    )
    allowed_count = sum(bool(value) for values in first if isinstance(values, list) for value in values)
    metrics["shared_bucket_allowed"] = allowed_count
    metrics["shared_bucket_limit"] = BUCKET_LIMIT
    metrics["multi_replica_overflow_denied"] = all(item.get("overflow") is False for item in observations)
    first_by_replica = {
        str(item.get("replica")): values[0]
        for item, values in zip(observations, first)
        if isinstance(values, list) and values and isinstance(item.get("replica"), str)
    }
    metrics["replay_consistent"] = valid_first and set(first_by_replica) == {"api-a", "api-b"} and all(
        item.get("replay") == first_by_replica.get(
            "api-b" if item.get("replica") == "api-a" else "api-a"
        )
        for item in observations
    )
    metrics["other_tenant_allowed"] = sum(item.get("other_tenant") is True for item in observations)
    shared_ok = (
        valid_first
        and allowed_count == BUCKET_LIMIT
        and metrics["multi_replica_overflow_denied"] is True
    )
    results.extend(
        (
            GateResult(
                "shared-atomic-bucket",
                "PASS" if shared_ok else "FAIL",
                "the two replicas consumed exactly one shared fixed-window bucket"
                if shared_ok
                else "replicas did not consume exactly one shared bucket",
            ),
            GateResult(
                "request-replay-idempotency",
                "PASS" if metrics["replay_consistent"] is True else "FAIL",
                "replaying a request ID returned its original decision without a second token",
            ),
            GateResult(
                "RATE_LIMIT_MULTI_REPLICA_BYPASS_REJECTED",
                "PASS" if shared_ok else "FAIL",
                "a second API replica could not bypass the shared rate limit",
            ),
            GateResult(
                "other-tenant-bucket",
                "PASS" if metrics["other_tenant_allowed"] == 2 else "FAIL",
                "a separate tenant received its own bounded bucket",
            ),
        )
    )
    production_safe = all(item.get("production_safe") is True for item in observations)
    results.append(
        GateResult(
            "production-capability",
            "PASS" if production_safe else "PARTIAL",
            "both production-composed replicas reported a TLS/authenticated capability"
            if production_safe
            else "runtime semantics passed without a production-safe TLS capability",
        )
    )
    return results, metrics, production_safe


def _run_two_replicas(url: str, *, require_tls: bool, run_id: str) -> tuple[str, list[GateResult], dict[str, object], bool]:
    context = multiprocessing_module.get_context("spawn")
    start_event = context.Event()
    continue_event = context.Event()
    processes: list[Any] = []
    channels: list[Any] = []
    replicas = ("api-a", "api-b")
    try:
        for replica in replicas:
            parent, child = context.Pipe(duplex=False)
            process = context.Process(
                target=_replica_target,
                args=(url, run_id, replica, require_tls, start_event, continue_event, child),
                name=f"rick-runtime-{replica}",
            )
            processes.append(process)
            channels.append(parent)
            process.start()
            child.close()

        ready = [_receive(channel, WORKER_WAIT_SECONDS) for channel in channels]
        if any(item.get("kind") == "blocked" for item in ready):
            return (
                "BLOCKED_EXTERNAL",
                [GateResult("driver", "BLOCKED_EXTERNAL", "real Redis driver is unavailable")],
                {"replica_count": 2, "runtime_claim": False},
                False,
            )
        if any(item.get("kind") != "ready" for item in ready):
            return (
                "FAIL",
                [GateResult("startup", "FAIL", "one or more API-shaped replicas did not become ready")],
                {"replica_count": 2, "runtime_claim": False},
                False,
            )
        start_event.set()
        first = [_receive(channel, WORKER_WAIT_SECONDS) for channel in channels]
        if any(item.get("kind") != "first" for item in first):
            continue_event.set()
            return (
                "FAIL",
                [GateResult("shared-bucket", "FAIL", "one or more replicas failed before the bucket observation")],
                {"replica_count": 2, "runtime_claim": False},
                False,
            )
        continue_event.set()
        complete = [_receive(channel, WORKER_WAIT_SECONDS) for channel in channels]
        if any(item.get("kind") != "complete" for item in complete):
            return (
                "FAIL",
                [GateResult("completion", "FAIL", "one or more replicas failed after the bucket observation")],
                {"replica_count": 2, "runtime_claim": False},
                False,
            )
        observations = [
            {
                **ready_item,
                **first_item,
                **complete_item,
            }
            for ready_item, first_item, complete_item in zip(ready, first, complete)
        ]
        results, metrics, production_safe = _local_results(observations)
        status = "PASS" if all(item.result in {"PASS", "PARTIAL"} for item in results) else "FAIL"
        metrics["runtime_claim"] = status == "PASS"
        return status, results, metrics, production_safe
    finally:
        _stop_processes(processes, channels)


def run_gate(
    url: str,
    *,
    require_tls: bool = False,
    allow_nonlocal: bool = False,
) -> tuple[str, list[GateResult], dict[str, object], bool]:
    _validate_url(url, allow_nonlocal=allow_nonlocal)
    dependencies = _runtime_dependencies()
    if dependencies is None:
        return (
            "BLOCKED_EXTERNAL",
            [GateResult("driver", "BLOCKED_EXTERNAL", "locking package is unavailable")],
            {"replica_count": 2, "runtime_claim": False},
            False,
        )
    try:
        _settings_for(url, require_tls=require_tls, dependencies=dependencies)
    except Exception:
        return (
            "FAIL",
            [GateResult("configuration", "FAIL", "Redis runtime configuration was rejected")],
            {"replica_count": 2, "runtime_claim": False},
            False,
        )
    return _run_two_replicas(url, require_tls=require_tls, run_id=uuid.uuid4().hex[:12])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-url", default=os.environ.get("RICK_TEST_REDIS_URL", ""))
    parser.add_argument("--require-tls", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if not args.redis_url.strip():
        status = "BLOCKED_EXTERNAL"
        results = [GateResult("redis", status, "RICK_TEST_REDIS_URL or --redis-url is required")]
        metrics: dict[str, object] = {"replica_count": 2, "runtime_claim": False}
        production_safe = False
    else:
        try:
            status, results, metrics, production_safe = run_gate(
                args.redis_url,
                require_tls=args.require_tls,
                allow_nonlocal=args.allow_nonlocal,
            )
        except _BlockedExternal:
            status = "BLOCKED_EXTERNAL"
            results = [GateResult("endpoint-policy", status, "non-loopback Redis requires explicit runtime authority")]
            metrics = {"replica_count": 2, "runtime_claim": False}
            production_safe = False
        except _InvalidConfiguration:
            status = "FAIL"
            results = [GateResult("configuration", status, "Redis URL configuration was rejected")]
            metrics = {"replica_count": 2, "runtime_claim": False}
            production_safe = False
        except ValueError:
            status = "FAIL"
            results = [GateResult("configuration", status, "Redis URL configuration was rejected")]
            metrics = {"replica_count": 2, "runtime_claim": False}
            production_safe = False

    payload = {
        "schema_version": "phase3-redis-multi-replica-runtime-gate.v1",
        "status": status,
        "replicas": ["api-a", "api-b"],
        "results": [item.to_dict() for item in results],
        "metrics": metrics,
        "runtime_claim": status == "PASS",
        "production_safe": bool(production_safe),
    }
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "status": status, "production_safe": production_safe}, sort_keys=True))
    return 0 if status == "PASS" else (2 if status == "BLOCKED_EXTERNAL" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
