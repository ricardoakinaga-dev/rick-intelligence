"""Production configuration only; shared runtime wiring belongs to the Lead."""

from dataclasses import replace

import pytest

from core.config import ApiSettings


@pytest.fixture(autouse=True)
def clear_provider_env(monkeypatch):
    names = ("LLM_PROVIDER", "RICK_PROVIDER", "LLM_BASE_URL", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL",
             "LLM_API_KEY", "EXTERNAL_CHAT_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
             "LLM_MODEL", "OPENAI_CHAT_MODEL", "ANTHROPIC_CHAT_MODEL", "RICK_EMBEDDING_PROVIDER",
             "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY", "ANTHROPIC_MAX_TOKENS", "ANTHROPIC_VERSION", "OPENAI_MAX_ATTEMPTS",
             "OPENAI_RETRY_DELAY_MS", "OPENAI_MAX_BACKOFF_MS")
    for name in names:
        monkeypatch.delenv(name, raising=False)


def production(**overrides):
    values = dict(environment="production", identity_mode="production", session_cookie_secure=True,
                  chat_backend_mode="professor", provider_kind="anthropic", external_chat_api_key="claude-secret",
                  provider_chat_model="claude-opus-5-5", provider_base_url="https://api.anthropic.com/v1",
                  embedding_provider_kind="openai", embedding_base_url="https://api.openai.com/v1",
                  embedding_api_key="embedding-secret", locker_base_url="https://lease.invalid",
                  knowledge_sqlite_path="", vector_sqlite_path="", chat_history_sqlite_path="",
                  clinical_case_sqlite_path="", audit_sqlite_path="", ingestion_journal_path="", ingestion_staging_path="")
    values.update(overrides)
    return ApiSettings(**values)


def test_production_can_select_native_anthropic_and_independent_embeddings():
    settings = production()
    settings.validate()
    assert settings.selected_provider_kind == "anthropic"
    assert "claude-secret" not in repr(settings) and "embedding-secret" not in repr(settings)


@pytest.mark.parametrize("overrides", [
    {"embedding_provider_kind": "", "embedding_base_url": "", "embedding_api_key": ""},
    {"embedding_api_key": ""}, {"embedding_base_url": ""}, {"embedding_provider_kind": "anthropic"},
    {"embedding_base_url": "https://user:embedding-secret@invalid"},
    {"provider_anthropic_version": "version\n"}, {"provider_max_output_tokens": 0},
    {"provider_kind": "deterministic"}, {"provider_chat_model": ""}, {"external_chat_api_key": ""},
])
def test_invalid_production_configuration_is_redacted(overrides):
    with pytest.raises(ValueError) as caught:
        production(**overrides).validate()
    assert "secret" not in str(caught.value)


def test_native_env_resolves_vendor_secrets_without_reusing_openai_chat_settings(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_CHAT_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "independent-openai-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://embedding.invalid/v1")
    monkeypatch.setenv("RICK_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.invalid/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "independent-openai-secret")
    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "8192")
    settings = ApiSettings()
    assert settings.provider_kind == "anthropic"
    assert settings.provider_base_url == "https://api.anthropic.com/v1"
    assert settings.provider_chat_model == "claude-sonnet-5-5"
    assert settings.external_chat_api_key == "claude-secret"
    assert settings.embedding_api_key == "independent-openai-secret"
    assert settings.provider_max_output_tokens == 8192
    monkeypatch.setenv("LLM_MODEL", "conflicting-model")
    with pytest.raises(ValueError, match="Conflicting configuration"):
        ApiSettings()


def test_vendor_key_alias_conflicts_are_redacted(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "different-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-secret")
    with pytest.raises(ValueError) as caught:
        ApiSettings()
    assert "different-secret" not in str(caught.value) and "claude-secret" not in str(caught.value)


def test_existing_openai_production_config_needs_no_new_embedding_fields():
    settings = production(provider_kind="openai", provider_base_url="https://api.openai.com/v1",
                          provider_chat_model="gpt-6-astra", embedding_provider_kind="",
                          embedding_base_url="", embedding_api_key="")
    settings.validate()
    assert settings.selected_provider_kind == "openai"


def test_legacy_openai_env_still_resolves(monkeypatch):
    monkeypatch.setenv("RICK_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-6-astra")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    settings = ApiSettings()
    assert settings.provider_chat_model == "gpt-6-astra" and settings.external_chat_api_key == "openai-secret"
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("EXTERNAL_CHAT_API_KEY", "legacy-secret")
    assert ApiSettings().external_chat_api_key == "legacy-secret"


def test_production_deterministic_is_forbidden_even_with_legacy_chat_backend():
    with pytest.raises(ValueError, match="deterministic"):
        replace(production(), chat_backend_mode="legacy", use_legacy_adapters=True, provider_kind="deterministic").validate()


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_common_retry_env_and_lead_constructor_contract(monkeypatch, kind):
    from rick_providers import ProviderConfig
    monkeypatch.setenv("LLM_PROVIDER", kind)
    monkeypatch.setenv("OPENAI_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("OPENAI_RETRY_DELAY_MS", "1234")
    monkeypatch.setenv("OPENAI_MAX_BACKOFF_MS", "2345")
    settings = ApiSettings()
    assert (settings.provider_max_attempts, settings.provider_retry_delay_ms, settings.provider_max_backoff_ms) == (1, 1234, 2345)
    config = ProviderConfig(environment="test", max_attempts=settings.provider_max_attempts,
                            retry_delay_ms=settings.provider_retry_delay_ms,
                            max_backoff_ms=settings.provider_max_backoff_ms)
    config.validate()
    assert (config.max_attempts, config.retry_base_delay, config.max_backoff_delay) == (1, 1.234, 2.345)


@pytest.mark.parametrize("overrides", [
    {"provider_max_attempts": 0}, {"provider_max_attempts": 11}, {"provider_max_attempts": True},
    {"provider_retry_delay_ms": -1}, {"provider_retry_delay_ms": 120001},
    {"provider_retry_delay_ms": float("nan")}, {"provider_max_backoff_ms": float("inf")},
    {"provider_max_backoff_ms": 120001}, {"provider_max_backoff_ms": -1},
])
def test_retry_settings_safe_bounded_validation(overrides):
    with pytest.raises(ValueError, match="OPENAI_"):
        production(**overrides).validate()


@pytest.mark.parametrize("name", ["OPENAI_MAX_ATTEMPTS", "OPENAI_RETRY_DELAY_MS", "OPENAI_MAX_BACKOFF_MS"])
def test_invalid_retry_environment_is_redacted(monkeypatch, name):
    monkeypatch.setenv(name, "invalid-secret-value")
    with pytest.raises(ValueError) as caught:
        ApiSettings()
    assert name in str(caught.value) and "secret" not in str(caught.value)


@pytest.mark.parametrize("kind", ["openai", "anthropic", "openai_compatible"])
@pytest.mark.parametrize("field", ["provider_base_url", "embedding_base_url"])
def test_production_rejects_plaintext_credential_endpoints(kind, field):
    with pytest.raises(ValueError, match="Invalid provider configuration"):
        production(provider_kind=kind, **{field: "http://remote.invalid/v1"}).validate()


@pytest.mark.parametrize("backend", ["legacy", "professor"])
def test_production_legacy_locker_accepts_explicit_redis_url(backend):
    settings = production(chat_backend_mode=backend, use_legacy_adapters=True,
                          locker_base_url="", redis_url="redis://localhost:6379/0")
    settings.validate()
    if backend == "professor":
        with pytest.raises(ValueError, match="lease service"):
            replace(settings, redis_url="").validate()
