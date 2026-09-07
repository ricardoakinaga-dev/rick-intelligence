"""Native server-error responses share the actual application's observer."""
import asyncio

import pytest
from fastapi import FastAPI, Request
from starlette.requests import ClientDisconnect

from app import create_app
from conftest import make_settings
from test_transport_observation import exercise, total


def assert_failure_once(app):
    assert total(app.state.telemetry, "api.http.errors") == 1
    assert total(app.state.telemetry, "api.http.disconnects") == 0
    assert app.state.telemetry.snapshot()["slo"]["observations"] == 1


@pytest.mark.parametrize("fail_at", ["http.response.start", "http.response.body"])
def test_original_failure_survives_outer_500_transport_failure(fail_at):
    app = create_app(make_settings())
    original = ValueError("private original failure")
    attempts = []

    async def endpoint():
        raise original

    async def send(message):
        attempts.append(message)
        if message["type"] == fail_at:
            raise BrokenPipeError("closed")

    app.add_api_route("/probe", endpoint)
    with pytest.raises(ValueError) as caught:
        asyncio.run(exercise(app, sender=send))
    assert caught.value is original
    assert attempts[-1]["type"] == fail_at
    assert_failure_once(app)


@pytest.mark.parametrize("mixed", [False, True])
def test_observed_receive_disconnect_suppresses_outer_500_sends(mixed):
    app = create_app(make_settings())
    original = ValueError("real application failure")
    if mixed:
        original = ExceptionGroup("mixed", [ClientDisconnect(), original])
    attempts = []

    async def endpoint(request: Request):
        await request.receive()
        raise original

    async def send(message):
        attempts.append(message)

    app.add_api_route("/probe", endpoint)
    with pytest.raises(type(original)) as caught:
        asyncio.run(exercise(app, disconnected=True, sender=send))
    assert caught.value is original
    assert attempts == []
    assert_failure_once(app)


@pytest.mark.parametrize("secondary", [RuntimeError("send bug"),
    ExceptionGroup("mixed send failure", [BrokenPipeError("closed"), ValueError("send bug")])])
def test_nontransport_secondary_failure_retains_both_errors(secondary):
    app = create_app(make_settings())
    original = ValueError("original")

    async def endpoint():
        raise original

    async def send(message):
        raise secondary

    app.add_api_route("/probe", endpoint)
    with pytest.raises(BaseExceptionGroup) as caught:
        asyncio.run(exercise(app, sender=send))
    assert caught.value.exceptions == (original, secondary)
    assert_failure_once(app)


@pytest.mark.parametrize("grouped", [False, True])
def test_observed_client_disconnect_has_no_synthetic_500(grouped):
    app = create_app(make_settings())

    async def endpoint(request: Request):
        try:
            await request.body()
        except ClientDisconnect as exc:
            if grouped:
                raise ExceptionGroup("transport only", [exc])
            raise

    app.add_api_route("/probe", endpoint, methods=["POST"])
    assert asyncio.run(exercise(app, method="POST", disconnected=True)) == []
    assert total(app.state.telemetry, "api.http.errors") == 0
    assert total(app.state.telemetry, "api.http.disconnects") == 1
    assert app.state.telemetry.snapshot()["slo"]["observations"] == 0


def test_app_preserves_fastapi_and_wraps_native_server_error_middleware():
    from starlette.middleware.errors import ServerErrorMiddleware
    from core.middleware import MetricsMiddleware

    app = create_app(make_settings())
    assert isinstance(app, FastAPI)
    assert app.openapi()["paths"]
    stack = app.build_middleware_stack()
    assert isinstance(stack, MetricsMiddleware)
    assert isinstance(stack.app, ServerErrorMiddleware)
    assert not any(item.cls is MetricsMiddleware for item in app.user_middleware)


def test_shared_transport_state_records_first_observed_disconnect(monkeypatch):
    from core import transport

    scope = {}
    state = transport.get_transport(scope)
    assert state is scope["rick.transport"] is transport.get_transport(scope)
    assert not state.disconnected.is_set()
    assert state.disconnected_at is None
    monkeypatch.setattr(transport.time, "monotonic", lambda: 12.5)
    state.disconnect()
    monkeypatch.setattr(transport.time, "monotonic", lambda: 99.0)
    state.disconnect()
    assert state.disconnected.is_set()
    assert state.disconnected_at == 12.5


def test_unobserved_client_disconnect_remains_an_application_failure():
    app = create_app(make_settings())
    original = ClientDisconnect()

    async def endpoint():
        raise original

    app.add_api_route("/probe", endpoint)
    with pytest.raises(ClientDisconnect) as caught:
        asyncio.run(exercise(app))
    assert caught.value is original
    assert_failure_once(app)
