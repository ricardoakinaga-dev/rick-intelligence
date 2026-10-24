"""Zero-queue offload for synchronous identity/KDF/DB ports.

40 is the existing Starlette/AnyIO default thread safety ceiling, not a
throughput promise. Deadlines reuse the configured provider timeout. A timed
out/cancelled caller cannot kill Python/DB work: its slot remains occupied until
real completion. Shutdown stops admission and drains before stores can close.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar, copy_context
from functools import partial
import inspect
import math
import threading
import time
from typing import ParamSpec, Protocol, TypedDict, TypeVar, cast

from fastapi import Request

from core.config import ApiSettings
from core.errors import ApiError
from models import SessionSnapshot


class IdentityLoginResult(TypedDict):
    session_token: str


class IdentityTokenPort(Protocol):
    def validate_token(self, token: str | None) -> SessionSnapshot: ...


class IdentitySessionPort(IdentityTokenPort, Protocol):
    def logout(self, token: str | None, *, operation_id: str | None = None) -> None: ...


class IdentityLoginPort(IdentityTokenPort, Protocol):
    def login(self, *, email: str, password: str, tenant_id: str,
              workspace_id: str | None = None,
              ip: str | None, user_agent: str | None) -> IdentityLoginResult: ...


class _IdentityPorts:
    """Typed lazy facade, preserving supported dynamic __getattr__ adapters.

    Runtime Protocol isinstance uses getattr_static on Python 3.12 and rejects
    delegation. Resolve and validate the actual callable only when invoked in
    the admitted worker, so a descriptor/lookup cannot block the ASGI loop.
    This facade never wraps admin transactions or claims rollback capability.
    """
    def __init__(self, value: object) -> None:
        self._identity = value

    def _invoke(self, name: str, *args: object, **kwargs: object) -> object:
        method = getattr(self._identity, name, None)
        if not callable(method):
            raise ApiError("provider_unavailable")
        result: object = method(*args, **kwargs)
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise ApiError("provider_unavailable")
        return result

    def validate_token(self, token: str | None) -> SessionSnapshot:
        result = self._invoke("validate_token", token)
        if not isinstance(result, SessionSnapshot):
            raise ApiError("provider_unavailable")
        return result

    def logout(self, token: str | None, *, operation_id: str | None = None) -> None:
        method = getattr(self._identity, "logout", None)
        if operation_id and callable(method):
            parameters: Mapping[str, inspect.Parameter] = {}
            try:
                parameters = inspect.signature(method).parameters
            except (TypeError, ValueError):
                parameters = {}
            if "operation_id" in parameters:
                self._invoke("logout", token, operation_id=operation_id)
                return
        self._invoke("logout", token)

    def login(self, *, email: str, password: str, tenant_id: str,
              workspace_id: str | None = None,
              ip: str | None, user_agent: str | None) -> IdentityLoginResult:
        method = getattr(self._identity, "login", None)
        parameters: Mapping[str, inspect.Parameter] = {}
        if callable(method):
            try:
                parameters = inspect.signature(method).parameters
            except (TypeError, ValueError):
                parameters = {}
        if workspace_id is not None and "workspace_id" in parameters:
            result = self._invoke("login", email=email, password=password,
                                  tenant_id=tenant_id, workspace_id=workspace_id,
                                  ip=ip, user_agent=user_agent)
        else:
            result = self._invoke("login", email=email, password=password,
                                  tenant_id=tenant_id, ip=ip, user_agent=user_agent)
        token = result.get("session_token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise ApiError("provider_unavailable")
        # Other adapter metadata is not part of the HTTP login orchestration.
        return {"session_token": token}


def identity_token_port(value: object) -> IdentityTokenPort:
    return _IdentityPorts(value)


def identity_session_port(value: object) -> IdentitySessionPort:
    return _IdentityPorts(value)


def identity_login_port(value: object) -> IdentityLoginPort:
    return _IdentityPorts(value)


P = ParamSpec("P")
T = TypeVar("T")


_process_slots = threading.BoundedSemaphore(40)
_operation: ContextVar[tuple[threading.Event, float] | None] = ContextVar("identity_operation", default=None)


def ensure_identity_operation_current() -> None:
    """Do not confirm a synchronous sequence after its caller abandoned it."""
    operation = _operation.get()
    if operation is not None:
        abandoned, deadline = operation
        if abandoned.is_set() or time.monotonic() >= deadline:
            raise ApiError("provider_unavailable")


class IdentityOffload:
    def __init__(self, capacity: int = 40) -> None:
        self.capacity = capacity
        self._condition = threading.Condition()
        self._active = 0
        self._closed = False

    async def run(self, function: Callable[..., T | Awaitable[T]], *args: object,
                  timeout: float, allow_awaitable: bool = False, **kwargs: object) -> T:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ApiError("provider_unavailable")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[object] = loop.create_future()
        with self._condition:
            if self._closed or self._active >= self.capacity or not _process_slots.acquire(blocking=False):
                raise ApiError("provider_unavailable")
            self._active += 1
        context = copy_context()
        abandoned = threading.Event()
        context.run(_operation.set, (abandoned, time.monotonic() + timeout))

        def deliver(value: object, error: BaseException | None) -> None:
            if not future.done():
                if error is None:
                    future.set_result(value)
                else:
                    future.set_exception(error)

        async_task: list[asyncio.Future[object] | None] = [None]

        def release_slot() -> None:
            with self._condition:
                self._active -= 1
                _process_slots.release()
                self._condition.notify_all()

        def close_unstarted(value: object) -> None:
            close = getattr(value, "close", None)
            if callable(close):
                close()

        def async_done(task: asyncio.Future[object]) -> None:
            value: object
            error: BaseException | None
            try:
                value, error = task.result(), None
            except asyncio.CancelledError:
                value, error = None, ApiError("provider_unavailable")
            except BaseException as exc:
                value, error = None, exc
            release_slot()
            deliver(value, error)

        def start_async(value: Awaitable[object]) -> None:
            # The thread only created an awaitable. Keep the SAME admission
            # slot until its real async work terminates, including resistant
            # cancellation; never wait for cancellation beyond the HTTP budget.
            if (abandoned.is_set() or future.done()) and inspect.iscoroutine(value):
                close_unstarted(value)
                release_slot()
                return
            try:
                task = asyncio.ensure_future(value, loop=loop)
                async_task[0] = task
                task.add_done_callback(async_done)
                if abandoned.is_set() or future.done():
                    task.cancel()
            except BaseException as exc:
                close_unstarted(value)
                release_slot()
                deliver(None, exc)

        def invoke() -> None:
            value: object = None
            error: BaseException | None = None
            try:
                value = context.run(partial(function, *args, **kwargs))
                if inspect.isawaitable(value):
                    if allow_awaitable:
                        try:
                            loop.call_soon_threadsafe(start_async, value, context=context)
                        except RuntimeError:
                            close_unstarted(value)
                            release_slot()
                        return
                    close_unstarted(value)
                    raise ApiError("provider_unavailable")
            except BaseException as exc:
                error = exc
            release_slot()
            try:
                loop.call_soon_threadsafe(deliver, value, error)
            except RuntimeError:
                pass  # caller loop closed; synchronous operation already finished

        thread = threading.Thread(target=invoke, name="identity-operation", daemon=True)
        try:
            thread.start()
        except BaseException:
            with self._condition:
                self._active -= 1
                _process_slots.release()
                self._condition.notify_all()
            raise ApiError("provider_unavailable") from None
        try:
            # One checked bridge cast reconnects the opaque cross-thread
            # Future to the callable's generic result; no credentials are cast.
            return cast(T, await asyncio.wait_for(future, timeout=timeout))
        except TimeoutError:
            abandoned.set()
            if async_task[0] is not None:
                async_task[0].cancel()
            raise ApiError("provider_unavailable") from None
        except asyncio.CancelledError:
            abandoned.set()
            if async_task[0] is not None:
                async_task[0].cancel()
            raise

    def shutdown(self, *, wait: bool = True, timeout: float = 0.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            self._closed = True
            while wait and self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._active == 0


class IdentityOffloadOptions(TypedDict):
    offload: IdentityOffload
    timeout_seconds: float


def identity_offload_options(request: Request) -> IdentityOffloadOptions:
    """One absolute budget covers quota initialization/IO and identity work."""
    deadline: float | None = getattr(request.state, "identity_deadline", None)
    if deadline is None:
        settings: ApiSettings = request.app.state.providers.settings
        deadline = time.monotonic() + settings.provider_timeout_ms / 1000
        request.state.identity_deadline = deadline
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ApiError("provider_unavailable")
    return {"offload": request.app.state.identity_offload, "timeout_seconds": remaining}


async def run_identity(request: Request, function: Callable[P, T],
                       *args: P.args, **kwargs: P.kwargs) -> T:
    options = identity_offload_options(request)
    try:
        return await options["offload"].run(partial(function, *args, **kwargs),
                                             timeout=options["timeout_seconds"])
    except ApiError:
        raise
    except Exception:
        # Adapter failures never leak backend detail or become false absence.
        raise ApiError("provider_unavailable") from None
