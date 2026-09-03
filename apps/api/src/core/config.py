"""Typed API configuration — single place where env is read and validated."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        raise ValueError(f"Invalid integer for {name}: {raw!r}")


@dataclass(frozen=True)
class ApiSettings:
    app_name: str = "RICK Intelligence API"
    api_version: str = "v1"
    environment: str = field(default_factory=lambda: _get("RICK_ENV", "local"))

    cors_allowed_origins: tuple[str, ...] = ()
    cors_allow_credentials: bool = True

    session_cookie_name: str = field(default_factory=lambda: _get("SESSION_COOKIE_NAME", "rick_session"))
    session_cookie_secure: bool = field(default_factory=lambda: _get_bool("SESSION_COOKIE_SECURE", False))
    session_cookie_samesite: str = field(default_factory=lambda: _get("SESSION_COOKIE_SAMESITE", "lax"))

    max_json_bytes: int = field(default_factory=lambda: _get_int("API_MAX_JSON_BYTES", 1_048_576))
    max_chat_message_chars: int = field(default_factory=lambda: _get_int("API_MAX_CHAT_MESSAGE_CHARS", 20000))
    max_query_chars: int = field(default_factory=lambda: _get_int("API_MAX_QUERY_CHARS", 2000))

    trust_forwarded_headers: bool = field(default_factory=lambda: _get_bool("TRUST_FORWARDED_HEADERS", False))
    trusted_proxies: tuple[str, ...] = ()

    # Secrets enter only via config; never serialized to logs/API.
    external_chat_api_key: str = field(default_factory=lambda: _get("EXTERNAL_CHAT_API_KEY", ""), repr=False)
    compat_api_key: str = field(default_factory=lambda: _get("RICK_COMPAT_API_KEY", "") or _get("PROFESSOR_API_KEY", ""), repr=False)

    use_legacy_adapters: bool = field(default_factory=lambda: _get_bool("RICK_API_USE_LEGACY", False))
    use_legacy_health_checks: bool = field(default_factory=lambda: _get_bool("RICK_API_LEGACY_HEALTH", False))

    identity_mode: str = field(default_factory=lambda: (_get("RICK_IDENTITY_MODE", "dev") or "dev").strip().lower())

    login_rate_limit_per_min: int = field(default_factory=lambda: _get_int("LOGIN_RATE_LIMIT_PER_MIN", 10))
    chat_rate_limit_per_min: int = field(default_factory=lambda: _get_int("CHAT_RATE_LIMIT_PER_MIN", 30))

    @classmethod
    def from_env(cls) -> "ApiSettings":
        origins = tuple(o.strip() for o in _get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip())
        proxies = tuple(p.strip() for p in _get("TRUSTED_PROXIES", "").split(",") if p.strip())
        settings = cls(cors_allowed_origins=origins, trusted_proxies=proxies)
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.max_json_bytes <= 0 or self.max_json_bytes > 50 * 1024 * 1024:
            raise ValueError("API_MAX_JSON_BYTES out of range")
        if self.max_chat_message_chars <= 0 or self.max_chat_message_chars > 100000:
            raise ValueError("API_MAX_CHAT_MESSAGE_CHARS out of range")
        if self.session_cookie_samesite not in {"lax", "strict", "none"}:
            raise ValueError("SESSION_COOKIE_SAMESITE must be lax|strict|none")
        if self.cors_allow_credentials and "*" in self.cors_allowed_origins:
            raise ValueError("Wildcard CORS origin cannot be combined with credentials")
        if self.identity_mode not in {"test", "dev", "production"}:
            raise ValueError("RICK_IDENTITY_MODE must be test|dev|production")
