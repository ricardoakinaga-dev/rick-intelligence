"""AUD15 failure-first identity HTTP/scheduling contracts (synthetic, no services)."""
from __future__ import annotations

import asyncio
import threading
import time

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from rick_identity import OIDCIdentityProvider, OIDCSettings, OIDCVerifier


def oidc(resolver=None):
    membership = dict(subject="subject", user_id="user", tenant_id="tenant", workspace_id="workspace",
                      role="VETERINARIAN", status="active", membership_status="active", authorized_collection_ids=[])
    verifier = OIDCVerifier(OIDCSettings(issuer="https://issuer.test", audience="api", algorithms=("HS256",)),
                            key_resolver=lambda _: "synthetic-test-secret-at-least-32-bytes")
    provider = OIDCIdentityProvider(verifier, membership_resolver=resolver or (lambda *_: membership))
    token = jwt.encode(dict(sub="subject", iss="https://issuer.test", aud="api", exp=int(time.time())+600,
                            tenant_id="tenant"), "synthetic-test-secret-at-least-32-bytes", algorithm="HS256", headers={"kid":"key"})
    return provider, token


def test_oidc_logout_cannot_confirm_revocation_it_does_not_support(client, providers):
    providers.identity, token = oidc()
    client.app.state.providers.identity = providers.identity
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    result = client.post("/api/v1/auth/logout", headers=headers)
    assert result.status_code == 503
    assert "signed_out" not in result.text and "set-cookie" not in result.headers
    assert not any(e.get("status") == "completed" for e in providers.audit_sink.events)
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


@pytest.mark.parametrize("authority", ["membership", "key"])
def test_oidc_membership_outage_is_503_not_anonymous_or_cleanup(client, providers, authority):
    down = [True]
    healthy, token = oidc()
    membership = healthy._membership_resolver(None, None, None)
    def resolve(*_):
        if down[0] and authority == "membership":
            raise RuntimeError("private outage detail")
        return membership
    providers.identity, _ = oidc(resolve)
    if authority == "key":
        def resolve_key(_):
            if down[0]:
                raise RuntimeError("private outage detail")
            return "synthetic-test-secret-at-least-32-bytes"
        providers.identity.verifier._key_resolver = resolve_key
    client.app.state.providers.identity = providers.identity
    headers = {"Authorization": f"Bearer {token}"}
    for path, method in [("/api/v1/auth/me", client.get), ("/api/v1/auth/logout", client.post)]:
        result = method(path, headers=headers)
        assert result.status_code == 503
        assert "private outage detail" not in result.text
        assert "set-cookie" not in result.headers
    assert client.get("/api/v1/auth/me", headers={"Authorization":"Bearer invalid"}).status_code == 401
    down[0] = False
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("reject_at", [1, 2])
def test_reset_negative_limiter_means_zero_consume_or_kdf(client, providers, monkeypatch, failure, reject_at):
    calls = []
    class Limiter:
        def check(self, key, *, limit_per_min):
            calls.append((key, limit_per_min))
            if failure and len(calls) == reject_at:
                raise RuntimeError("private limiter failure")
            return len(calls) < reject_at
    providers.rate_limiter = client.app.state.providers.rate_limiter = Limiter()
    consumed = []
    monkeypatch.setattr(providers.identity, "consume_password_reset", lambda **kw: consumed.append(kw) or 0)
    result = client.post("/api/v1/auth/confirm-password-reset", json={"token":"private-token", "new_password":"new-password"})
    assert result.status_code == (503 if failure else 429)
    assert consumed == []
    assert calls and all("private-token" not in key and budget == providers.settings.recovery_rate_limit_per_min for key, budget in calls)


