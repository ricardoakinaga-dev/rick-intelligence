# `packages/providers`

Root-owned typed provider boundary for Phase 1.5. `OpenAICompatibleClient`
performs async `POST /chat/completions` and `POST /embeddings` requests and
returns the DTOs from `rick_contracts.providers`. Both operations share
correlation propagation, timeout classification, bounded exponential retry,
response validation, and safe `ProviderError` serialization.

```python
from rick_providers import OpenAICompatibleClient, ProviderConfig

config = ProviderConfig(
    base_url="https://api.openai.com/v1",
    api_key="configured-outside-logs",
    chat_model="gpt-4o-mini",
    embedding_model="text-embedding-3-small",
    embedding_dimensions=1536,
)

async with OpenAICompatibleClient(config) as provider:
    answer = await provider.chat_completion(
        messages=[{"role": "user", "content": "Hello"}],
    )
    vector = await provider.get_embedding("Hello")
```

`DeterministicProvider` is a labeled, non-semantic test/dev double. It can be
selected by `create_provider` only with `provider_kind="deterministic"` and an
explicit `test`, `testing`, `dev`, `development`, or `local` environment; a
production configuration fails closed.
