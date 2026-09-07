"""Explicit provider selection for runtime wiring."""

from __future__ import annotations

import httpx

from rick_providers.client import CorrelationIdFactory, OpenAICompatibleClient, SleepFunction
from rick_providers.config import ProviderConfig, ProviderConfigurationError
from rick_providers.deterministic import DeterministicProvider


def create_provider(
    config: ProviderConfig | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: SleepFunction | None = None,
    client: httpx.AsyncClient | None = None,
    correlation_id_factory: CorrelationIdFactory | None = None,
) -> OpenAICompatibleClient | DeterministicProvider:
    """Create the configured provider with fail-closed deterministic mode.

    The default is the OpenAI-compatible adapter.  The deterministic adapter
    is selected only when configuration explicitly names it and the
    environment is test/dev/local; a production configuration cannot silently
    fall back to it.
    """

    selected = config or ProviderConfig.from_env()
    try:
        selected.validate()
    except ProviderConfigurationError:
        raise
    if selected.provider_kind == "deterministic":
        if not selected.is_test_or_dev:
            raise ProviderConfigurationError()
        return DeterministicProvider(
            selected,
            correlation_id_factory=correlation_id_factory,
        )
    return OpenAICompatibleClient(
        selected,
        transport=transport,
        sleep=sleep,
        client=client,
        correlation_id_factory=correlation_id_factory,
    )


provider_from_config = create_provider
provider_from_env = create_provider
build_provider = create_provider


__all__ = [
    "build_provider",
    "create_provider",
    "provider_from_config",
    "provider_from_env",
]