def test_reset_allowed_uses_independent_private_ip_and_token_buckets(client, providers, monkeypatch):
    keys = []
    class Limiter:
        def check(self, key, *, limit_per_min):
            keys.append((key, limit_per_min))
            return True
    providers.rate_limiter = client.app.state.providers.rate_limiter = Limiter()
    monkeypatch.setattr(providers.identity, "consume_password_reset", lambda **_: 1)
    result = client.post("/api/v1/auth/confirm-password-reset", json={"token":"private-token", "new_password":"new-password"})
    assert result.status_code == 200
    assert len(keys) == 2 and keys[0][0] != keys[1][0]
    assert all(len(key) == 64 and "private-token" not in key for key, _ in keys)


@pytest.mark.parametrize("operation", ["validate_token", "login", "issue_password_reset", "consume_password_reset"])
def test_slow_identity_lookup_does_not_occupy_asgi_loop(app, providers, monkeypatch, operation):
    original = getattr(providers.identity, operation)
    release = threading.Event()
    worker_threads = []
    async def exercise():
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        entered = asyncio.Event()
        def slow(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5), "identity fixture was not released"
            return original(*args, **kwargs)
        monkeypatch.setattr(providers.identity, operation, slow)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            if operation == "login":
                request = client.post("/api/v1/auth/login", json={"email":"admin@example.com", "password":"password123", "tenant_id":"default"})
            elif operation == "issue_password_reset":
                request = client.post("/api/v1/auth/recovery", json={"email":"admin@example.com", "tenant_id":"default"})
            elif operation == "consume_password_reset":
                request = client.post("/api/v1/auth/confirm-password-reset", json={"token":"invalid", "new_password":"new-password"})
            else:
                request = client.get("/api/v1/auth/me")
            task = asyncio.create_task(request)
            try:
                # Assert causal progress while the identity worker remains
                # blocked. Runner admission time is not an event-loop SLO.
                # Deadman timeouts bound broken fixtures; they are not latency
                # acceptance thresholds or retries of a failed observation.
                await asyncio.wait_for(entered.wait(), timeout=5)
                independent = await asyncio.wait_for(client.get("/health/live"), timeout=5)
                assert independent.status_code == 200
                assert worker_threads and all(t != loop_thread for t in worker_threads)
                assert not task.done() and not release.is_set()
            finally:
                release.set()
                await asyncio.wait_for(task, timeout=5)
    asyncio.run(exercise())


def test_delegated_identity_lookup_happens_in_admitted_worker(app, providers):
    native = providers.identity
    token = native.login(email="admin@example.com", password="password123", tenant_id="default",
                         ip=None, user_agent=None)["session_token"]
    entered, release = threading.Event(), threading.Event()
    lookup_threads = []
    class DelegatedIdentity:
        def __getattr__(self, name):
            if name == "validate_token":
                lookup_threads.append(threading.get_ident())
                entered.set()
                assert release.wait(5)
            return getattr(native, name)
    app.state.providers.identity = DelegatedIdentity()
    async def exercise():
        loop_thread = threading.get_ident()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            task = asyncio.create_task(client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}))
            try:
                assert await asyncio.to_thread(entered.wait, 5), "supported delegation must not be rejected"
                health = await asyncio.wait_for(client.get("/health/live"), timeout=5)
                assert health.status_code == 200
                assert not task.done() and not release.is_set()
            finally:
                release.set()
                response = await task
                assert await asyncio.to_thread(app.state.identity_offload.shutdown, timeout=2)
            assert response.status_code == 200
            assert lookup_threads and all(thread != loop_thread for thread in lookup_threads)
    asyncio.run(exercise())


