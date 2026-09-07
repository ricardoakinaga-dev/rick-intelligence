"""Typed API configuration — single place where env is read and validated."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
import ipaddress
from urllib.parse import urlsplit


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


_ENVIRONMENT_ALIASES = {
    "local": "local",
    "dev": "dev",
    "development": "dev",
    "test": "test",
    "testing": "test",
    "production": "production",
    "prod": "production",
    "live": "production",
}


def normalize_environment(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("RICK_ENV must be local|dev|test|production")
    normalized = _ENVIRONMENT_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValueError("RICK_ENV must be local|dev|test|production")
    return normalized


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
    csrf_token: str = field(default_factory=lambda: _get("CSRF_TOKEN", ""), repr=False)
    csrf_header_name: str = field(default_factory=lambda: _get("CSRF_HEADER_NAME", "X-CSRF-Token"))

    max_json_bytes: int = field(default_factory=lambda: _get_int("API_MAX_JSON_BYTES", 1_048_576))
    max_upload_bytes: int = field(default_factory=lambda: _get_int("API_MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
    max_chat_message_chars: int = field(default_factory=lambda: _get_int("API_MAX_CHAT_MESSAGE_CHARS", 20000))
    max_query_chars: int = field(default_factory=lambda: _get_int("API_MAX_QUERY_CHARS", 2000))
    max_pending_ingestion_jobs: int = field(default_factory=lambda: _get_int("INGESTION_MAX_PENDING_JOBS", 64))

    trust_forwarded_headers: bool = field(default_factory=lambda: _get_bool("TRUST_FORWARDED_HEADERS", False))
    trusted_proxies: tuple[str, ...] = ()

    # Secrets enter only via config; never serialized to logs/API.
    external_chat_api_key: str = field(default_factory=lambda: _get("EXTERNAL_CHAT_API_KEY", ""), repr=False)
    compat_api_key: str = field(default_factory=lambda: _get("RICK_COMPAT_API_KEY", "") or _get("PROFESSOR_API_KEY", ""), repr=False)
    compat_workspace_id: str = field(default_factory=lambda: (_get("RICK_COMPAT_WORKSPACE_ID", "default") or "default").strip())
    compat_allowed_collection_ids: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            item.strip() for item in (_get("RICK_COMPAT_COLLECTION_IDS", "rag_phase0")).split(",") if item.strip()
        )
    )

    use_legacy_adapters: bool = field(default_factory=lambda: _get_bool("RICK_API_USE_LEGACY", False))
    use_legacy_health_checks: bool = field(default_factory=lambda: _get_bool("RICK_API_LEGACY_HEALTH", False))

    identity_mode: str = field(default_factory=lambda: (_get("RICK_IDENTITY_MODE", "dev") or "dev").strip().lower())

    # One canonical chat backend selector.  `stub` is hermetic local plumbing;
    # `professor` is the root grounded path; `legacy` is an explicit rollback.
    chat_backend_mode: str = field(default_factory=lambda: (_get("RICK_API_CHAT_BACKEND", "stub") or "stub").strip().lower())
    provider_kind: str = field(default_factory=lambda: (_get("RICK_PROVIDER", "") or "").strip().lower())
    provider_base_url: str = field(default_factory=lambda: _get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    provider_chat_model: str = field(default_factory=lambda: _get("OPENAI_CHAT_MODEL", "gpt-4o-mini"))
    provider_embedding_model: str = field(default_factory=lambda: _get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    provider_embedding_dimensions: int = field(default_factory=lambda: _get_int("OPENAI_EMBEDDING_DIMENSIONS", 1536))
    provider_timeout_ms: int = field(default_factory=lambda: _get_int("OPENAI_TIMEOUT_MS", 30000))
    locker_base_url: str = field(default_factory=lambda: _get("RICK_LOCKER_BASE_URL", ""))

    login_rate_limit_per_min: int = field(default_factory=lambda: _get_int("LOGIN_RATE_LIMIT_PER_MIN", 10))
    chat_rate_limit_per_min: int = field(default_factory=lambda: _get_int("CHAT_RATE_LIMIT_PER_MIN", 30))
    recovery_rate_limit_per_min: int = field(default_factory=lambda: _get_int("RECOVERY_RATE_LIMIT_PER_MIN", 5))
    knowledge_sqlite_path: str = field(default_factory=lambda: _get("RICK_KNOWLEDGE_SQLITE_PATH", "").strip())
    vector_sqlite_path: str = field(default_factory=lambda: _get("RICK_VECTOR_SQLITE_PATH", "").strip())
    audit_sqlite_path: str = field(default_factory=lambda: _get("RICK_AUDIT_SQLITE_PATH", "").strip())
    audit_retention: int = field(default_factory=lambda: _get_int("RICK_AUDIT_RETENTION", 10000))
    ingestion_journal_path: str = field(default_factory=lambda: _get("RICK_INGESTION_JOURNAL_PATH", "").strip())
    ingestion_staging_path: str = field(default_factory=lambda: _get("RICK_INGESTION_STAGING_PATH", "").strip())
    ingestion_journal_max_rows: int = field(default_factory=lambda: _get_int("RICK_INGESTION_JOURNAL_MAX_ROWS", 256))

    def __post_init__(self) -> None:
        # Normalize aliases before any security gate runs. Otherwise values
        # such as `prod` or `live` could bypass exact `production` checks.
        object.__setattr__(self, "environment", normalize_environment(self.environment))

    @classmethod
    def from_env(cls) -> "ApiSettings":
        origins = tuple(o.strip() for o in _get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip())
        proxies = tuple(p.strip() for p in _get("TRUSTED_PROXIES", "").split(",") if p.strip())
        settings = cls(cors_allowed_origins=origins, trusted_proxies=proxies)
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.environment not in {"local", "dev", "test", "production"}:
            raise ValueError("RICK_ENV must be local|dev|test|production")
        if self.max_json_bytes <= 0 or self.max_json_bytes > 50 * 1024 * 1024:
            raise ValueError("API_MAX_JSON_BYTES out of range")
        if self.max_upload_bytes <= 0 or self.max_upload_bytes > 50 * 1024 * 1024:
            raise ValueError("API_MAX_UPLOAD_BYTES out of range")
        if self.max_pending_ingestion_jobs <= 0 or self.max_pending_ingestion_jobs > 1024:
            raise ValueError("INGESTION_MAX_PENDING_JOBS out of range")
        if self.max_chat_message_chars <= 0 or self.max_chat_message_chars > 100000:
            raise ValueError("API_MAX_CHAT_MESSAGE_CHARS out of range")
        if self.session_cookie_samesite not in {"lax", "strict", "none"}:
            raise ValueError("SESSION_COOKIE_SAMESITE must be lax|strict|none")
        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            raise ValueError("SameSite=None requires a secure session cookie")
        if not self.session_cookie_name or any(ord(char) < 0x21 or ord(char) > 0x7E for char in self.session_cookie_name):
            raise ValueError("SESSION_COOKIE_NAME must be a visible token")
        if not self.csrf_header_name or any(ord(char) < 0x21 or ord(char) > 0x7E for char in self.csrf_header_name):
            raise ValueError("CSRF_HEADER_NAME must be a visible token")
        if self.login_rate_limit_per_min <= 0 or self.login_rate_limit_per_min > 100_000:
            raise ValueError("LOGIN_RATE_LIMIT_PER_MIN out of range")
        if self.chat_rate_limit_per_min <= 0 or self.chat_rate_limit_per_min > 100_000:
            raise ValueError("CHAT_RATE_LIMIT_PER_MIN out of range")
        if self.recovery_rate_limit_per_min <= 0 or self.recovery_rate_limit_per_min > 100_000:
            raise ValueError("RECOVERY_RATE_LIMIT_PER_MIN out of range")
        if len(self.knowledge_sqlite_path) > 512 or "\x00" in self.knowledge_sqlite_path:
            raise ValueError("RICK_KNOWLEDGE_SQLITE_PATH is invalid")
        if len(self.vector_sqlite_path) > 512 or "\x00" in self.vector_sqlite_path:
            raise ValueError("RICK_VECTOR_SQLITE_PATH is invalid")
        if len(self.audit_sqlite_path) > 512 or "\x00" in self.audit_sqlite_path:
            raise ValueError("RICK_AUDIT_SQLITE_PATH is invalid")
        if self.audit_retention <= 0 or self.audit_retention > 1_000_000:
            raise ValueError("RICK_AUDIT_RETENTION out of range")
        for name, value in (
            ("RICK_INGESTION_JOURNAL_PATH", self.ingestion_journal_path),
            ("RICK_INGESTION_STAGING_PATH", self.ingestion_staging_path),
        ):
            if len(value) > 512 or "\x00" in value:
                raise ValueError(f"{name} is invalid")
        if self.ingestion_journal_max_rows <= 0 or self.ingestion_journal_max_rows > 100_000:
            raise ValueError("RICK_INGESTION_JOURNAL_MAX_ROWS out of range")
        if self.cors_allow_credentials and "*" in self.cors_allowed_origins:
            raise ValueError("Wildcard CORS origin cannot be combined with credentials")
        if self.identity_mode not in {"test", "dev", "production"}:
            raise ValueError("RICK_IDENTITY_MODE must be test|dev|production")
        if self.chat_backend_mode not in {"stub", "professor", "legacy"}:
            raise ValueError("RICK_API_CHAT_BACKEND must be stub|professor|legacy")
        if self.provider_kind and self.provider_kind not in {"openai", "openai_compatible", "deterministic"}:
            raise ValueError("RICK_PROVIDER must be openai|openai_compatible|deterministic")
        if self.provider_embedding_dimensions <= 0 or self.provider_embedding_dimensions > 16_384:
            raise ValueError("OPENAI_EMBEDDING_DIMENSIONS out of range")
        if self.provider_timeout_ms <= 0 or self.provider_timeout_ms > 120_000:
            raise ValueError("OPENAI_TIMEOUT_MS out of range")
        if self.chat_backend_mode == "professor":
            try:
                parsed_provider_url = urlsplit(self.provider_base_url)
            except (TypeError, ValueError):
                raise ValueError("OPENAI_BASE_URL is invalid") from None
            if (
                parsed_provider_url.scheme not in {"http", "https"}
                or not parsed_provider_url.netloc
                or parsed_provider_url.username is not None
                or parsed_provider_url.password is not None
                or parsed_provider_url.query
                or parsed_provider_url.fragment
            ):
                raise ValueError("OPENAI_BASE_URL is invalid")
            for field_name, value in (
                ("OPENAI_CHAT_MODEL", self.provider_chat_model),
                ("OPENAI_EMBEDDING_MODEL", self.provider_embedding_model),
            ):
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
                    raise ValueError(f"{field_name} is invalid")
        if not self.compat_workspace_id or len(self.compat_workspace_id) > 128:
            raise ValueError("RICK_COMPAT_WORKSPACE_ID is invalid")
        if not self.compat_allowed_collection_ids or len(self.compat_allowed_collection_ids) > 64:
            raise ValueError("RICK_COMPAT_COLLECTION_IDS must contain a finite non-empty scope")
        if any(not item or len(item) > 128 or item == "*" for item in self.compat_allowed_collection_ids):
            raise ValueError("RICK_COMPAT_COLLECTION_IDS cannot contain wildcard scope")
        for proxy in self.trusted_proxies:
            try:
                ipaddress.ip_network(proxy, strict=False)
            except (TypeError, ValueError):
                raise ValueError("TRUSTED_PROXIES must contain valid IPs or CIDR networks") from None
        if self.environment == "production" and self.chat_backend_mode == "stub" and not self.use_legacy_adapters:
            raise ValueError("production cannot use the stub chat backend")
        if self.environment == "production" and self.identity_mode != "production":
            raise ValueError("production requires RICK_IDENTITY_MODE=production")
        if self.environment == "production" and not self.session_cookie_secure:
            raise ValueError("production requires a secure session cookie")
        if self.environment == "production" and self.knowledge_sqlite_path:
            raise ValueError("production requires an external knowledge store")
        if self.environment == "production" and self.vector_sqlite_path:
            raise ValueError("production requires an external vector store")
        if self.environment == "production" and self.audit_sqlite_path:
            raise ValueError("production requires an external audit store")
        if self.environment == "production" and (self.ingestion_journal_path or self.ingestion_staging_path):
            raise ValueError("production requires an external ingestion queue and object store")
        if self.environment == "production" and self.chat_backend_mode == "professor":
            if not self.external_chat_api_key.strip():
                raise ValueError("production Professor mode requires a provider API key")
            if self.provider_kind == "deterministic":
                raise ValueError("production Professor mode cannot use deterministic provider")
            if not self.locker_base_url.strip():
                raise ValueError("production Professor mode requires a lease service")
