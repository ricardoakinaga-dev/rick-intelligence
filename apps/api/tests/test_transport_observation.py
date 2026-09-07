"""Exercise the real ASGI stack; transport abandonment is not an app failure."""
import asyncio

import pytest
from fastapi import Request
from starlette.responses import StreamingResponse

from app import create_app
from conftest import make_settings
from core.middleware import MetricsMiddleware
from core.telemetry import ApiTelemetry


def scope(path="/probe", method="GET"):
    return dict(type="http", asgi={"version": "3.0", "spec_version": "2.3"},
                http_version="1.1", method=method, scheme="http", path=path,
                raw_path=path.encode(), query_string=b"", root_path="", headers=[],
                client=("127.0.0.1", 123), server=("testserver", 80))


async def exercise(app, *, path="/probe", method="GET", disconnected=False, sender=None):
    first = True
    sent = []
    async def receive():
        nonlocal first
        if disconnected:
            return {"type": "http.disconnect"}
        if first:
            first = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()
    async def send(message):
        if sender:
            await sender(message)
        sent.append(message)
    await asyncio.wait_for(app(scope(path, method), receive, send), timeout=2)
    return sent


def total(telemetry, name):
    return sum(item["total"] for item in telemetry.snapshot()["counters"] if item["name"] == name)


def test_actual_ready_early_disconnect_does_not_become_a_500():
    app = create_app(make_settings())
    sent = asyncio.run(exercise(app, path="/health/ready", disconnected=True))
    assert all(message.get("status", 200) < 500 for message in sent)
    assert total(app.state.telemetry, "api.http.errors") == 0


def test_observed_body_disconnect_is_separate_from_slo():
    app = create_app(make_settings())
    async def read_body(request: Request):
        await request.body()
        return {"ok": True}
    app.add_api_route("/probe", read_body, methods=["POST"])
    asyncio.run(exercise(app, method="POST", disconnected=True))
    assert total(app.state.telemetry, "api.http.disconnects") == 1
    assert app.state.telemetry.snapshot()["slo"]["observations"] == 0


@pytest.mark.parametrize("error", [RuntimeError("No response returned."), OSError("application failure")])
def test_connected_application_errors_propagate_and_count_once(error):
    app = create_app(make_settings())
    async def broken():
        raise error
    app.add_api_route("/probe", broken)
    with pytest.raises(type(error), match=str(error)):
        asyncio.run(exercise(app))
    assert total(app.state.telemetry, "api.http.errors") == 1
    assert app.state.telemetry.snapshot()["slo"]["observations"] == 1


def test_post_header_stream_error_is_not_counted_as_success():
    app = create_app(make_settings())
    closed = []
    async def chunks():
        try:
            yield b"first"
            raise ValueError("synthetic stream failure")
        finally:
            closed.append(True)
    async def streaming():
        return StreamingResponse(chunks())
    app.add_api_route("/probe", streaming)
    with pytest.raises((ValueError, ExceptionGroup)) as caught:
        asyncio.run(exercise(app))
    error = caught.value
    while isinstance(error, ExceptionGroup) and len(error.exceptions) == 1:
        error = error.exceptions[0]
    assert isinstance(error, ValueError) and str(error) == "synthetic stream failure"
    assert closed == [True]
    snapshot = app.state.telemetry.snapshot()
    assert snapshot["slo"]["observations"] == 1
    assert snapshot["slo"]["error_rate"] == 1.0
    assert total(app.state.telemetry, "api.http.errors") == 1


def test_transport_send_failure_does_not_create_service_error():
    app = create_app(make_settings())
    async def closed_transport(message):
        raise BrokenPipeError("synthetic closed transport")
    asyncio.run(exercise(app, path="/health/live", sender=closed_transport))
    assert total(app.state.telemetry, "api.http.disconnects") == 1
    assert app.state.telemetry.snapshot()["slo"]["observations"] == 0


def test_stream_disconnect_closes_generator_and_does_not_count_success():
    async def run():
        app = create_app(make_settings())
        first_sent = asyncio.Event()
        closed = asyncio.Event()
        async def chunks():
            try:
                yield b"first"
                await asyncio.Event().wait()
            finally:
                closed.set()
        async def streaming():
            return StreamingResponse(chunks())
        app.add_api_route("/probe", streaming)
        async def receive():
            await first_sent.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                first_sent.set()
        await asyncio.wait_for(app(scope(), receive, send), timeout=2)
        assert closed.is_set()
        assert total(app.state.telemetry, "api.http.disconnects") == 1
        assert app.state.telemetry.snapshot()["slo"]["observations"] == 0
    asyncio.run(run())