@pytest.mark.parametrize("lookup_kind", ["getattr", "descriptor"])
@pytest.mark.parametrize("timeout_ms", [30, 1000])
def test_reset_hot_method_lookup_is_admitted_and_cannot_consume_after_deadline(app, lookup_kind, timeout_ms):
    from dataclasses import replace
    entered = threading.Event()
    release = threading.Event()
    lookup_threads, lookup_active, consumed = [], [], []
    runner = app.state.identity_offload
    def consume(**kwargs):
        consumed.append(kwargs)
        return 2
    def hot_lookup():
        lookup_threads.append(threading.get_ident())
        lookup_active.append(runner._active)
        entered.set()
        assert release.wait(5), "hot getter was not released"
        return consume
    class DynamicIdentity:
        def __getattr__(self, name):
            if name == "consume_password_reset":
                return hot_lookup()
            raise AttributeError(name)
    class DescriptorIdentity:
        @property
        def consume_password_reset(self):
            return hot_lookup()
    app.state.providers.identity = DynamicIdentity() if lookup_kind == "getattr" else DescriptorIdentity()
    app.state.providers.settings = replace(app.state.providers.settings, provider_timeout_ms=timeout_ms)
    async def exercise():
        loop_thread = threading.get_ident()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            task = asyncio.create_task(client.post("/api/v1/auth/confirm-password-reset",
                json={"token":"private-reset-token", "new_password":"new-password"}))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                health = await asyncio.wait_for(client.get("/health/live"), timeout=5)
                assert health.status_code == 200 and not release.is_set()
                assert lookup_threads and all(thread != loop_thread for thread in lookup_threads)
                if timeout_ms != 30:
                    assert not task.done()
                    release.set()
                response = await asyncio.wait_for(task, timeout=5)
                active_after_response = runner._active
            finally:
                release.set()
                await asyncio.wait_for(task, timeout=5)
                assert await asyncio.to_thread(runner.shutdown, timeout=2)
            assert entered.is_set()
            assert lookup_threads and all(thread != loop_thread for thread in lookup_threads)
            assert lookup_active == [1], "hot method resolution must hold an admission slot"
            if timeout_ms == 30:
                assert response.status_code == 503
                assert active_after_response == 1, "timed-out lookup keeps its slot until real completion"
                assert consumed == [], "a getter returning after deadline must never start consume/KDF"
            else:
                assert response.status_code == 200
                assert response.json() == {"status":"reset", "revoked_sessions":2}
                assert consumed == [{"token":"private-reset-token", "new_password":"new-password"}]
    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["unsupported", "invalid", "async_unsupported"])
def test_reset_lookup_fix_preserves_invalid_and_unsupported_contracts(client, mode):
    async_body_calls = []
    if mode == "unsupported":
        client.app.state.providers.identity = object()
    elif mode == "async_unsupported":
        class AsyncIdentity:
            async def consume_password_reset(self, **kwargs):
                async_body_calls.append(kwargs)
                return 1
        client.app.state.providers.identity = AsyncIdentity()
    response = client.post("/api/v1/auth/confirm-password-reset",
        json={"token":"private-invalid-token", "new_password":"new-password"})
    assert response.status_code == (503 if mode == "async_unsupported" else 400)
    assert response.json()["error"]["code"] == ("result_indeterminate" if mode == "async_unsupported" else "validation_error")
    assert "private-invalid-token" not in response.text
    assert async_body_calls == []


def test_reset_denied_quota_does_not_even_resolve_hot_consume(client):
    lookups = []
    class Identity:
        @property
        def consume_password_reset(self):
            lookups.append(True)
            raise AssertionError("quota denied: provider lookup must not start")
    class Limiter:
        def check(self, key, *, limit_per_min):
            return False
    client.app.state.providers.identity = Identity()
    client.app.state.providers.rate_limiter = Limiter()
    response = client.post("/api/v1/auth/confirm-password-reset",
        json={"token":"private-invalid-token", "new_password":"new-password"})
    assert response.status_code == 429
    assert lookups == []


def test_reset_result_conversion_stays_inside_admitted_worker(app):
    from types import SimpleNamespace
    conversion_threads = []
    class Count:
        def __int__(self):
            conversion_threads.append(threading.get_ident())
            return 3
    app.state.providers.identity = SimpleNamespace(consume_password_reset=lambda **_: Count())
    async def exercise():
        loop_thread = threading.get_ident()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/auth/confirm-password-reset",
                json={"token":"private-reset-token", "new_password":"new-password"})
        assert response.status_code == 200 and response.json()["revoked_sessions"] == 3
        assert conversion_threads and all(thread != loop_thread for thread in conversion_threads)
        assert await asyncio.to_thread(app.state.identity_offload.shutdown, timeout=2)
    asyncio.run(exercise())


