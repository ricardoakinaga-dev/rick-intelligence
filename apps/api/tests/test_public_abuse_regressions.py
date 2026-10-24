"""AUD12-A04/A05: costly search and public spray controls, hermetic only."""
from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from app import create_app
from apps.api.tests.support import login_as
import core.rate_limit as rate_limit
from core.rate_limit import InMemoryRateLimiter


@pytest.mark.parametrize("answer", [False, None, "false", 1])
def test_search_checks_async_limiter_before_retrieval(client, providers, monkeypatch, answer):
    login_as(client, "admin@example.com")
    monkeypatch.setenv("RICK_API_ROOT_RETRIEVAL", "1")
    calls = []
    retrieval_calls = []

    class Limiter:
        async def allow(self, key, *, limit, window_seconds, request_id):
            calls.append((key, limit, request_id))
            await asyncio.sleep(0)
            return answer

    class Retrieval:
        def retrieve(self, **kwargs):
            retrieval_calls.append(kwargs)
            return {"query": kwargs["query"], "evidence": []}

    client.app.state.providers.rate_limiter = Limiter()
    client.app.state.providers.retrieval = Retrieval()
    response = client.post("/api/v1/search", json={"query": "higiene"})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert response.headers["Retry-After"] == "60"
    assert calls and all(len(key) == 64 and request_id for key, _, request_id in calls)
    assert retrieval_calls == []


