"""Configuration for the root provider boundary.

The configuration object deliberately contains credentials because it is the
input to the HTTP adapter, but its representation is redacted.  Provider
errors never retain a reference to this object.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit

import httpx


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 1_536
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.25
DEFAULT_MAX_BACKOFF_SECONDS = 30.0

_TEST_OR_DEV_ENVIRONMENTS = frozenset({
    "test",
    "testing",
    "dev",
    "development",
    "local",
})
_PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production", "live"})


class ProviderConfigurationError(ValueError):
    """Safe construction-time configuration failure.

    A provider operation turns this into the contract ``ProviderError`` with
    an operation and correlation ID.  This exception is also used by
    ``create_provider`` where no logical operation exists yet.
    """

    code = "invalid_configuration"

    def __init__(self) -> None:
        super().__init__("Invalid provider configuration.")


@dataclass(frozen=True, slots=True, init=False)
class ProviderConfig:
    """Validated-at-use provider settings.

    ``timeout`` and retry delays are expressed in seconds.  The accepted
    environment values for the deterministic provider are intentionally
    narrow: it may be used only in an explicitly test/dev/local environment.
    """

    base_url: str
    api_key: str | None = field(default=None, repr=False)
    chat_model: str = DEFAULT_CHAT_MODEL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    timeout: float | httpx.Timeout = DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY_SECONDS
    max_backoff_delay: float = DEFAULT_MAX_BACKOFF_SECONDS
    environment: str = "production"
    provider_kind: str = "openai"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        chat_model: str = DEFAULT_CHAT_MODEL,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
        max_backoff_delay: float = DEFAULT_MAX_BACKOFF_SECONDS,
        environment: str = "production",
        provider_kind: str = "openai",
        # Friendly aliases make configuration from existing runtimes less
        # surprising without creating a second configuration model.
        timeout_ms: float | None = None,
        timeout_seconds: float | httpx.Timeout | None = None,
        retry_delay_seconds: float | None = None,
        retry_delay: float | None = None,
        backoff_base: float | None = None,
        backoff_base_seconds: float | None = None,
        backoff_factor: float | None = None,
        max_backoff_seconds: float | None = None,
        embedding_dimension: int | None = None,
    ) -> None:
        if timeout_seconds is not None:
            timeout = timeout_seconds
        if timeout_ms is not None:
            timeout = timeout_ms / 1_000
        aliases = [
            value
            for value in (retry_delay_seconds, retry_delay, backoff_base, backoff_base_seconds, backoff_factor)
            if value is not None
        ]
        if aliases:
            retry_base_delay = aliases[0]
        if max_backoff_seconds is not None:
            max_backoff_delay = max_backoff_seconds
        if embedding_dimension is not None:
            embedding_dimensions = embedding_dimension

        object.__setattr__(self, "base_url", base_url.strip() if isinstance(base_url, str) else base_url)
        if api_key is None:
            normalized_api_key: object = None
        elif isinstance(api_key, str):
            normalized_api_key = api_key.strip() or None
        else:
            normalized_api_key = api_key
        object.__setattr__(self, "api_key", normalized_api_key)
        object.__setattr__(self, "chat_model", chat_model)
        object.__setattr__(self, "embedding_model", embedding_model)
        object.__setattr__(self, "embedding_dimensions", embedding_dimensions)
        object.__setattr__(self, "timeout", timeout)
        object.__setattr__(self, "max_attempts", max_attempts)
        object.__setattr__(self, "retry_base_delay", retry_base_delay)
        object.__setattr__(self, "max_backoff_delay", max_backoff_delay)
        object.__setattr__(self, "environment", environment.strip().lower() if isinstance(environment, str) else environment)
        object.__setattr__(self, "provider_kind", provider_kind.strip().lower() if isinstance(provider_kind, str) else provider_kind)

    @property
    def timeout_seconds(self) -> float | httpx.Timeout:
        return self.timeout

    @property
    def timeout_ms(self) -> float | None:
        if isinstance(self.timeout, (int, float)) and not isinstance(self.timeout, bool):
            return float(self.timeout) * 1_000
        return None

    @property
    def embedding_dimension(self) -> int:
        return self.embedding_dimensions

    @property
    def backoff_base_seconds(self) -> float:
        return self.retry_base_delay

    @property
    def retry_delay(self) -> float:
        return self.retry_base_delay

    @property
    def max_backoff_seconds(self) -> float:
        return self.max_backoff_delay

    @property
    def is_production(self) -> bool:
        return isinstance(self.environment, str) and self.environment in _PRODUCTION_ENVIRONMENTS

    @property
    def is_test_or_dev(self) -> bool:
        return isinstance(self.environment, str) and self.environment in _TEST_OR_DEV_ENVIRONMENTS

    def __repr__(self) -> str:
        """Do not let a normal configuration repr expose the API key or URL."""

        timeout = "configured" if isinstance(self.timeout, httpx.Timeout) else self.timeout
        return (
            "ProviderConfig("
            f"provider_kind={self.provider_kind!r}, environment={self.environment!r}, "
            f"chat_model={self.chat_model!r}, embedding_model={self.embedding_model!r}, "
            f"embedding_dimensions={self.embedding_dimensions!r}, timeout={timeout!r}, "
            f"max_attempts={self.max_attempts!r})"
        )

    def validate(self) -> None:
        """Validate settings without including values in the exception."""

        if not isinstance(self.base_url, str):
            raise ProviderConfigurationError()
        try:
            parsed = urlsplit(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ProviderConfigurationError()
            # Userinfo and query strings are not valid provider base settings;
            # rejecting them also prevents credentials from being hidden in a
            # URL that might later be logged by an HTTP library.
            if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
                raise ProviderConfigurationError()
            _ = parsed.port
        except (ValueError, ProviderConfigurationError):
            raise ProviderConfigurationError() from None

        if self.api_key is not None and not isinstance(self.api_key, str):
            raise ProviderConfigurationError()
        if not isinstance(self.environment, str) or not self.environment:
            raise ProviderConfigurationError()
        if self.provider_kind not in {"openai", "openai_compatible", "deterministic"}:
            raise ProviderConfigurationError()
        if isinstance(self.timeout, bool):
            raise ProviderConfigurationError()
        if isinstance(self.timeout, httpx.Timeout):
            timeout_values = (self.timeout.connect, self.timeout.read, self.timeout.write, self.timeout.pool)
            if any(value is None or not _positive_finite(value) for value in timeout_values):
                raise ProviderConfigurationError()
        elif not _positive_finite(self.timeout):
            raise ProviderConfigurationError()
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 10:
            raise ProviderConfigurationError()
        if not _nonnegative_finite(self.retry_base_delay):
            raise ProviderConfigurationError()
        if not _nonnegative_finite(self.max_backoff_delay):
            raise ProviderConfigurationError()
        if type(self.embedding_dimensions) is not int or not 1 <= self.embedding_dimensions <= 16_384:
            raise ProviderConfigurationError()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ProviderConfig":
        """Build settings from environment variables with safe failures.

        The default kind is the live OpenAI-compatible adapter.  Selecting a
        deterministic adapter requires both ``RICK_PROVIDER=deterministic``
        and an explicit test/dev/local environment.
        """

        values = os.environ if environ is None else environ
        timeout_ms = _read_float(values, "OPENAI_TIMEOUT_MS", 30_000.0)
        retry_ms = _read_float(values, "OPENAI_RETRY_DELAY_MS", 250.0)
        max_backoff_ms = _read_float(values, "OPENAI_MAX_BACKOFF_MS", 30_000.0)
        max_attempts = _read_int(values, "OPENAI_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
        dimensions = _read_int(
            values,
            "OPENAI_EMBEDDING_DIMENSIONS",
            _read_int(values, "EMBEDDING_DIMENSION", DEFAULT_EMBEDDING_DIMENSIONS),
        )
        environment = _first_value(values, "RICK_ENV", "NODE_ENV", "ENV", default="production")
        provider_kind = _first_value(
            values,
            "RICK_PROVIDER",
            "RICK_PROVIDER_KIND",
            "RICK_PROVIDER_MODE",
            default="openai",
        )
        return cls(
            base_url=_first_value(values, "OPENAI_BASE_URL", default=DEFAULT_BASE_URL),
            api_key=values.get("OPENAI_API_KEY"),
            chat_model=_first_value(values, "OPENAI_CHAT_MODEL", default=DEFAULT_CHAT_MODEL),
            embedding_model=_first_value(values, "OPENAI_EMBEDDING_MODEL", default=DEFAULT_EMBEDDING_MODEL),
            embedding_dimensions=dimensions,
            timeout_ms=timeout_ms,
            max_attempts=max_attempts,
            retry_base_delay=retry_ms / 1_000,
            max_backoff_delay=max_backoff_ms / 1_000,
            environment=environment,
            provider_kind=provider_kind,
        )


def _positive_finite(value: object) -> bool:
    converted = _finite_float(value)
    return converted is not None and converted > 0


def _nonnegative_finite(value: object) -> bool:
    converted = _finite_float(value)
    return converted is not None and converted >= 0


def _finite_float(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except (OverflowError, ValueError, TypeError):
        return None
    return converted if math.isfinite(converted) else None


def _first_value(values: Mapping[str, str], *names: str, default: str) -> str:
    for name in names:
        value = values.get(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _read_float(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        raise ProviderConfigurationError() from None
    if not math.isfinite(parsed) or parsed < 0:
        raise ProviderConfigurationError()
    return parsed


def _read_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        raise ProviderConfigurationError() from None
    return parsed


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_CHAT_MODEL",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_DIMENSIONS",
    "ProviderConfig",
    "ProviderConfigurationError",
]
