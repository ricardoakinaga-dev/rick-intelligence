"""Per-request signals from actual ASGI transport observation only."""
from __future__ import annotations

import asyncio
import time

from starlette.requests import ClientDisconnect


class TransportState:
    def __init__(self):
        self.disconnected = asyncio.Event()
        self.disconnected_at: float | None = None

    def disconnect(self) -> None:
        if not self.disconnected.is_set():
            self.disconnected_at = time.monotonic()
            self.disconnected.set()


def get_transport(scope) -> TransportState:
    if "rick.transport" not in scope:
        scope["rick.transport"] = TransportState()
    return scope["rick.transport"]


class _TransportClosed(OSError):
    """Raised only by the observer when an actual ASGI send raises OSError."""


def all_leaves(error: BaseException, kinds: tuple[type[BaseException], ...]) -> bool:
    if isinstance(error, kinds):
        return True
    return isinstance(error, BaseExceptionGroup) and all(
        all_leaves(item, kinds) for item in error.exceptions
    )


def is_transport_only(scope, error: BaseException) -> bool:
    return get_transport(scope).disconnected.is_set() and all_leaves(
        error, (ClientDisconnect, _TransportClosed)
    )
