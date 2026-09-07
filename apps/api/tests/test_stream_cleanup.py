"""Bound request wait without abandoning ownership of resistant finalizers."""
import asyncio
import threading

import anyio
import pytest
from starlette.responses import StreamingResponse

from app import create_app
from conftest import make_settings
from core import streaming
from test_transport_observation import scope, total


def leaves(error):
    nested = getattr(error, "exceptions", ())
    return [leaf for item in nested for leaf in leaves(item)] if nested else [error]


@pytest.mark.parametrize("cancel_caller", [False, True])
def test_shielded_native_finalizer_does_not_extend_request_wait(monkeypatch, cancel_caller):
    monkeypatch.setattr(streaming, "STREAM_CLEANUP_SECONDS", .02)

    async def run():
        app = create_app(make_settings())
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def chunks():
            try:
                yield b"one"
                entered.set()
                await asyncio.Event().wait()
            finally:
                with anyio.CancelScope(shield=True):
                    cleaning.set()
                    await release.wait()

        retained = chunks()
        async def endpoint():
            return StreamingResponse(retained)
        app.add_api_route("/probe", endpoint)

        async def receive():
            await entered.wait()
            if cancel_caller:
                await asyncio.Event().wait()
            return {"type": "http.disconnect"}
        async def send(message):
            pass

        task = asyncio.create_task(app(scope(), receive, send))
        try:
            await asyncio.wait_for(entered.wait(), .5)
            if cancel_caller:
                task.cancel()
            await asyncio.wait_for(cleaning.wait(), .5)
            done, _ = await asyncio.wait([task], timeout=.15)
            assert task in done, "request wait exceeded teardown deadline"
            with pytest.raises(BaseException) as caught:
                await task
            assert any(isinstance(x, TimeoutError) for x in leaves(caught.value))
            assert total(app.state.telemetry, "api.http.errors") == 1
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            # Inspect on the running loop, not after asyncgen shutdown.
            for _ in range(100):
                if retained.ag_frame is None:
                    break
                await asyncio.sleep(.001)
            assert retained.ag_frame is None

    asyncio.run(run())


@pytest.mark.parametrize("late_failure", [False, True])
def test_resistant_cleanup_retains_capacity_until_actual_completion(monkeypatch, late_failure):
    monkeypatch.setattr(streaming, "STREAM_CLEANUP_SECONDS", .02)
    monkeypatch.setattr(streaming, "_slots", threading.BoundedSemaphore(1))

    async def run():
        app = create_app(make_settings())
        release, cleaning = asyncio.Event(), asyncio.Event()
        invoked = 0
        loop_errors = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: loop_errors.append(context))
        initial = dict(streaming.cleanup_outcomes)
        baseline = set(streaming._active_tasks)

        class Iterator:
            def __aiter__(self):
                return self
            async def __anext__(self):
                raise StopAsyncIteration
            async def aclose(self):
                cleaning.set()
                while not release.is_set():
                    try:
                        with anyio.CancelScope(shield=True):
                            await release.wait()
                    except asyncio.CancelledError:
                        continue
                if late_failure:
                    raise ValueError("synthetic private provider detail")

        async def endpoint():
            nonlocal invoked
            invoked += 1
            return StreamingResponse(Iterator()) if invoked == 1 else {"ok": True}
        app.add_api_route("/probe", endpoint)
        async def receive():
            await asyncio.Event().wait()
        sent = []
        async def send(message):
            sent.append(message)

        task = asyncio.create_task(app(scope(), receive, send))
        try:
            await asyncio.wait_for(cleaning.wait(), .5)
            done, _ = await asyncio.wait([task], timeout=.15)
            assert task in done
            with pytest.raises(BaseException) as caught:
                await task
            assert any(isinstance(x, TimeoutError) for x in leaves(caught.value))
            assert len(streaming._active_tasks - baseline) == 1
            assert not release.is_set()
            first_sends = len(sent)
            for _ in range(3):
                responses = []
                async def capture(message):
                    responses.append(message)
                await app(scope(), receive, capture)
                assert responses[0]["status"] == 503
                assert b"provider_unavailable" in responses[-1]["body"]
            assert invoked == 1, "admission must happen before endpoint resource allocation"
            assert len(streaming._active_tasks - baseline) == 1
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            remaining = streaming._active_tasks - baseline
            if remaining:
                await asyncio.wait_for(asyncio.gather(*remaining, return_exceptions=True), .5)
            await asyncio.sleep(0)
        assert streaming._active_tasks == baseline
        assert len(sent) == first_sends, "no late transport sends after request timeout"
        outcome = "late_failure" if late_failure else "late_completion"
        assert streaming.cleanup_outcomes[outcome] == initial.get(outcome, 0) + 1
        assert not loop_errors
        await app(scope(), receive, send)
        assert invoked == 2
        assert any(message.get("status") == 200 for message in sent[first_sends:])

    asyncio.run(run())