@pytest.mark.parametrize("abandon", ["timeout", "cancel"])
def test_offload_has_no_queue_and_retains_abandoned_work_until_shutdown(abandon):
    from core.errors import ApiError
    from services.identity_offload import IdentityOffload
    from contextvars import ContextVar
    runner = IdentityOffload(capacity=1)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    context = ContextVar("aud15_context", default=None)
    seen = []
    def work():
        entered.set()
        try:
            release.wait(2)
            seen.append(context.get())
        finally:
            finished.set()
    async def exercise():
        context.set("tenant-scoped-request")
        task = asyncio.create_task(runner.run(work, timeout=0.05 if abandon == "timeout" else 1))
        while not entered.is_set():
            await asyncio.sleep(0)
        if abandon == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(ApiError):
                await task
        with pytest.raises(ApiError):
            await runner.run(lambda: seen.append("queued"), timeout=1)
        assert runner.shutdown(timeout=0) is False
        release.set()
        assert await asyncio.to_thread(runner.shutdown, timeout=1) is True
        assert finished.is_set() and seen == ["tenant-scoped-request"]
        with pytest.raises(ApiError):
            await runner.run(lambda: None, timeout=1)
    try:
        asyncio.run(exercise())
    finally:
        release.set()
        assert runner.shutdown(timeout=2)


