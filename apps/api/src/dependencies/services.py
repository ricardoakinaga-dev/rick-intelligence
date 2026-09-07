"""Dependency providers — tests replace these without monkey-patching globals."""

from __future__ import annotations

from dataclasses import dataclass, field
from starlette.requests import Request

from core.config import ApiSettings


@dataclass
class Providers:
    settings: ApiSettings
    identity: object = None  # IdentityProvider protocol
    chat_backend: object = None  # ChatBackend protocol
    health_checks: dict = field(default_factory=dict)
    audit_sink: object = None
    chat_history: object = None
    job_journal: object = None
    rate_limiter: object = None
    knowledge: object = None  # rick_knowledge store (preferred read path)
    vector_store: object = None  # vector store (local SQLite or live adapter)
    retrieval: object = None  # RetrievalApplicationService (flag-gated)
    provider: object = None  # typed root LLM/embedding provider
    lease: object = None  # owner-safe root lease client
    professor: object = None  # root Professor orchestrator/backend
    ingestion: object = None  # bounded root ingestion application service
    worker: object = None  # process-local job runner (never implied durable)
    storage: object = None  # external durable metadata store in production
    queue: object = None  # external durable ingestion queue in production
    object_store: object = None  # external durable object store in production


def get_providers(request: Request) -> Providers:
    """Resolve only the app serving this request; never a process-wide fallback."""
    providers = getattr(request.app.state, "providers", None)
    if providers is None:
        raise RuntimeError("request application has no configured providers")
    return providers


def get_settings(request: Request) -> ApiSettings:
    return get_providers(request).settings
