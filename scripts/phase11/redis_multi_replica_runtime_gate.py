#!/usr/bin/env python3
"""Run the real two-process Redis multi-replica API rate-limit gate.

The gate starts two independent canonical ``apps/api`` server processes
against the same Redis URL and proves the HTTP route policies consume one
atomic, tenant-scoped bucket. It never uses the in-memory limiter and never
treats a missing URL, driver, or runtime as a pass; unavailable external
capability is reported as ``BLOCKED_EXTERNAL``.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import inspect
import ipaddress
import json
import multiprocessing as multiprocessing_module
import os
from pathlib import Path
import socket
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
API_STARTUP_WAIT_SECONDS = 15.0
HTTP_REQUEST_TIMEOUT_SECONDS = 3.0
API_RATE_WINDOW_MS = 60_000


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


def _api_dependencies() -> tuple[Any, ...] | None:
    """Load the canonical API factory and real HTTP server dependencies."""

    package_paths = [
        ROOT / "apps/api/src",
        *(ROOT / "packages" / name / "src" for name in (
            "authorization",
            "contracts",
            "evidence",
            "identity",
            "ingestion",
            "jobs",
            "knowledge",
            "locking",
            "observability",
            "professor",
            "providers",
            "retrieval",
            "storage",
        )),
    ]
    sys.path[:0] = [str(path) for path in package_paths]
    try:
        import uvicorn

        from app import create_app
        from core.config import ApiSettings
    except ImportError:
        return None
    return create_app, ApiSettings, uvicorn


def _api_settings_for(settings_type: Any, *, api_key: str, bucket_limit: int) -> Any:
    """Build a hermetic API instance whose only external capability is Redis."""

    return settings_type(
        environment="test",
        identity_mode="dev",
        chat_backend_mode="stub",
        provider_kind="deterministic",
        external_chat_api_key="",
        compat_api_key=api_key,
        cors_allowed_origins=("http://127.0.0.1",),
        session_cookie_secure=False,
        login_rate_limit_per_min=bucket_limit,
        chat_rate_limit_per_min=bucket_limit,
        recovery_rate_limit_per_min=bucket_limit,
    )


def _api_bucket_key(limiter: Any, *, route_key: str) -> str:
    """Derive the package-owned bucket key without exposing its material."""

    logical_key = hashlib.sha256(route_key.encode("utf-8")).hexdigest()
    bucket_material = hashlib.sha256(
        f"{logical_key}\x1f{API_RATE_WINDOW_MS}".encode("utf-8")
    ).hexdigest()
    return limiter.namespace.key("rate-bucket", bucket_material)


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


async def _api_replica_process(
    url: str,
    run_id: str,
    replica: str,
    require_tls: bool,
    port: int,
    stop_event: Any,
    channel: Any,
) -> None:
    """Serve one real ``apps/api`` instance with a Redis-backed limiter."""

    client: Any | None = None
    limiter: Any | None = None
    server: Any | None = None
    serve_task: asyncio.Task[Any] | None = None
    try:
        dependencies = _runtime_dependencies()
        api_dependencies = _api_dependencies()
        if dependencies is None or api_dependencies is None:
            _send(channel, {"kind": "blocked", "reason": "api_or_redis_driver_unavailable"})
            return
        settings = _settings_for(url, require_tls=require_tls, dependencies=dependencies)
        create_client = dependencies[1]
        create_limiter = dependencies[2]
        create_app, api_settings_type, uvicorn = api_dependencies
        client = create_client(settings)
        namespace = settings.namespace_for(f"runtime-api-{run_id}")
        limiter = create_limiter(settings, namespace, client=client)

        if not await limiter.health_check():
            _send(channel, {"kind": "error", "error": "redis_health_failed"})
            return
        production_safe = bool(getattr(limiter, "production_safe", False))
        if require_tls and not await limiter.readiness_check():
            _send(channel, {"kind": "error", "error": "redis_production_readiness_failed"})
            return

        api_settings = _api_settings_for(
            api_settings_type,
            api_key=f"compat-{run_id}",
            bucket_limit=BUCKET_LIMIT,
        )
        app = create_app(api_settings)
        # The local API factory is real, but its default limiter is intentionally
        # in-memory. Replace that explicit local capability before any request;
        # a missing assignment would be a hard gate failure, never a fallback.
        providers = app.state.providers
        providers.rate_limiter = limiter
        identity = providers.identity
        tenant_id = f"runtime-tenant-{run_id}"
        identity.create_user(
            email=f"runtime-login-{run_id}@example.test",
            role="VETERINARIAN",
            tenant_id=tenant_id,
            password="password123",
        )
        identity.create_user(
            email=f"runtime-chat-{run_id}@example.test",
            role="VETERINARIAN",
            tenant_id=tenant_id,
            password="password123",
        )
        if getattr(providers, "rate_limiter", None) is not limiter:
            _send(channel, {"kind": "error", "error": "redis_limiter_not_bound"})
            return

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
            lifespan="on",
        )
        server = uvicorn.Server(config)
        # The gate owns process shutdown; it must not install handlers that
        # can turn a test cancellation into an unbounded server lifetime.
        server.install_signal_handlers = lambda: None
        serve_task = asyncio.create_task(server.serve())
        deadline = asyncio.get_running_loop().time() + API_STARTUP_WAIT_SECONDS
        while not server.started and not serve_task.done():
            if asyncio.get_running_loop().time() >= deadline:
                _send(channel, {"kind": "error", "error": "api_startup_timeout"})
                return
            await asyncio.sleep(0.01)
        if not server.started or serve_task.done():
            _send(channel, {"kind": "error", "error": "api_startup_failed"})
            return

        _send(
            channel,
            {
                "kind": "ready",
                "replica": replica,
                "pid": os.getpid(),
                "port": port,
                "http_boundary": True,
                "tenant_namespace": namespace.scope_fingerprint,
                "production_safe": production_safe,
            },
        )
        await asyncio.to_thread(stop_event.wait, WORKER_WAIT_SECONDS)

        route_key = ":".join(
            (
                "login",
                tenant_id,
                f"runtime-login-{run_id}@example.test",
                "127.0.0.1",
            )
        )
        pttl = getattr(client, "pttl", None)
        if not callable(pttl):
            _send(channel, {"kind": "error", "error": "redis_pttl_unavailable"})
            return
        bucket_ttl_ms = await pttl(_api_bucket_key(limiter, route_key=route_key))
        if type(bucket_ttl_ms) is not int:
            _send(channel, {"kind": "error", "error": "redis_pttl_invalid"})
            return
        _send(
            channel,
            {
                "kind": "complete",
                "replica": replica,
                "bucket_pttl_ms": bucket_ttl_ms,
                "production_safe": production_safe,
            },
        )
    except ImportError:
        _send(channel, {"kind": "blocked", "reason": "api_or_redis_driver_unavailable"})
    except Exception as exc:  # pragma: no cover - exercised by a live Redis.
        if type(exc).__name__ == "RedisDependencyError":
            _send(channel, {"kind": "blocked", "reason": "redis_driver_unavailable"})
        else:
            _send(channel, {"kind": "error", "error": type(exc).__name__})
    finally:
        if server is not None:
            server.should_exit = True
        if serve_task is not None and not serve_task.done():
            try:
                await asyncio.wait_for(serve_task, timeout=PROCESS_JOIN_SECONDS)
            except Exception:
                serve_task.cancel()
                try:
                    await serve_task
                except BaseException:
                    pass
        if limiter is not None:
            try:
                await limiter.close()
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
    port: int,
    stop_event: Any,
    channel: Any,
) -> None:
    asyncio.run(
        _api_replica_process(
            url,
            run_id,
            replica,
            require_tls,
            port,
            stop_event,
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


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _response_observation(response: Any, request_id: str) -> dict[str, object]:
    status = int(getattr(response, "status_code", 0))
    return {
        "status": status,
        "allowed": 200 <= status < 300,
        "denied": status == 429,
        "request_id_echoed": getattr(response, "headers", {}).get("x-request-id") == request_id,
    }


async def _post_http(client: Any, path: str, payload: Mapping[str, object], request_id: str, headers: Mapping[str, str] | None = None) -> dict[str, object]:
    try:
        response = await client.post(
            path,
            json=dict(payload),
            headers={"X-Request-ID": request_id, **dict(headers or {})},
        )
    except Exception as exc:  # pragma: no cover - exercised by a live API.
        return {"status": 0, "allowed": False, "denied": False, "request_id_echoed": False, "error": type(exc).__name__}
    return _response_observation(response, request_id)


async def _run_http_case(
    clients: tuple[Any, Any],
    path: str,
    payload: Mapping[str, object],
    run_id: str,
    case_name: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Run four unique HTTP IDs plus one cross-replica replay."""

    request_ids = tuple(f"{case_name}-{index}-{run_id}" for index in range(1, 5))
    first = await _post_http(clients[0], path, payload, request_ids[0], headers)
    replay = await _post_http(clients[1], path, payload, request_ids[0], headers)
    unique = [
        first,
        await _post_http(clients[0], path, payload, request_ids[1], headers),
        await _post_http(clients[1], path, payload, request_ids[2], headers),
        await _post_http(clients[0], path, payload, request_ids[3], headers),
    ]
    unique_allowed = sum(item.get("allowed") is True for item in unique)
    unique_denied = sum(item.get("denied") is True for item in unique)
    replay_consistent = (
        first.get("allowed") == replay.get("allowed")
        and first.get("denied") == replay.get("denied")
        and first.get("request_id_echoed") is True
        and replay.get("request_id_echoed") is True
    )
    passed = (
        unique_allowed == BUCKET_LIMIT
        and unique_denied == len(unique) - BUCKET_LIMIT
        and replay_consistent
        and all(item.get("request_id_echoed") is True for item in unique)
    )
    return {
        "name": case_name,
        "unique_request_count": len(unique),
        "unique_allowed": unique_allowed,
        "unique_denied": unique_denied,
        "replay_consistent": replay_consistent,
        "passed": passed,
    }


