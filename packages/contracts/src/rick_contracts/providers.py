"""Provider boundary contracts shared by the root runtime.

These DTOs intentionally contain only safe, client-independent data. Provider
implementations must never serialize response bodies, URLs, credentials or
exception causes into a public error.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from rick_contracts.base import StrictContractModel

PROVIDER_CONTRACT_VERSION = "provider-contract-v1"

ProviderErrorCode = Literal[
    "timeout",
    "unavailable",
    "rate_limit",
    "server_error",
    "malformed_response",
    "missing_field",
    "invalid_json",
    "invalid_model",
    "embedding_dimension_mismatch",
    "model_not_found",
    "http_error",
    "invalid_configuration",
    "cancelled",
    "internal_error",
]


class ProviderMessage(StrictContractModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=1_000_000)


class ProviderErrorDto(StrictContractModel):
    """Safe provider failure metadata; no raw cause or response payload."""

    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[PROVIDER_CONTRACT_VERSION] = PROVIDER_CONTRACT_VERSION
    code: ProviderErrorCode
    operation: Literal["chat_completion", "embeddings"]
    correlation_id: str = Field(min_length=1, max_length=128)
    attempts: int = Field(ge=0, le=10)
    retryable: bool
    status: int | None = Field(default=None, ge=100, le=599)


class EmbeddingResult(StrictContractModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[PROVIDER_CONTRACT_VERSION] = PROVIDER_CONTRACT_VERSION
    model: str = Field(min_length=1, max_length=256)
    dimensions: int = Field(gt=0, le=16_384)
    vector: list[float] = Field(min_length=1, max_length=16_384)
    correlation_id: str = Field(min_length=1, max_length=128)

    @field_validator("vector")
    @classmethod
    def finite_vector(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(item) for item in value):
            raise ValueError("embedding vector must contain finite values")
        return value

    @model_validator(mode="after")
    def exact_dimension(self) -> "EmbeddingResult":
        if len(self.vector) != self.dimensions:
            raise ValueError("embedding vector dimension mismatch")
        return self


class ProviderUsage(StrictContractModel):
    """Optional bounded usage counters from a provider response."""

    model_config = ConfigDict(extra="forbid", strict=True)

    prompt_tokens: int = Field(ge=0, le=10_000_000)
    completion_tokens: int = Field(ge=0, le=10_000_000)
    total_tokens: int = Field(ge=0, le=20_000_000)


class ChatCompletionResult(StrictContractModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[PROVIDER_CONTRACT_VERSION] = PROVIDER_CONTRACT_VERSION
    model: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=1_000_000)
    finish_reason: Literal["stop", "length", "content_filter", "unknown"] = "stop"
    correlation_id: str = Field(min_length=1, max_length=128)
    usage: ProviderUsage | None = None


class ChatCompletionChunk(StrictContractModel):
    """One provider-produced incremental chat delta.

    The chunk is deliberately smaller than the final result. Citation
    validation belongs to Professor after the final content is assembled.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[PROVIDER_CONTRACT_VERSION] = PROVIDER_CONTRACT_VERSION
    model: str = Field(min_length=1, max_length=256)
    delta: str = Field(default="", max_length=1_000_000)
    finish_reason: Literal["stop", "length", "content_filter", "unknown"] | None = None
    correlation_id: str = Field(min_length=1, max_length=128)
    usage: ProviderUsage | None = None