def test_invalid_postgres_reset_claim_does_not_hash(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from core.errors import ApiError
    from services.postgres_identity import PostgresIdentityProvider
    facade = PostgresIdentityProvider(lambda: None)
    facade._recovery_transaction = lambda: nullcontext(object())
    facade._recovery = SimpleNamespace(consume=lambda *_, **__: None)
    hashed = []
    monkeypatch.setattr("services.postgres_identity.hash_password", lambda value: hashed.append(value) or "hash")
    with pytest.raises(ApiError):
        facade.consume_password_reset(token="invalid", new_password="new-password")
    assert hashed == []


def test_postgres_reset_kdf_failure_rolls_back_claim_and_retry_is_single_use(monkeypatch):
    from types import SimpleNamespace
    from core.errors import ApiError
    from services.postgres_identity import PostgresIdentityProvider
    events = []
    class Connection:
        claimed = False
        consumed = False
        def commit(self):
            self.consumed = self.claimed
            events.append("commit")
        def rollback(self):
            self.claimed = self.consumed
            events.append("rollback")
        def close(self):
            pass
    connection = Connection()
    facade = PostgresIdentityProvider(lambda: connection)
    def claim(*_, **kwargs):
        assert kwargs["connection"] is connection
        events.append("claim")
        if connection.claimed:
            return None
        connection.claimed = True
        return dict(user_id="user", tenant_id="tenant", workspace_id="workspace")
    facade._recovery = SimpleNamespace(consume=claim)
    facade._users = SimpleNamespace(lock_user_for_update=lambda *_, **__: True,
        get_by_id_for_tenant_workspace_for_update=lambda *_, **__: {"status":"active", "membership_status":"active"},
        update_password_credentials=lambda **_: events.append("update") or True)
    facade._sessions = SimpleNamespace(revoke_user=lambda *_, **__: events.append("revoke") or 1)
    def failing_hash(_):
        events.append("hash-failure")
        raise RuntimeError("synthetic KDF failure")
    monkeypatch.setattr("services.postgres_identity.hash_password", failing_hash)
    with pytest.raises(ApiError):
        facade.consume_password_reset(token="valid", new_password="new-password")
    assert events == ["claim", "hash-failure", "rollback"] and not connection.claimed
    events.clear()
    monkeypatch.setattr("services.postgres_identity.hash_password", lambda _: events.append("hash") or "hash")
    assert facade.consume_password_reset(token="valid", new_password="new-password") == 1
    assert events == ["claim", "hash", "update", "revoke", "commit"]
    events.clear()
    with pytest.raises(ApiError):
        facade.consume_password_reset(token="valid", new_password="new-password")
    assert events == ["claim", "rollback"]


def test_noop_identity_adapter_cannot_acquire_logout_completion(client, providers, monkeypatch):
    from apps.api.tests.support import login_as
    login_as(client, "admin@example.com")
    monkeypatch.setattr(providers.identity, "logout", lambda _: None)
    result = client.post("/api/v1/auth/logout")
    assert result.status_code == 503 and "set-cookie" not in result.headers
    assert result.json()["error"]["code"] == "result_indeterminate"
    assert not any(event.get("status") == "completed" for event in providers.audit_sink.events)
    assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize("error", [RuntimeError, TimeoutError])
def test_logout_adapter_failure_has_no_completion_or_cookie(client, providers, monkeypatch, error):
    from apps.api.tests.support import login_as
    login_as(client, "admin@example.com")
    def failed(_):
        raise error("private adapter detail")
    monkeypatch.setattr(providers.identity, "logout", failed)
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 503 and "set-cookie" not in response.headers
    assert response.json()["error"]["code"] == "result_indeterminate"
    assert "private adapter detail" not in response.text
    assert not any(event.get("status") == "completed" for event in providers.audit_sink.events)


def test_late_logout_revocation_does_not_emit_completion(client, providers, monkeypatch):
    from apps.api.tests.support import login_as
    login_as(client, "admin@example.com")
    release = threading.Event()
    finished = threading.Event()
    original = providers.identity.logout
    def slow(token):
        try:
            release.wait(2)
            original(token)
        finally:
            finished.set()
    monkeypatch.setattr(providers.identity, "logout", slow)
    from dataclasses import replace
    client.app.state.providers.settings = replace(client.app.state.providers.settings, provider_timeout_ms=30)
    try:
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 503 and "set-cookie" not in response.headers
        assert response.json()["error"]["code"] == "result_indeterminate"
    finally:
        release.set()
        assert finished.wait(2)
        assert client.app.state.identity_offload.shutdown(timeout=2)
    assert not any(event.get("status") == "completed" for event in providers.audit_sink.events)


@pytest.mark.parametrize("operation", ["confirm", "login", "recovery"])
@pytest.mark.parametrize("blockage", ["sync_port", "lazy_initialization"])
def test_auth_quota_deadline_and_admission_do_not_starve_shared_pool(app, providers, operation, blockage):
    from dataclasses import replace
    release = threading.Event()
    class BlockingLimiter:
        def check(self, key, *, limit_per_min):
            assert release.wait(2)
            return True
    app.state.providers.rate_limiter = BlockingLimiter()
    init_lock = None
    if blockage == "lazy_initialization":
        from core.rate_limit import _rate_limiter_init_lock
        init_lock = _rate_limiter_init_lock
        init_lock.acquire()
        app.state.providers.rate_limiter = None
    app.state.providers.settings = replace(app.state.providers.settings, provider_timeout_ms=30)
    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            if operation == "confirm":
                path, payload = "/api/v1/auth/confirm-password-reset", {"token":"invalid", "new_password":"new-password"}
            elif operation == "login":
                path, payload = "/api/v1/auth/login", {"email":"admin@example.com", "password":"password123", "tenant_id":"default"}
            else:
                path, payload = "/api/v1/auth/recovery", {"email":"admin@example.com", "tenant_id":"default"}
            tasks = [asyncio.create_task(client.post(path, json=payload)) for _ in range(42)]
            health = asyncio.create_task(client.get("/health/live"))
            try:
                await asyncio.wait([*tasks, health], timeout=5)
                timely = all(task.done() for task in tasks)
                independent = health.done()
                statuses = [task.result().status_code for task in tasks if task.done()]
                assert not release.is_set()
                assert independent and health.result().status_code == 200
            finally:
                release.set()
                if init_lock is not None:
                    init_lock.release()
                await asyncio.gather(*tasks, health)
                assert await asyncio.to_thread(app.state.identity_offload.shutdown, timeout=2)
            assert independent, "blocked quota must not exhaust the shared Starlette pool"
            assert timely and statuses == [503] * 42, "quota admission/deadline must bound every public request"
    asyncio.run(exercise())


def test_async_quota_resistant_cancellation_retains_admission_without_extending_deadline():
    from core.errors import ApiError
    from core.rate_limit import check_rate_limit_async
    from services.identity_offload import IdentityOffload
    runner = IdentityOffload(capacity=1)
    async def exercise():
        release, finished, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Limiter:
            async def check(self, key, *, limit_per_min):
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await release.wait()  # an external port may suppress cancel
                finally:
                    finished.set()
                return True
        task = asyncio.create_task(check_rate_limit_async(Limiter(), "scope", limit_per_min=1,
                                        offload=runner, timeout_seconds=0.03))
        done, _ = await asyncio.wait({task}, timeout=5)
        if task not in done:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            pytest.fail("caller waited for a port that suppressed cancellation")
        with pytest.raises(ApiError):
            task.result()
        assert not release.is_set() and not finished.is_set()
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        assert runner.shutdown(timeout=0) is False
        with pytest.raises(ApiError):
            await runner.run(lambda: None, timeout=1)
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=1)
        assert await asyncio.to_thread(runner.shutdown, timeout=1)
    asyncio.run(exercise())


