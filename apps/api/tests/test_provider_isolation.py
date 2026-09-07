"""Synthetic actual-HTTP isolation probes; no external accounts or services."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Event
from types import SimpleNamespace
import asyncio

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import create_app
from conftest import make_settings, login_as
from dependencies.services import Providers, get_providers, get_settings
from services.audit import InMemoryAuditSink
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider


def application(label):
    settings = make_settings(session_cookie_name="session_" + label, compat_api_key="synthetic-" + label)
    providers = Providers(
        settings=settings, identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(), audit_sink=InMemoryAuditSink(),
        health_checks={label: lambda: {"ok": label == "b", "required": True}},
        chat_history=SimpleNamespace(list_history=lambda **_: [{"marker": label}]),
    )
    return create_app(settings, providers)


@pytest.fixture
def pair():
    with ExitStack() as stack:
        a = application("a")
        ca = stack.enter_context(TestClient(a))
        login_as(ca, "vet@example.com")
        b = application("b")
        cb = stack.enter_context(TestClient(b))
        login_as(cb, "admin@example.com")
        yield a, ca, b, cb


def foreign_cookie(ca, cb):
    ca.cookies.clear()
    for cookie in cb.cookies.jar:
        ca.cookies.set(cookie.name, cookie.value)


def test_own_session_survives_other_application_creation(pair):
    _, ca, _, _ = pair
    response = ca.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "vet@example.com"


def test_foreign_cookie_cannot_authenticate_another_application(pair):
    _, ca, _, cb = pair
    foreign_cookie(ca, cb)
    assert ca.get("/api/v1/auth/me").status_code == 401


def test_logout_cannot_revoke_a_foreign_application_session(pair):
    _, ca, _, cb = pair
    foreign_cookie(ca, cb)
    assert ca.post("/api/v1/auth/logout").status_code == 200
    assert cb.get("/api/v1/auth/me").status_code == 200


def test_login_cookie_configuration_stays_app_local(pair):
    _, ca, _, _ = pair
    response = login_as(ca, "vet@example.com")
    cookie_names = set(response.cookies.keys())
    assert "session_a" in cookie_names
    assert "session_b" not in cookie_names


def test_login_audit_stays_app_local(pair):
    a, ca, b, _ = pair
    before_a = len(a.state.providers.audit_sink.events)
    before_b = len(b.state.providers.audit_sink.events)
    login_as(ca, "vet@example.com")
    assert len(a.state.providers.audit_sink.events) == before_a + 1
    assert len(b.state.providers.audit_sink.events) == before_b


@pytest.mark.parametrize("key, expected", [("synthetic-a", 200), ("synthetic-b", 401)])
def test_compatibility_key_configuration_stays_app_local(pair, key, expected):
    _, ca, _, _ = pair
    assert ca.get("/v1/models", headers={"x-api-key": key}).status_code == expected


def test_readiness_stays_app_local(pair):
    _, ca, _, cb = pair
    response = ca.get("/health/ready")
    assert response.status_code == 503
    assert [check["name"] for check in response.json()["checks"]] == ["a"]
    assert cb.get("/health/ready").status_code == 200


def test_construction_between_authentication_and_data_access_cannot_switch_store():
    a = application("a")
    with TestClient(a) as ca:
        login_as(ca, "vet@example.com")
        entered, release = Event(), Event()
        validate = a.state.providers.identity.validate_token

        def held_validation(token):
            snapshot = validate(token)
            entered.set()
            assert release.wait(5), "probe release deadline"
            return snapshot

        a.state.providers.identity.validate_token = held_validation
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(ca.get, "/api/v1/history")
            try:
                assert entered.wait(5), "authentication did not start"
                application("b")
            finally:
                release.set()
            response = pending.result(timeout=5)
        assert response.status_code == 200
        assert response.json()["items"] == [{"marker": "a"}]


def test_reusing_injected_container_does_not_reconfigure_an_existing_app():
    original_settings = make_settings(compat_api_key="synthetic-original")
    injected = Providers(settings=original_settings)
    a = create_app(make_settings(compat_api_key="synthetic-a"), injected)
    b = create_app(make_settings(compat_api_key="synthetic-b"), injected)
    with TestClient(a) as ca, TestClient(b) as cb:
        assert ca.get("/v1/models", headers={"x-api-key": "synthetic-a"}).status_code == 200
        assert cb.get("/v1/models", headers={"x-api-key": "synthetic-b"}).status_code == 200
    assert injected.settings is original_settings
    assert a.state.providers is not b.state.providers


def test_each_app_owns_its_health_registration_mapping():
    settings = make_settings()
    injected = Providers(settings=settings, health_checks={"original": lambda: True})
    a, b = create_app(settings, injected), create_app(settings, injected)
    b.state.providers.health_checks["only-b"] = lambda: False
    assert "only-b" not in a.state.providers.health_checks
    assert "only-b" not in injected.health_checks


@pytest.mark.parametrize("attribute", ["runtime_checks", "readiness_checks"])
def test_integrator_registration_maps_are_preserved_but_app_owned(attribute):
    settings = make_settings()
    callback = lambda: True
    injected = Providers(settings=settings, identity=InMemoryIdentityProvider())
    setattr(injected, attribute, {"original": callback})
    a, b = create_app(settings, injected), create_app(settings, injected)
    assert a.state.providers.identity is injected.identity  # explicit service injection remains intact
    assert getattr(a.state.providers, attribute)["original"] is callback
    getattr(b.state.providers, attribute)["only-b"] = lambda: False
    assert "only-b" not in getattr(a.state.providers, attribute)
    assert "only-b" not in getattr(injected, attribute)


def test_accessor_has_no_fallback_to_another_application():
    a = application("a")
    request = Request({"type": "http", "app": a})
    application("b")
    assert get_providers(request) is a.state.providers
    assert get_settings(request) is a.state.settings
    with pytest.raises(RuntimeError, match="no configured providers"):
        get_providers(Request({"type": "http", "app": FastAPI()}))


def test_mounted_apps_resolve_the_effective_child_application():
    root, a, b = FastAPI(), application("a"), application("b")
    root.mount("/a", a)
    root.mount("/b", b)
    with TestClient(root) as client:
        for prefix, cookie_name in [("/a", "session_a"), ("/b", "session_b")]:
            response = client.post(prefix + "/api/v1/auth/login", json={
                "email": "vet@example.com", "password": "password123", "tenant_id": "default",
            })
            assert response.status_code == 200
            assert set(response.cookies.keys()) == {cookie_name}
            assert client.get(prefix + "/api/v1/auth/me").status_code == 200
        assert client.get("/a/health/ready").status_code == 503
        assert client.get("/b/health/ready").status_code == 200


def test_concurrent_async_readiness_requests_keep_their_own_checks():
    async def scenario():
        a, b = application("a"), application("b")
        entered, release = [], asyncio.Event()

        def register(app, label):
            async def check():
                entered.append(label)
                if len(entered) == 2:
                    release.set()
                await asyncio.wait_for(release.wait(), .5)
                return {"ok": label == "b", "required": True}
            app.state.providers.health_checks = {label: check}

        register(a, "a")
        register(b, "b")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=a), base_url="http://a.test") as ca:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=b), base_url="http://b.test") as cb:
                ra, rb = await asyncio.wait_for(asyncio.gather(ca.get("/health/ready"), cb.get("/health/ready")), 1)
        assert sorted(entered) == ["a", "b"]
        assert (ra.status_code, rb.status_code) == (503, 200)
        assert [item["name"] for item in ra.json()["checks"]] == ["a"]
        assert [item["name"] for item in rb.json()["checks"]] == ["b"]

    asyncio.run(scenario())
