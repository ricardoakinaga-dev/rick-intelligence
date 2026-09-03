"""Dependency providers — tests replace these without monkey-patching globals."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.config import ApiSettings


@dataclass
class Providers:
    settings: ApiSettings
    identity: object = None  # IdentityProvider protocol
    chat_backend: object = None  # ChatBackend protocol
    health_checks: dict = field(default_factory=dict)
    audit_sink: object = None
    rate_limiter: object = None


_global_providers: Providers | None = None


def set_providers(providers: Providers) -> None:
    global _global_providers
    _global_providers = providers


def get_providers() -> Providers:
    assert _global_providers is not None, "providers not initialized; use create_app()"
    return _global_providers


def get_settings() -> ApiSettings:
    return get_providers().settings