def test_logout_completion_must_not_persist_after_http_timeout(client, providers, monkeypatch):
    """B01 regression: a late non-terminal effect write is not a completion.

    The HTTP coroutine may abandon while the offload worker is inside the sink.
    The contract forbids a terminal ``completed`` write after that abandon; a
    late ``effect_applied`` record is allowed and will be reconciled.
    """
    from dataclasses import replace
    from apps.api.tests.support import login_as
    login_as(client, "admin@example.com")
    entered, release, persisted = threading.Event(), threading.Event(), threading.Event()
    original = providers.audit_sink.emit
    def delayed_effect(event):
        if event.get("action") == "auth.logout" and event.get("status") == "effect_applied":
            entered.set()
            assert release.wait(2)
            result = original(event)
            persisted.set()
            return result
        return original(event)
    monkeypatch.setattr(providers.audit_sink, "emit", delayed_effect)
    client.app.state.providers.settings = replace(client.app.state.providers.settings, provider_timeout_ms=30)
    try:
        response = client.post("/api/v1/auth/logout")
        assert entered.is_set()
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "result_indeterminate"
        assert not any(event.get("status") == "completed" for event in providers.audit_sink.events)
    finally:
        # Release only after the 503 was returned, then fully drain the worker;
        # the final assertion observes the real sink side effect, not a race.
        release.set()
        assert client.app.state.identity_offload.shutdown(timeout=2)
    assert persisted.is_set()
    assert any(event.get("status") == "effect_applied" for event in providers.audit_sink.events)
    assert not any(event.get("status") in {"completed", "acknowledged"} for event in providers.audit_sink.events)


def test_shutdown_does_not_close_stores_behind_pending_identity(monkeypatch):
    from types import SimpleNamespace
    from app import _shutdown_owned_resources
    from services.identity_offload import IdentityOffload
    monkeypatch.setattr("app.APP_LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS", 0.02)
    runner = IdentityOffload(capacity=1)
    entered, release = threading.Event(), threading.Event()
    closed = []
    application = SimpleNamespace(state=SimpleNamespace(identity_offload=runner,
        owned_resources=(SimpleNamespace(close=lambda: closed.append(True)),)))
    def slow():
        entered.set()
        release.wait(2)
    async def exercise():
        task = asyncio.create_task(runner.run(slow, timeout=1))
        while not entered.is_set():
            await asyncio.sleep(0)
        await _shutdown_owned_resources(application)
        assert not application.state.lifecycle_shutdown_complete and closed == []
        release.set()
        await task
        await _shutdown_owned_resources(application)
        assert application.state.lifecycle_shutdown_complete and closed == [True]
    try:
        asyncio.run(exercise())
    finally:
        release.set()
        assert runner.shutdown(timeout=2)


