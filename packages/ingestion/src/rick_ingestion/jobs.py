"""Canonical ingestion job contract + explicit state machine.

Stages: queued → validating → parsing → chunking → embedding → indexing →
verifying → published, plus failed/cancelled. Impossible transitions (e.g.
published → running) are rejected unless a new attempt is created. Heartbeats
carry stage + progress only — never document text.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

TERMINAL_STATES = ("published", "failed", "cancelled")

_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "queued": ("validating", "cancelled", "failed"),
    "validating": ("parsing", "failed", "cancelled"),
    "parsing": ("chunking", "failed", "cancelled"),
    "chunking": ("embedding", "failed", "cancelled"),
    "embedding": ("indexing", "failed", "cancelled"),
    "indexing": ("verifying", "failed", "cancelled"),
    "verifying": ("published", "failed", "cancelled"),
    "published": (),
    "failed": ("queued",),  # explicit retry creates a new attempt
    "cancelled": ("queued",),  # explicit re-queue creates a new attempt
}

TRANSIENT_ERROR_CODES = ("provider_timeout", "provider_unavailable", "vector_store_unavailable",
                         "lock_unavailable", "storage_unavailable")
PERMANENT_ERROR_CODES = ("validation_error", "unsupported_media_type", "request_too_large")


class InvalidTransitionError(Exception):
    pass


@dataclass
class IngestionJob:
    job_id: str = field(default_factory=lambda: f"ing-{uuid.uuid4().hex[:12]}")
    document_id: str | None = None
    status: str = "queued"
    stage: str = "queued"
    progress: float = 0.0
    attempt: int = 1
    error_code: str | None = None
    safe_error_message: str | None = None
    workspace_id: str = "default"
    collection_id: str = "rag_phase0"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    heartbeats: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def transition(self, to_status: str, *, error_code: str | None = None,
                   message: str | None = None, progress: float | None = None) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(self.status, ())
        if to_status not in allowed:
            raise InvalidTransitionError(f"{self.status} -> {to_status} is not allowed")
        if to_status in ("failed", "cancelled") or (self.status in ("failed", "cancelled") and to_status == "queued"):
            if self.status in ("failed", "cancelled") and to_status == "queued":
                self.attempt += 1
        self.status = to_status
        self.stage = to_status
        if progress is not None:
            self.progress = min(1.0, max(0.0, progress))
        if to_status in TERMINAL_STATES:
            self.finished_at = time.time()
        if self.started_at is None and to_status not in ("queued",):
            self.started_at = time.time()
        self.error_code = error_code
        self.safe_error_message = message

    def heartbeat(self, **fields) -> None:
        self.heartbeats.append({"at": time.time(), "stage": self.stage, **fields})


def is_retryable(error_code: str | None) -> bool:
    """Transient infra failures retry; malformed/unsupported content never does."""
    if error_code in TRANSIENT_ERROR_CODES:
        return True
    if error_code in PERMANENT_ERROR_CODES:
        return False
    return False