def test_non_http_scopes_pass_through_without_metrics():
    telemetry = ApiTelemetry()
    seen = []
    async def child(scope, receive, send):
        seen.append(scope)
    middleware = MetricsMiddleware(child, telemetry=telemetry)
    ws_scope = {"type": "websocket"}
    asyncio.run(middleware(ws_scope, None, None))
    assert seen == [ws_scope]
    assert telemetry.snapshot()["slo"]["observations"] == 0


def test_real_failure_after_observed_disconnect_is_still_visible():
    from starlette.requests import ClientDisconnect
    telemetry = ApiTelemetry()
    async def child(scope, receive, send):
        await receive()
        raise ExceptionGroup("mixed", [ClientDisconnect(), ValueError("real failure")])
    middleware = MetricsMiddleware(child, telemetry=telemetry)
    with pytest.raises(ExceptionGroup) as caught:
        asyncio.run(exercise(middleware, disconnected=True))
    assert any(isinstance(error, ValueError) for error in caught.value.exceptions)
    assert total(telemetry, "api.http.errors") == 1
    assert total(telemetry, "api.http.disconnects") == 0


def test_server_task_cancellation_propagates_without_service_error():
    async def run():
        telemetry = ApiTelemetry()
        entered = asyncio.Event()
        async def child(scope, receive, send):
            entered.set()
            await asyncio.Event().wait()
        middleware = MetricsMiddleware(child, telemetry=telemetry)
        task = asyncio.create_task(exercise(middleware))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert total(telemetry, "api.http.cancellations") == 1
        assert telemetry.snapshot()["slo"]["observations"] == 0
    asyncio.run(run())


def test_stream_send_failure_closes_generator_on_the_running_loop():
    async def run():
        app = create_app(make_settings())
        closed = asyncio.Event()
        async def chunks():
            try:
                yield b"first"
                await asyncio.Event().wait()
            finally:
                closed.set()
        async def streaming():
            return StreamingResponse(chunks())
        app.add_api_route("/probe", streaming)
        async def send(message):
            if message["type"] == "http.response.body":
                raise BrokenPipeError("closed while streaming")
        await exercise(app, sender=send)
        # Observe cleanup before asyncio.run's shutdown_asyncgens can hide a leak.
        await asyncio.wait_for(closed.wait(), timeout=0.5)
        assert total(app.state.telemetry, "api.http.disconnects") == 1
        assert app.state.telemetry.snapshot()["slo"]["observations"] == 0
    asyncio.run(run())


def test_request_context_is_restored_after_application_failure():
    from core.middleware import RequestContextMiddleware
    from core.request_context import RequestContext, clear_current, get_current, set_current
    previous = RequestContext(request_id="outer", correlation_id="outer")
    async def child(scope, receive, send):
        assert get_current() is not previous
        raise ValueError("context cleanup")
    async def run():
        set_current(previous)
        try:
            with pytest.raises(ValueError, match="context cleanup"):
                await exercise(RequestContextMiddleware(child))
            assert get_current() is previous
        finally:
            clear_current()
    asyncio.run(run())


def test_declared_size_cannot_crash_integer_parsing():
    from fastapi.testclient import TestClient
    app = create_app(make_settings())
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", content=b"", headers={"Content-Length": "9" * 5000})
    assert response.status_code == 413
    assert total(app.state.telemetry, "api.http.errors") == 0


def test_retained_generator_is_explicitly_closed_after_send_failure():
    async def run():
        app = create_app(make_settings())
        closed = asyncio.Event()
        async def chunks():
            try:
                yield b"first"
                await asyncio.Event().wait()
            finally:
                closed.set()
        retained = chunks()
        async def streaming():
            return StreamingResponse(retained)
        app.add_api_route("/probe", streaming)
        async def send(message):
            if message["type"] == "http.response.body":
                raise BrokenPipeError("closed transport")
        try:
            await exercise(app, sender=send)
            assert closed.is_set()
        finally:
            await retained.aclose()
    asyncio.run(run())