async def _run_http_cases(
    ready: list[dict[str, object]],
    run_id: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Exercise the canonical auth, recovery, chat and compatibility routes."""

    try:
        import httpx
    except ImportError:
        return [], {"blocked": "http_client_unavailable"}

    ports = [item.get("port") for item in ready]
    if any(type(port) is not int or not 1 <= port <= 65_535 for port in ports):
        return [], {"error": "invalid_api_port"}
    tenant_id = f"runtime-tenant-{run_id}"
    login_email = f"runtime-login-{run_id}@example.test"
    chat_email = f"runtime-chat-{run_id}@example.test"
    password = "password123"
    clients = (
        httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{ports[0]}",
            timeout=HTTP_REQUEST_TIMEOUT_SECONDS,
        ),
        httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{ports[1]}",
            timeout=HTTP_REQUEST_TIMEOUT_SECONDS,
        ),
    )
    try:
        # Each API process has its own session store. Prime one chat session
        # per replica before testing the shared chat rate-limit key.
        for index, client in enumerate(clients):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": chat_email, "password": password, "tenant_id": tenant_id},
                headers={"X-Request-ID": f"chat-bootstrap-{index}-{run_id}"},
            )
            if not 200 <= response.status_code < 300:
                return [], {"error": "chat_session_bootstrap_failed"}

        login_case = await _run_http_case(
            clients,
            "/api/v1/auth/login",
            {"email": login_email, "password": password, "tenant_id": tenant_id},
            run_id,
            "login",
        )
        recovery_email = f"runtime-recovery-{run_id}@example.test"
        recovery_case = await _run_http_case(
            clients,
            "/api/v1/auth/recovery",
            {"email": recovery_email, "tenant_id": tenant_id},
            run_id,
            "recovery",
        )
        chat_case = await _run_http_case(
            clients,
            "/api/v1/chat",
            {"message": "shared Redis rate-limit probe", "stream": False},
            run_id,
            "chat",
        )
        compatibility_case = await _run_http_case(
            clients,
            "/v1/chat/completions",
            {"model": "rick-professor", "messages": [{"role": "user", "content": "probe"}]},
            run_id,
            "compatibility",
            headers={"Authorization": f"Bearer compat-{run_id}"},
        )

        # Same route and email, different tenant: tenant B must not inherit
        # tenant A's exhausted recovery bucket.
        tenant_b = f"runtime-tenant-b-{run_id}"
        tenant_b_first = await _post_http(
            clients[0],
            "/api/v1/auth/recovery",
            {"email": recovery_email, "tenant_id": tenant_b},
            f"tenant-b-1-{run_id}",
        )
        tenant_b_replay = await _post_http(
            clients[1],
            "/api/v1/auth/recovery",
            {"email": recovery_email, "tenant_id": tenant_b},
            f"tenant-b-1-{run_id}",
        )
        tenant_isolation = {
            "allowed": tenant_b_first.get("allowed") is True and tenant_b_replay.get("allowed") is True,
            "replay_consistent": tenant_b_first.get("allowed") == tenant_b_replay.get("allowed"),
            "request_ids_echoed": tenant_b_first.get("request_id_echoed") is True and tenant_b_replay.get("request_id_echoed") is True,
        }
        cases = [login_case, recovery_case, chat_case, compatibility_case]
        return cases, {
            "http_boundary": True,
            "all_policy_cases_passed": all(case.get("passed") is True for case in cases),
            "replay_consistent": all(case.get("replay_consistent") is True for case in cases),
            "tenant_isolation": tenant_isolation,
        }
    finally:
        for client in clients:
            await client.aclose()


def _finish_process(process: Any) -> None:
    if getattr(process, "pid", None) is None:
        return
    process.join(PROCESS_JOIN_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(PROCESS_JOIN_SECONDS)


def _stop_processes(processes: list[Any], channels: list[Any], stop_events: list[Any]) -> None:
    for event in stop_events:
        event.set()
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
    production_safe = len(observations) == 2 and all(
        item.get("production_safe") is True for item in observations
    )
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


def _http_results(
    observations: list[dict[str, object]],
    cases: list[dict[str, object]],
    http_metrics: Mapping[str, object],
) -> tuple[list[GateResult], dict[str, object], bool]:
    """Derive release assertions from the real canonical API HTTP run."""

    case_names = {str(item.get("name")) for item in cases}
    expected_case_names = {"login", "recovery", "chat", "compatibility"}
    valid_cases = (
        len(cases) == len(expected_case_names)
        and case_names == expected_case_names
        and all(
            item.get("unique_request_count") == 4
            and item.get("unique_allowed") == BUCKET_LIMIT
            and item.get("unique_denied") == 4 - BUCKET_LIMIT
            and item.get("passed") is True
            for item in cases
        )
    )
    distinct_processes = len({item.get("pid") for item in observations}) == 2
    shared_namespace = (
        len(observations) == 2
        and all(isinstance(item.get("tenant_namespace"), str) for item in observations)
        and len({item.get("tenant_namespace") for item in observations}) == 1
    )
    http_boundary = (
        len(observations) == 2
        and all(item.get("http_boundary") is True for item in observations)
    )
    pttls = [item.get("bucket_pttl_ms") for item in observations]
    ttl_ok = all(type(value) is int and 0 < value <= API_RATE_WINDOW_MS for value in pttls)
    tenant_isolation = http_metrics.get("tenant_isolation")
    tenant_isolation_ok = (
        isinstance(tenant_isolation, Mapping)
        and tenant_isolation.get("allowed") is True
        and tenant_isolation.get("replay_consistent") is True
        and tenant_isolation.get("request_ids_echoed") is True
    )
    replay_ok = (
        valid_cases
        and http_metrics.get("replay_consistent") is True
        and tenant_isolation_ok
    )
    shared_ok = valid_cases and http_metrics.get("all_policy_cases_passed") is True
    production_safe = all(item.get("production_safe") is True for item in observations)
    metrics: dict[str, object] = {
        "replica_count": len(observations),
        "distinct_processes": distinct_processes,
        "http_api_boundary": http_boundary,
        "shared_tenant_namespace": shared_namespace,
        "policy_case_count": len(cases),
        "policy_cases": {
            str(item.get("name")): {
                "unique_request_count": item.get("unique_request_count"),
                "unique_allowed": item.get("unique_allowed"),
                "unique_denied": item.get("unique_denied"),
                "replay_consistent": item.get("replay_consistent") is True,
                "passed": item.get("passed") is True,
            }
            for item in cases
        },
        "shared_bucket_limit": BUCKET_LIMIT,
        "shared_bucket_cases_passed": shared_ok,
        "replay_consistent": replay_ok,
        "tenant_isolation": tenant_isolation_ok,
        "bucket_ttl_positive": ttl_ok,
        "bucket_pttl_ms": pttls if ttl_ok else [],
        "production_safe": production_safe,
    }
    results = [
        GateResult(
            "two-api-processes",
            "PASS" if distinct_processes else "FAIL",
            "two independent API server processes produced the observations"
            if distinct_processes
            else "HTTP observations did not come from two distinct API processes",
        ),
        GateResult(
            "http-api-boundary",
            "PASS" if http_boundary else "FAIL",
            "requests crossed the canonical apps/api HTTP boundary",
        ),
        GateResult(
            "tenant-namespace-isolation",
            "PASS" if shared_namespace and tenant_isolation_ok else "FAIL",
            "both API replicas shared one namespace and a different tenant received a separate bucket",
        ),
        GateResult(
            "shared-atomic-bucket",
            "PASS" if shared_ok else "FAIL",
            "login, recovery, chat and compatibility each consumed one shared bounded bucket",
        ),
        GateResult(
            "request-replay-idempotency",
            "PASS" if replay_ok else "FAIL",
            "the same request ID replayed through the other API replica retained its decision",
        ),
        GateResult(
            "RATE_LIMIT_MULTI_REPLICA_BYPASS_REJECTED",
            "PASS" if shared_ok and http_boundary else "FAIL",
            "a second API replica could not bypass any tested route policy",
        ),
        GateResult(
            "redis-bucket-ttl",
            "PASS" if ttl_ok else "FAIL",
            "the shared Redis bucket retained a bounded positive TTL after HTTP traffic",
        ),
        GateResult(
            "production-capability",
            "PASS" if production_safe else "PARTIAL",
            "both API replicas reported a TLS/authenticated Redis capability"
            if production_safe
            else "HTTP Redis semantics passed without a production-safe TLS capability",
        ),
    ]
    return results, metrics, production_safe


def _run_two_replicas(url: str, *, require_tls: bool, run_id: str) -> tuple[str, list[GateResult], dict[str, object], bool]:
    context = multiprocessing_module.get_context("spawn")
    processes: list[Any] = []
    channels: list[Any] = []
    stop_events: list[Any] = []
    replicas = ("api-a", "api-b")
    try:
        for replica in replicas:
            port = _free_loopback_port()
            stop_event = context.Event()
            parent, child = context.Pipe(duplex=False)
            process = context.Process(
                target=_replica_target,
                args=(url, run_id, replica, require_tls, port, stop_event, child),
                name=f"rick-runtime-{replica}",
            )
            processes.append(process)
            channels.append(parent)
            stop_events.append(stop_event)
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
                [GateResult("startup", "FAIL", "one or more canonical API replicas did not become ready")],
                {"replica_count": 2, "runtime_claim": False},
                False,
            )

        try:
            cases, http_metrics = asyncio.run(_run_http_cases(ready, run_id))
        except Exception:  # pragma: no cover - defensive parent boundary.
            cases, http_metrics = [], {"error": "http_case_runner_failed"}
        if not cases or http_metrics.get("error"):
            if http_metrics.get("blocked"):
                return (
                    "BLOCKED_EXTERNAL",
                    [GateResult("http-client", "BLOCKED_EXTERNAL", "HTTP client dependency is unavailable")],
                    {"replica_count": 2, "runtime_claim": False},
                    False,
                )
            return (
                "FAIL",
                [GateResult("http-boundary", "FAIL", "canonical API HTTP cases could not be completed")],
                {"replica_count": 2, "runtime_claim": False},
                False,
            )

        for event in stop_events:
            event.set()
        complete = [_receive(channel, WORKER_WAIT_SECONDS) for channel in channels]
        if any(item.get("kind") != "complete" for item in complete):
            return (
                "FAIL",
                [GateResult("completion", "FAIL", "one or more canonical API replicas failed after HTTP cases")],
                {"replica_count": 2, "runtime_claim": False},
                False,
            )
        observations = [
            {
                **ready_item,
                **complete_item,
            }
            for ready_item, complete_item in zip(ready, complete)
        ]
        results, metrics, production_safe = _http_results(observations, cases, http_metrics)
        status = "PASS" if all(item.result in {"PASS", "PARTIAL"} for item in results) else "FAIL"
        metrics["runtime_claim"] = status == "PASS"
        return status, results, metrics, production_safe
    finally:
        _stop_processes(processes, channels, stop_events)


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
