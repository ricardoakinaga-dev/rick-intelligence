"""Lifecycle + readiness semantics: ready / degraded / not_ready."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass
class DependencyState:
    name: str
    ok: bool
    required: bool = True
    detail: str | None = None


@dataclass
class AppState:
    settings: object = None
    providers: object = None
    checks: dict[str, Callable[[], DependencyState | Awaitable[DependencyState]]] = field(default_factory=dict)


def evaluate_readiness(states: list[DependencyState]) -> tuple[str, int]:
    """Returns (status, http_code). ready→200, degraded→200, not_ready→503.

    Any required dependency down => not_ready (503). Optional down => degraded (200).
    """
    if any(s.required and not s.ok for s in states):
        return "not_ready", 503
    if any(not s.ok for s in states):
        return "degraded", 200
    return "ready", 200