def test_csrf_rejection_retains_security_and_correlation_headers():
    from fastapi.testclient import TestClient
    from core.security import SECURITY_HEADERS
    app = create_app(make_settings())
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": "hello"}, headers={
            "Cookie": "rick_session=present", "Origin": "https://evil.example",
            "X-Request-ID": "transport-test", "X-Correlation-ID": "correlation-test"})
    assert response.status_code == 403
    assert response.headers["x-request-id"] == "transport-test"
    assert response.headers["x-correlation-id"] == "correlation-test"
    assert response.json()["error"]["request_id"] == "transport-test"
    assert all(response.headers[key] == value for key, value in SECURITY_HEADERS.items())


def test_known_server_error_is_not_hidden_by_transport_failure():
    app = create_app(make_settings())
    async def unavailable():
        from starlette.responses import JSONResponse
        return JSONResponse({"error": "synthetic unavailable"}, status_code=503)
    app.add_api_route("/probe", unavailable)
    async def send(message):
        if message["type"] == "http.response.body":
            raise BrokenPipeError("closed after server error headers")
    asyncio.run(exercise(app, sender=send))
    assert total(app.state.telemetry, "api.http.errors") == 1
    assert app.state.telemetry.snapshot()["slo"]["error_rate"] == 1.0


def test_unhandled_error_keeps_security_and_correlation_headers():
    from fastapi.testclient import TestClient
    from core.security import SECURITY_HEADERS
    app = create_app(make_settings())
    async def broken():
        raise ValueError("private failure")
    app.add_api_route("/probe", broken)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/probe", headers={"X-Request-ID": "error-test", "X-Correlation-ID": "correlation-test"})
    assert response.status_code == 500
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"] == "error-test"
    assert response.headers["x-correlation-id"] == "correlation-test"
    assert all(response.headers[key] == value for key, value in SECURITY_HEADERS.items())
    assert "private failure" not in response.text


def test_canonical_streaming_routes_own_response_teardown():
    from core.streaming import ClosingStreamingRoute
    app = create_app(make_settings())
    for path in ("/api/v1/chat", "/v1/chat/completions"):
        route = next(route for route in app.routes if getattr(route, "path", None) == path)
        assert isinstance(route, ClosingStreamingRoute)


def test_cleanup_failure_is_not_hidden_by_transport_disconnect():
    app = create_app(make_settings())
    class Iterator:
        def __aiter__(self):
            return self
        async def __anext__(self):
            return b"chunk"
        async def aclose(self):
            raise ValueError("cleanup failed")
    async def streaming():
        return StreamingResponse(Iterator())
    app.add_api_route("/probe", streaming)
    async def send(message):
        if message["type"] == "http.response.body":
            raise BrokenPipeError("closed")
    with pytest.raises(ExceptionGroup) as caught:
        asyncio.run(exercise(app, sender=send))
    assert any(isinstance(error, ValueError) and str(error) == "cleanup failed" for error in caught.value.exceptions)
    assert total(app.state.telemetry, "api.http.errors") == 1


def test_cooperative_cleanup_has_a_finite_bound(monkeypatch):
    from core import streaming as streaming_module
    monkeypatch.setattr(streaming_module, "STREAM_CLEANUP_SECONDS", 0.02)
    app = create_app(make_settings())
    class Iterator:
        def __aiter__(self):
            return self
        async def __anext__(self):
            return b"chunk"
        async def aclose(self):
            await asyncio.Event().wait()
    async def streaming():
        return StreamingResponse(Iterator())
    app.add_api_route("/probe", streaming)
    async def send(message):
        if message["type"] == "http.response.body":
            raise BrokenPipeError("closed")
    with pytest.raises(ExceptionGroup) as caught:
        asyncio.run(exercise(app, sender=send))
    assert any(isinstance(error, TimeoutError) for error in caught.value.exceptions)
    assert total(app.state.telemetry, "api.http.errors") == 1


@pytest.mark.parametrize("raise_api_error", [False, True])
def test_service_failure_after_receive_disconnect_still_counts(raise_api_error):
    from core.errors import ApiError
    from starlette.responses import JSONResponse
    app = create_app(make_settings())
    async def unavailable(request: Request):
        assert (await request.receive())["type"] == "http.disconnect"
        if raise_api_error:
            raise ApiError("provider_unavailable")
        return JSONResponse({"error": "synthetic unavailable"}, status_code=503)
    app.add_api_route("/probe", unavailable)
    sent = asyncio.run(exercise(app, disconnected=True))
    assert sent == []
    assert total(app.state.telemetry, "api.http.errors") == 1
    assert app.state.telemetry.snapshot()["slo"]["error_rate"] == 1.0
