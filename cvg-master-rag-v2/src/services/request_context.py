"""
Request-scoped context helpers for trace correlation.
"""
from contextvars import ContextVar
from uuid import uuid4


_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def generate_request_id() -> str:
    return str(uuid4())


def set_request_id(request_id: str | None) -> str:
    resolved = request_id or generate_request_id()
    _request_id_var.set(resolved)
    return resolved


def get_request_id() -> str | None:
    return _request_id_var.get()


def clear_request_id() -> None:
    _request_id_var.set(None)
