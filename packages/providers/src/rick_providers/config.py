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
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
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
    embedding_provider_kind: str | None = None
    embedding_base_url: str | None = field(default=None, repr=False)
    embedding_api_key: str | None = field(default=None, repr=False)
    anthropic_version: str = "2023-06-01"
    max_output_tokens: int = 4096

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        chat_model: str | None = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
        max_backoff_delay: float = DEFAULT_MAX_BACKOFF_SECONDS,
        environment: str = "production",
        provider_kind: str = "openai",
        embedding_provider_kind: str | None = None,
        embedding_base_url: str | None = None,
        embedding_api_key: str | None = None,
        anthropic_version: str = "2023-06-01",
        max_output_tokens: int = 4096,
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
        retry_delay_ms: float | None = None,
        max_backoff_ms: float | None = None,
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
        if retry_delay_ms is not None:
            if _finite_float(retry_delay_ms) is None:
                raise ProviderConfigurationError()
            retry_base_delay = retry_delay_ms / 1_000
        if max_backoff_ms is not None:
            if _finite_float(max_backoff_ms) is None:
                raise ProviderConfigurationError()
            max_backoff_delay = max_backoff_ms / 1_000
        if embedding_dimension is not None:
            embedding_dimensions = embedding_dimension

        kind = provider_kind.strip().lower() if isinstance(provider_kind, str) else provider_kind
        if base_url is None:
            base_url = DEFAULT_ANTHROPIC_BASE_URL if kind == "anthropic" else DEFAULT_BASE_URL
        if chat_model is None:
            chat_model = "" if kind == "anthropic" else DEFAULT_CHAT_MODEL
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
        object.__setattr__(self, "embedding_provider_kind", embedding_provider_kind.strip().lower() if isinstance(embedding_provider_kind, str) else embedding_provider_kind)
        object.__setattr__(self, "embedding_base_url", embedding_base_url.strip() if isinstance(embedding_base_url, str) else embedding_base_url)
        object.__setattr__(self, "embedding_api_key", embedding_api_key.strip() or None if isinstance(embedding_api_key, str) else embedding_api_key)
        object.__setattr__(self, "anthropic_version", anthropic_version)
        object.__setattr__(self, "max_output_tokens", max_output_tokens)

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

        if self.api_key is not None and (not isinstance(self.api_key, str) or not _header_value(self.api_key)):
            raise ProviderConfigurationError()
        if not isinstance(self.environment, str) or not self.environment:
            raise ProviderConfigurationError()
        if self.provider_kind not in {"openai", "openai_compatible", "anthropic", "deterministic"}:
            raise ProviderConfigurationError()
        if self.provider_kind == "deterministic" and not self.is_test_or_dev:
            raise ProviderConfigurationError()
        if not self.is_test_or_dev and parsed.scheme != "https":
            raise ProviderConfigurationError()
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 128_000:
            raise ProviderConfigurationError()
        if not isinstance(self.anthropic_version, str) or not _header_value(self.anthropic_version):
            raise ProviderConfigurationError()
        explicit_embeddings = any(value is not None for value in (
            self.embedding_provider_kind, self.embedding_base_url, self.embedding_api_key,
        ))
        if explicit_embeddings:
            if self.embedding_provider_kind not in {"openai", "openai_compatible"} or not self.embedding_base_url:
                raise ProviderConfigurationError()
            ProviderConfig(base_url=self.embedding_base_url, api_key=self.embedding_api_key,
                           provider_kind=self.embedding_provider_kind,
                           environment=self.environment).validate()
        if self.provider_kind == "anthropic":
            if not isinstance(self.chat_model, str) or not self.chat_model.strip():
                raise ProviderConfigurationError()
            if self.is_production and (not self.api_key or not explicit_embeddings or not self.embedding_api_key):
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
        if not _nonnegative_finite(self.retry_base_delay) or self.retry_base_delay > 120:
            raise ProviderConfigurationError()
        if not _nonnegative_finite(self.max_backoff_delay) or self.max_backoff_delay > 120:
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
        provider_kind = _read_alias(values, "LLM_PROVIDER", "RICK_PROVIDER", default=_first_value(
            values,
            "RICK_PROVIDER",
            "RICK_PROVIDER_KIND",
            "RICK_PROVIDER_MODE",
            default="openai",
        ), provider=True)
        anthropic = provider_kind.lower() == "anthropic"
        vendor_key_name = "ANTHROPIC_API_KEY" if anthropic else "OPENAI_API_KEY"
        api_key = _read_alias(values, "LLM_API_KEY", "EXTERNAL_CHAT_API_KEY", default="")
        vendor_key = values.get(vendor_key_name, "")
        if api_key.strip() and vendor_key.strip() and api_key != vendor_key:
            raise ProviderConfigurationError()
        return cls(
            base_url=_read_alias(values, "LLM_BASE_URL", "ANTHROPIC_BASE_URL" if anthropic else "OPENAI_BASE_URL", default=DEFAULT_ANTHROPIC_BASE_URL if anthropic else DEFAULT_BASE_URL),
            api_key=api_key if api_key.strip() else vendor_key,
            chat_model=_read_alias(values, "LLM_MODEL", "ANTHROPIC_CHAT_MODEL" if anthropic else "OPENAI_CHAT_MODEL", default="" if anthropic else DEFAULT_CHAT_MODEL),
            embedding_model=_read_alias(values, "EMBEDDING_MODEL", "OPENAI_EMBEDDING_MODEL", default=DEFAULT_EMBEDDING_MODEL),
            embedding_dimensions=dimensions,
            timeout_ms=timeout_ms,
            max_attempts=max_attempts,
            retry_base_delay=retry_ms / 1_000,
            max_backoff_delay=max_backoff_ms / 1_000,
            environment=environment,
            provider_kind=provider_kind,
            embedding_provider_kind=values.get("RICK_EMBEDDING_PROVIDER") or None,
            embedding_base_url=values.get("EMBEDDING_BASE_URL") or None,
            embedding_api_key=values.get("EMBEDDING_API_KEY") or None,
            anthropic_version=_first_value(values, "ANTHROPIC_VERSION", default="2023-06-01"),
            max_output_tokens=_read_int(values, "ANTHROPIC_MAX_TOKENS", 4096),
        )


def _header_value(value: str) -> bool:
    return bool(value) and len(value) <= 4096 and all(0x21 <= ord(char) <= 0x7e for char in value)


def _read_alias(values: Mapping[str, str], current: str, legacy: str, *, default: str, provider: bool = False) -> str:
    first, second = values.get(current, ""), values.get(legacy, "")
    normalize = (lambda value: value.strip().lower().replace("-", "_")) if provider else (lambda value: value)
    if first.strip() and second.strip() and normalize(first) != normalize(second):
        raise ProviderConfigurationError()
    return normalize(first if first.strip() else second if second.strip() else default)


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
    "DEFAULT_ANTHROPIC_BASE_URL",
    "DEFAULT_CHAT_MODEL",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_DIMENSIONS",
    "ProviderConfig",
    "ProviderConfigurationError",
]
