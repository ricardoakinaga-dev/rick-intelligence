"""Root Professor application contract built on retrieval evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from rick_contracts.chat import Citation
from rick_contracts.base import StrictContractModel
from rick_contracts.rag import EvidenceDto
from rick_contracts.security import RetrievalContext

PROFESSOR_CONTRACT_VERSION = "professor-contract-v1"
EvidenceStatus = Literal[
    "NO_EVIDENCE",
    "WEAK_EVIDENCE",
    "APPROVED_EVIDENCE",
    "CITATION_INVALID",
    "GENERATION_FAILED",
]


class ProfessorRequest(StrictContractModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[PROFESSOR_CONTRACT_VERSION] = PROFESSOR_CONTRACT_VERSION
    query: str = Field(min_length=1, max_length=20_000)
    conversation_id: str = Field(min_length=1, max_length=128)
    retrieval_context: RetrievalContext
    mode: str = Field(default="grounded", min_length=1, max_length=32)


class ProfessorResponse(StrictContractModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[PROFESSOR_CONTRACT_VERSION] = PROFESSOR_CONTRACT_VERSION
    conversation_id: str = Field(min_length=1, max_length=128)
    answer: str = Field(min_length=1, max_length=1_000_000)
    evidence_status: EvidenceStatus
    citations: list[Citation] = Field(default_factory=list)
    evidence: list[EvidenceDto] = Field(default_factory=list, max_length=20)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=32)
