"""Canonical RequestContext — server-derived identity only, never raw framework objects downstream."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field

MAX_CORRELATION_LEN = 128
_CORRELATION_RE = re.compile(r"^[A-Za-z0-9\-_:.]{1,128}$")
MAX_REQUEST_ID_LEN = 128
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9\-_:.]{1,128}$")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def normalize_correlation_id(value: str | None) -> str:
    """Preserve a trusted client correlation id; otherwise generate one. Caps length/charset."""
    if value and len(value) <= MAX_CORRELATION_LEN and _CORRELATION_RE.fullmatch(value):
        return value
    return uuid.uuid4().hex[:16]


def normalize_request_id(value: str | None) -> str:
    """Accept only a bounded, header-safe request id; otherwise generate one."""

    if value and len(value) <= MAX_REQUEST_ID_LEN and _REQUEST_ID_RE.fullmatch(value):
        return value
    return new_request_id()


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    correlation_id: str
    route: str = ""
    api_version: str = "v1"
    user_id: str | None = None
    session_id: str | None = None
    workspace_id: str | None = None
    tenant_id: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None

    def log_fields(self) -> dict:
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "route": self.route,
        }


_current: ContextVar[RequestContext | None] = ContextVar("rick_request_context", default=None)


def set_current(ctx: RequestContext) -> None:
    _current.set(ctx)


def get_current() -> RequestContext | None:
    return _current.get()


def clear_current() -> None:
    _current.set(None)
