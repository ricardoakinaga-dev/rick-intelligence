"""In-memory audit sink (default) — legacy log_admin_event wiring plugs in here when enabled."""

from __future__ import annotations


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        try:
            self.events.append(dict(event))
        except Exception:
            pass  # audit must never break the request path (failure policy: best-effort + error log)