def test_reset_single_use_race_and_expiration(providers):
    from concurrent.futures import ThreadPoolExecutor
    from core.errors import ApiError
    provider = providers.identity
    token = provider.issue_password_reset(email="admin@example.com", tenant_id="default")
    def consume():
        try:
            provider.consume_password_reset(token=token, new_password="new-password")
            return "reset"
        except ApiError:
            return "invalid"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: consume(), range(2))) == ["invalid", "reset"]
    assert consume() == "invalid"
    expired = provider.issue_password_reset(email="admin@example.com", tenant_id="default")
    import hashlib
    key = hashlib.sha256(expired.encode()).hexdigest()
    user, _ = provider._reset_tokens[key]
    provider._reset_tokens[key] = user, 0
    with pytest.raises(ApiError):
        provider.consume_password_reset(token=expired, new_password="new-password")


def test_reset_effect_is_audited_once_with_scope(client, providers, monkeypatch):
    from services.identity_results import ResetEffect
    before = len(providers.audit_sink.events)
    monkeypatch.setattr(
        providers.identity,
        "consume_password_reset",
        lambda **_: ResetEffect(2, user_id="user-1", tenant_id="tenant-1", workspace_id="workspace-1"),
    )
    response = client.post(
        "/api/v1/auth/confirm-password-reset",
        json={"token": "private-reset-token", "new_password": "new-password"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "reset", "revoked_sessions": 2}
    events = providers.audit_sink.events[before:]
    assert len(events) == 1
    assert events[0]["action"] == "auth.reset_effect"
    assert events[0]["status"] == "effect_applied"
    assert events[0]["tenant_id"] == "tenant-1"
    assert events[0]["user_id"] == "user-1"
    assert events[0]["workspace_id"] == "workspace-1"


def test_reset_effect_audit_failure_is_indeterminate(client, providers, monkeypatch):
    from services.identity_results import ResetEffect
    monkeypatch.setattr(
        providers.identity,
        "consume_password_reset",
        lambda **_: ResetEffect(1, user_id="user-1", tenant_id="tenant-1", workspace_id="workspace-1"),
    )
    monkeypatch.setattr(providers.audit_sink, "emit", lambda _event: False)
    response = client.post(
        "/api/v1/auth/confirm-password-reset",
        json={"token": "private-reset-token", "new_password": "new-password"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "result_indeterminate"
    assert "private-reset-token" not in response.text


def test_reset_writes_durable_operation_and_acknowledges(client, providers, monkeypatch):
    from services.identity_results import ResetEffect
    operations = type("Ops", (), {})()
    operations.begun, operations.effects, operations.acked = [], [], []
    operations.begin = lambda **kw: operations.begun.append(kw)
    operations.mark_effect = lambda op, **kw: (operations.effects.append((op, kw)) or True)
    operations.acknowledge = lambda op: (operations.acked.append(op) or True)
    operations.fail = lambda op, code: True
    providers.audit_operations = client.app.state.providers.audit_operations = operations

    def consume(token, new_password):
        return ResetEffect(1, user_id="user-1", tenant_id="tenant-1", workspace_id="workspace-1")

    monkeypatch.setattr(providers.identity, "consume_password_reset", consume)
    response = client.post(
        "/api/v1/auth/confirm-password-reset",
        json={"token": "private-reset-token", "new_password": "new-password"},
    )
    assert response.status_code == 200
    assert operations.begun and operations.begun[0]["action"] == "auth.reset_effect"
    assert operations.effects and operations.acked
    assert operations.acked[0] == operations.effects[0][0]