def test_search_limiter_failure_is_safe_and_does_not_run_retrieval(client, monkeypatch):
    login_as(client, "admin@example.com")
    monkeypatch.setenv("RICK_API_ROOT_RETRIEVAL", "1")
    calls = []

    class Unavailable:
        async def allow(self, *args, **kwargs):
            raise ConnectionError("synthetic-private-redis-detail")

    class Retrieval:
        def retrieve(self, **kwargs):
            calls.append(kwargs)
            return {"query": kwargs["query"], "evidence": []}

    client.app.state.providers.rate_limiter = Unavailable()
    client.app.state.providers.retrieval = Retrieval()
    response = client.post("/api/v1/search", json={"query": "higiene"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert "synthetic-private-redis-detail" not in response.text
    assert calls == []


@pytest.mark.parametrize("route", ["login", "recovery", "request-password-reset"])
@pytest.mark.parametrize("dimension", ["ip", "account", "tenant"])
def test_public_spray_has_independent_buckets(providers, route, dimension):
    # Explicit synthetic tenant budgets; no production/NAT numbers inferred.
    settings = replace(providers.settings, login_rate_limit_per_min=2, recovery_rate_limit_per_min=2,
                       login_tenant_rate_limit_per_min=2, recovery_tenant_rate_limit_per_min=2)
    providers.rate_limiter = InMemoryRateLimiter()
    responses = []
    for n in range(3):
        ip = "192.0.2.1" if dimension == "ip" else f"192.0.2.{n + 1}"
        email = "absent@example.test" if dimension == "account" else f"absent{n}@example.test"
        tenant = f"tenant{n}" if dimension == "ip" else "default"
        with TestClient(create_app(settings, providers), client=(ip, 42000), raise_server_exceptions=False) as client:
            payload = {"email": email, "tenant_id": tenant}
            if route == "login":
                payload["password"] = "incorrect"
            responses.append(client.post(f"/api/v1/auth/{route}", json=payload))
    first_status = 401 if route == "login" else 200
    assert [response.status_code for response in responses] == [first_status, first_status, 429]
    assert responses[-1].headers["Retry-After"] == "60"
    assert responses[-1].json()["error"]["code"] == "rate_limited"
    assert "absent" not in responses[-1].text


@pytest.mark.parametrize("route", ["login", "recovery", "request-password-reset", "search", "chat", "compat"])
def test_client_request_id_cannot_replay_a_rate_limit_allowance(providers, monkeypatch, route):
    settings = replace(providers.settings, login_rate_limit_per_min=1, recovery_rate_limit_per_min=1, chat_rate_limit_per_min=1,
                       compat_api_key="synthetic-test-compat-key")
    with TestClient(create_app(settings, providers), raise_server_exceptions=False) as client:
        if route in {"search", "chat"}:
            login_as(client, "admin@example.com")
        if route == "search":
            monkeypatch.setenv("RICK_API_ROOT_RETRIEVAL", "1")

            class Retrieval:
                def retrieve(self, **kwargs):
                    return {"query": kwargs["query"], "evidence": []}

            client.app.state.providers.retrieval = Retrieval()

        class ReplayAwareLimiter:
            # Faithful to the shared limiter's per-key request-id dedup port.
            def __init__(self):
                self.seen = {}
                self.counts = {}

            async def allow(self, key, *, limit, window_seconds, request_id):
                if (key, request_id) not in self.seen:
                    self.counts[key] = self.counts.get(key, 0) + 1
                    self.seen[key, request_id] = self.counts[key] <= limit
                return self.seen[key, request_id]

        client.app.state.providers.rate_limiter = ReplayAwareLimiter()
        headers = {"X-Request-ID": "client-chosen-repeated-id"}
        payload = {"query": "higiene"} if route == "search" else {"email": "absent@example.test", "tenant_id": "default"}
        if route == "login":
            payload["password"] = "incorrect"
        path = "/api/v1/search" if route == "search" else f"/api/v1/auth/{route}"
        if route == "chat":
            path, payload = "/api/v1/chat", {"message": "Synthetic hermetic question"}
        elif route == "compat":
            path, payload = "/v1/chat/completions", {"messages": [{"role": "user", "content": "Synthetic hermetic question"}]}
            headers["Authorization"] = "Bearer synthetic-test-compat-key"
        first = client.post(path, json=payload, headers=headers)
        second = client.post(path, json=payload, headers=headers)
        assert first.status_code == (401 if route == "login" else 200)
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "rate_limited"


def test_default_local_limiter_bounds_unrevisited_keys():
    limiter = InMemoryRateLimiter()
    outcomes = [limiter.check(f"synthetic-{n}", limit_per_min=1) for n in range(5000)]
    assert sum(outcomes) <= 4096
    assert len(limiter._events) <= 4096


def test_local_capacity_never_evicts_live_keys_to_reset_quota(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    limiter = InMemoryRateLimiter(max_keys=2, max_events=3)
    assert limiter.check("a", limit_per_min=2)
    assert limiter.check("b", limit_per_min=2)
    assert not limiter.check("c", limit_per_min=2)
    assert limiter.check("a", limit_per_min=2)
    assert not limiter.check("b", limit_per_min=2)
    assert not limiter.check("a", limit_per_min=2)
    assert len(limiter._events) == 2
    now[0] += 60
    assert limiter.check("c", limit_per_min=2)
    assert set(limiter._events) == {"c"}


def test_local_event_capacity_is_bounded_under_threads():
    limiter = InMemoryRateLimiter(max_keys=20, max_events=5)
    with ThreadPoolExecutor(max_workers=10) as executor:
        outcomes = list(executor.map(lambda _: limiter.check("a", limit_per_min=100), range(100)))
    assert sum(outcomes) == 5
    assert sum(len(events) for events in limiter._events.values()) == 5


@pytest.mark.parametrize("settings", [
    {"max_keys": 0}, {"max_events": 0}, {"max_keys": True},
    {"window_seconds": 0}, {"window_seconds": float("nan")},
])
def test_local_limiter_rejects_invalid_capacity(settings):
    with pytest.raises(ValueError):
        InMemoryRateLimiter(**settings)


def test_typed_scope_hashes_do_not_alias_or_expose_identity():
    key = rate_limit.rate_limit_key
    assert key("login:account", "a:b", "c") != key("login:account", "a", "b:c")
    assert key("login:account", None, "email") != key("login:account", "", "email")
    assert key("login:ip", "source") != key("recovery:ip", "source")
    assert len(key("login:account", "tenant", "synthetic@example.test")) == 64
    # Lone Unicode surrogates must not break the hashed public boundary.
    assert len(key("login:account", "tenant", "\ud800@example.test")) == 64


def test_local_event_capacity_reclaims_partial_expiry_without_resetting_live_window(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    limiter = InMemoryRateLimiter(max_keys=2, max_events=2)
    assert limiter.check("a", limit_per_min=2)
    now[0] += 1
    assert limiter.check("a", limit_per_min=2)
    now[0] += 59
    assert limiter.check("b", limit_per_min=2)
    assert sum(map(len, limiter._events.values())) == 2
    assert not limiter.check("a", limit_per_min=2)


@pytest.mark.parametrize("field", ["login_tenant_rate_limit_per_min", "recovery_tenant_rate_limit_per_min", "search_tenant_rate_limit_per_min"])
@pytest.mark.parametrize("value", [0, -1, True, "2", 100001])
def test_tenant_budgets_are_explicit_positive_typed_config(providers, field, value):
    with pytest.raises(ValueError, match="out of range"):
        replace(providers.settings, **{field: value}).validate()


def test_unratified_tenant_budget_is_not_silently_invented(providers):
    assert providers.settings.login_tenant_rate_limit_per_min is None
    assert providers.settings.recovery_tenant_rate_limit_per_min is None
    assert providers.settings.search_tenant_rate_limit_per_min is None


def test_explicit_search_tenant_budget_is_shared_across_actors(providers, monkeypatch):
    settings = replace(providers.settings, chat_rate_limit_per_min=2, search_tenant_rate_limit_per_min=1)
    monkeypatch.setenv("RICK_API_ROOT_RETRIEVAL", "1")
    calls = []

    class Retrieval:
        def retrieve(self, **kwargs):
            calls.append(kwargs)
            return {"query": kwargs["query"], "evidence": []}

    with TestClient(create_app(settings, providers), raise_server_exceptions=False) as client:
        client.app.state.providers.retrieval = Retrieval()
        login_as(client, "admin@example.com")
        assert client.post("/api/v1/search", json={"query": "higiene"}).status_code == 200
        login_as(client, "vet@example.com")
        limited = client.post("/api/v1/search", json={"query": "higiene"})
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "60"
        assert len(calls) == 1


@pytest.mark.parametrize("port", ["check", "allow"])
def test_sync_limiter_never_occupies_event_loop(port):
    entered, heartbeat, release = threading.Event(), threading.Event(), threading.Event()
    observed = []

    def blocking(*args, **kwargs):
        entered.set()
        if not release.wait(3):
            raise RuntimeError("bounded-test-cleanup-timeout")
        return True

    class Limiter:
        pass

    limiter = Limiter()
    setattr(limiter, port, blocking)

    async def probe():
        loop = asyncio.get_running_loop()

        def release_from_outside():
            try:
                if entered.wait(3):
                    loop.call_soon_threadsafe(heartbeat.set)
                    observed.append(heartbeat.wait(1))
            finally:
                release.set()

        helper = threading.Thread(target=release_from_outside)
        helper.start()
        try:
            assert await rate_limit.check_rate_limit_async(limiter, "scope-key", limit_per_min=1)
        finally:
            release.set()
            helper.join(4)
        assert not helper.is_alive()

    asyncio.run(probe())
    assert observed == [True], "loop heartbeat must progress before synchronous port is released"


def test_local_clock_is_serialized_with_acceptance(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: clock[0])
    limiter = InMemoryRateLimiter(max_keys=2, max_events=4)
    underlying = limiter._lock
    waiting, resume = threading.Event(), threading.Event()
    outcomes = []

    class Gate:
        def __enter__(self):
            if threading.current_thread().name == "clock-before-lock":
                waiting.set()
                assert resume.wait(3)
            return underlying.__enter__()

        def __exit__(self, *args):
            return underlying.__exit__(*args)

    limiter._lock = Gate()
    thread = threading.Thread(name="clock-before-lock", target=lambda: outcomes.append(limiter.check("a", limit_per_min=2)))
    thread.start()
    try:
        assert waiting.wait(3)
        clock[0] = 100.0
        assert limiter.check("a", limit_per_min=2)
    finally:
        resume.set()
        thread.join(4)
    assert not thread.is_alive() and outcomes == [True]
    clock[0] = 120.0
    assert not limiter.check("a", limit_per_min=2), "both accepted t=100 events are still live"
    assert list(limiter._events["a"]) == [100.0, 100.0]


@pytest.mark.parametrize("port", ["check", "allow"])
def test_port_body_typeerror_is_not_retried_after_consumption(port):
    calls = []

    def fail(*args, **kwargs):
        calls.append((args, kwargs))
        raise TypeError("synthetic-private-counter-error")

    class Limiter:
        pass

    limiter = Limiter()
    setattr(limiter, port, fail)
    with pytest.raises(TypeError, match="synthetic-private-counter-error"):
        asyncio.run(rate_limit.check_rate_limit_async(limiter, "scope-key", limit_per_min=1))
    assert len(calls) == 1


def test_async_adapter_preserves_legacy_keyword_only_allow():
    calls = []

    class Limiter:
        def allow(self, key, *, limit_per_min):
            calls.append((key, limit_per_min))
            return True

    assert asyncio.run(rate_limit.check_rate_limit_async(Limiter(), "scope-key", limit_per_min=2))
    assert calls == [("scope-key", 2)]


@pytest.mark.parametrize("family", ["login", "recovery", "chat"])
def test_lazy_initialization_lock_is_not_acquired_on_event_loop(providers, monkeypatch, family):
    from routes import auth, chat
    from starlette.requests import Request
    entered, heartbeat, release = threading.Event(), threading.Event(), threading.Event()
    observed = []
    providers.rate_limiter = None

    class Gate:
        def __enter__(self):
            entered.set()
            assert release.wait(3)

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(rate_limit, "_rate_limiter_init_lock", Gate())
    from types import SimpleNamespace
    from services.identity_offload import IdentityOffload
    runner = IdentityOffload()
    request = Request({"type": "http", "client": ("synthetic-host", 1),
                       "app": SimpleNamespace(state=SimpleNamespace(providers=providers, identity_offload=runner))})
    payload = auth.RecoveryRequest(email="synthetic@example.test", tenant_id="default")

    async def probe():
        loop = asyncio.get_running_loop()

        def release_from_outside():
            try:
                if entered.wait(3):
                    loop.call_soon_threadsafe(heartbeat.set)
                    observed.append(heartbeat.wait(1))
            finally:
                release.set()

        helper = threading.Thread(target=release_from_outside)
        helper.start()
        try:
            if family == "login":
                assert await auth._login_rate_allowed(providers, request, payload)
            elif family == "recovery":
                assert await auth._recovery_rate_allowed(providers, request, payload)
            else:
                assert await chat._rate_allowed(providers, "synthetic-scope")
        finally:
            release.set()
            helper.join(4)
            assert runner.shutdown(timeout=1)
        assert not helper.is_alive()

    asyncio.run(probe())
    assert observed == [True]


def test_chat_scope_segments_do_not_alias():
    from types import SimpleNamespace
    from routes.chat import _chat_rate_key
    assert _chat_rate_key(SimpleNamespace(tenant_id="a:b", user_id="c")) != _chat_rate_key(SimpleNamespace(tenant_id="a", user_id="b:c"))
