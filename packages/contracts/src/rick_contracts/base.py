"""Shared validation policy for every public contract DTO."""

from pydantic import BaseModel, ConfigDict


class StrictContractModel(BaseModel):
    """Reject unknown fields and implicit scalar coercion at contract edges."""

    model_config = ConfigDict(extra="forbid", strict=True)
