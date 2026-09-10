"""Root typed provider package.

The package exposes a single async OpenAI-compatible HTTP boundary plus an
explicitly non-production deterministic test/dev provider.
"""

from rick_contracts.providers import (
    PROVIDER_CONTRACT_VERSION,
    ChatCompletionChunk,
    ChatCompletionResult,
    EmbeddingResult,
    ProviderErrorCode,
    ProviderErrorDto,
    ProviderMessage,
    ProviderToolCall,
    ProviderToolCallDelta,
    ProviderToolCallDeltaFunction,
    ProviderToolCallFunction,
)

from rick_providers.client import (
    MAX_RESPONSE_BYTES,
    AsyncOpenAICompatibleClient,
    AsyncOpenAIProvider,
    OpenAICompatibleAsyncClient,
    OpenAICompatibleClient,
    OpenAICompatibleProvider,
    OpenAIProvider,
)
from rick_providers.config import (
    DEFAULT_BASE_URL,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    ProviderConfig,
    ProviderConfigurationError,
)
from rick_providers.deterministic import (
    DeterministicDevProvider,
    DeterministicProvider,
    DeterministicTestProvider,
)
from rick_providers.errors import (
    RETRYABLE_ERROR_CODES,
    ProviderError,
    ProviderOperation,
    is_provider_error,
    provider_error,
    summarize_provider_error,
)
from rick_providers.factory import build_provider, create_provider, provider_from_config, provider_from_env
from rick_providers.protocols import AsyncProvider, Provider
from rick_providers.resilience import ProviderBudgetError, ResilientProvider

__all__ = [
    "PROVIDER_CONTRACT_VERSION",
    "ProviderMessage",
    "ProviderErrorCode",
    "ProviderErrorDto",
    "EmbeddingResult",
    "ProviderToolCall",
    "ProviderToolCallFunction",
    "ProviderToolCallDelta",
    "ProviderToolCallDeltaFunction",
    "ChatCompletionChunk",
    "ChatCompletionResult",
    "ProviderConfig",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderOperation",
    "RETRYABLE_ERROR_CODES",
    "provider_error",
    "is_provider_error",
    "summarize_provider_error",
    "AsyncProvider",
    "Provider",
    "ProviderBudgetError",
    "ResilientProvider",
    "MAX_RESPONSE_BYTES",
    "OpenAICompatibleClient",
    "AsyncOpenAICompatibleClient",
    "AsyncOpenAIProvider",
    "OpenAICompatibleAsyncClient",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "DeterministicProvider",
    "DeterministicDevProvider",
    "DeterministicTestProvider",
    "create_provider",
    "build_provider",
    "provider_from_config",
    "provider_from_env",
    "DEFAULT_BASE_URL",
    "DEFAULT_CHAT_MODEL",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_DIMENSIONS",
]