def test_nonstream_and_endpoint_failure_release_admission(monkeypatch):
    monkeypatch.setattr(streaming, "_slots", threading.BoundedSemaphore(1))

    async def run():
        app = create_app(make_settings())
        failure = ValueError("endpoint failure")
        invoked = 0
        async def endpoint():
            nonlocal invoked
            invoked += 1
            if invoked == 1:
                raise failure
            return {"ok": True}
        app.add_api_route("/probe", endpoint)
        async def receive():
            await asyncio.Event().wait()
        sent = []
        async def send(message):
            sent.append(message)
        with pytest.raises(ValueError) as caught:
            await app(scope(), receive, send)
        assert caught.value is failure
        for _ in range(3):
            await app(scope(), receive, send)
        assert invoked == 4
        assert not streaming._active_tasks

    asyncio.run(run())


def test_healthy_stream_has_no_added_lifetime_deadline(monkeypatch):
    monkeypatch.setattr(streaming, "STREAM_CLEANUP_SECONDS", .02)

    async def run():
        app = create_app(make_settings())
        async def chunks():
            yield b"one"
            await asyncio.sleep(.06)
            yield b"two"
        async def endpoint():
            return StreamingResponse(chunks())
        app.add_api_route("/probe", endpoint)
        async def receive():
            await asyncio.Event().wait()
        sent = []
        async def send(message):
            sent.append(message)
        await asyncio.wait_for(app(scope(), receive, send), .5)
        assert b"".join(m.get("body", b"") for m in sent) == b"onetwo"
        assert total(app.state.telemetry, "api.http.errors") == 0
        assert not streaming._active_tasks

    asyncio.run(run())


def test_background_teardown_deadline_starts_after_final_body(monkeypatch):
    from starlette.background import BackgroundTask
    monkeypatch.setattr(streaming, "STREAM_CLEANUP_SECONDS", .02)

    async def run():
        app = create_app(make_settings())
        cleaned = asyncio.Event()
        async def chunks():
            yield b"one"
        async def background():
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        async def endpoint():
            return StreamingResponse(chunks(), background=BackgroundTask(background))
        app.add_api_route("/probe", endpoint)
        async def receive():
            await asyncio.Event().wait()
        sent = []
        async def send(message):
            sent.append(message)
        task = asyncio.create_task(app(scope(), receive, send))
        try:
            done, _ = await asyncio.wait([task], timeout=.15)
            assert task in done
            with pytest.raises(BaseException) as caught:
                await task
            assert any(isinstance(x, TimeoutError) for x in leaves(caught.value))
            assert sent[-1] == {"type": "http.response.body", "body": b"", "more_body": False}
            await asyncio.wait_for(cleaned.wait(), .5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            remaining = set(streaming._active_tasks)
            if remaining:
                await asyncio.wait_for(asyncio.gather(*remaining, return_exceptions=True), .5)

    asyncio.run(run())
