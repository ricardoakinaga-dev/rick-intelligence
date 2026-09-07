"""Owner-safe lease contracts for local and HTTP-backed lock implementations."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from rick_contracts.base import StrictContractModel

LOCKING_CONTRACT_VERSION = "locking-contract-v1"


class LeaseRequest(StrictContractModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[LOCKING_CONTRACT_VERSION] = LOCKING_CONTRACT_VERSION
    key: str = Field(min_length=1, max_length=512)
    owner: str = Field(min_length=1, max_length=256)
    ttl_ms: int = Field(gt=0, le=3_600_000)


class LeaseResult(StrictContractModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[LOCKING_CONTRACT_VERSION] = LOCKING_CONTRACT_VERSION
    operation: Literal["acquire", "renew", "release"]
    key: str = Field(min_length=1, max_length=512)
    acquired: bool | None = None
    renewed: bool | None = None
    released: bool | None = None
    correlation_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def operation_outcome(self) -> "LeaseResult":
        fields = {
            "acquire": self.acquired,
            "renew": self.renewed,
            "release": self.released,
        }
        expected = fields[self.operation]
        if expected is None:
            raise ValueError(f"{self.operation} result is required")
        if any(value is not None for name, value in fields.items() if name != self.operation):
            raise ValueError("lease result may contain only the operation outcome")
        return self


class LeaseErrorDto(StrictContractModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[LOCKING_CONTRACT_VERSION] = LOCKING_CONTRACT_VERSION
    code: Literal["unavailable", "timeout", "not_owner", "invalid_request", "cancelled", "internal_error"]
    operation: Literal["acquire", "renew", "release"]
    correlation_id: str = Field(min_length=1, max_length=128)
