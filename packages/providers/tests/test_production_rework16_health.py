"""Native readiness binds valid metadata to the configured model identity.

Official alias/snapshot semantics are recorded in provider16-health/docs.md.
Every HTTP operation uses MockTransport; fixtures contain synthetic keys only.
"""

import copy

import httpx
import pytest

from rick_providers import AnthropicMessagesClient, ProviderConfig, create_provider


PIN = "claude-sonnet-4-5-20250929"
ALIAS = "claude-sonnet-4-5"


def metadata(model_id=PIN):
    return {
        "id": model_id,
        "type": "model",
        "display_name": "Claude Sonnet 4.5",
        "created_at": "2025-09-29T00:00:00Z",
        "capabilities": None,
        "max_input_tokens": 200_000,
        "max_tokens": 64_000,
    }


async def probe(requested, body):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=copy.deepcopy(body))

    config = ProviderConfig(
        provider_kind="anthropic", environment="production",
        chat_model=requested, api_key="synthetic-test-key", timeout=1,
        max_attempts=1,
        embedding_provider_kind="openai",
        embedding_base_url="https://embedding.invalid/v1",
        embedding_api_key="synthetic-embedding-key",
    )
    async with create_provider(config, transport=httpx.MockTransport(handle)) as provider:
        assert isinstance(provider, AnthropicMessagesClient)
        healthy = await provider.health_check()
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == f"/v1/models/{requested}"
    assert requests[0].headers["anthropic-version"] == "2023-06-01"
    return healthy


@pytest.mark.asyncio
@pytest.mark.parametrize("requested,returned", [
    (PIN, PIN),
    ("claude-sonnet-4-6", "claude-sonnet-4-6"),
    ("claude-sonnet-5-5", "claude-sonnet-5-5"),
    (ALIAS, ALIAS),
    (ALIAS, PIN),
    ("claude-haiku-4-5", "claude-haiku-4-5-20251001"),
])
async def test_native_health_accepts_exact_or_documented_alias(requested, returned):
    assert await probe(requested, metadata(returned)) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("requested,returned", [
    (PIN, "unrelated-model"),
    (PIN, "gpt-4o-mini"),
    (ALIAS, "claude-haiku-4-5-20251001"),
    (ALIAS, "claude-sonnet-4-6"),
    (PIN, "claude-sonnet-4-5-20250930"),
    (PIN, ALIAS),
    ("claude-sonnet-4-6", "claude-sonnet-4-6-20260217"),
    ("claude-sonnet-5-5", "claude-sonnet-5-5-20260928"),
    ("claude-sonnet-4-6", "claude-sonnet-4-7"),
    (ALIAS, "claude-sonnet-4-50-20250929"),
    (ALIAS, "claude-sonnet-4-5-20250929-extra"),
    (ALIAS, "claude-sonnet-4-5-20250230"),
    (ALIAS, "claude-sonnet-4-5-20251301"),
    (ALIAS, "claude-sonnet-4-5-2025092"),
    (ALIAS, "anthropic.claude-sonnet-4-5-20250929-v1:0"),
    (ALIAS, "claude-sonnet-4-5@20250929"),
])
async def test_native_health_rejects_different_or_pinned_mismatches(requested, returned):
    # Well-formed metadata ensures failure is specifically the identity boundary.
    assert await probe(requested, metadata(returned)) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("id", None), ("id", 42), ("id", ""), ("id", " "),
    ("id", PIN + "\n"), ("type", "message"),
    ("display_name", None), ("display_name", 42),
    ("created_at", None), ("created_at", "2025-02-30T00:00:00Z"),
    ("created_at", "2025-09-29"),
    ("max_input_tokens", True), ("max_tokens", -1),
    ("capabilities", []), ("capabilities", {"batch": {"supported": True}}),
    ("error", {"type": "api_error"}),
])
async def test_native_health_rejects_malformed_metadata(field, value):
    body = metadata()
    body[field] = value
    assert await probe(PIN, body) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["id", "type", "display_name", "created_at"])
async def test_native_health_rejects_missing_required_metadata(field):
    body = metadata()
    del body[field]
    assert await probe(PIN, body) is False
