"""Serialized contracts for the explicit decision layer."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rick_evidence import EvidenceBundle, EvidenceScope


DECISION_CONTRACT_VERSION = "decision-contract-v1"
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class DecisionAction(str, Enum):
    """The only outcomes exposed by the decision layer."""

    ANSWER = "ANSWER"
    RETRIEVE_AGAIN = "RETRIEVE_AGAIN"
    ASK_FOR_CLARIFICATION = "ASK_FOR_CLARIFICATION"
    ABSTAIN = "ABSTAIN"
    ESCALATE = "ESCALATE"


class DomainRisk(str, Enum):
    """Coarse policy input; it is not a diagnosis or a probability."""

    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IntentClarity(str, Enum):
    """Whether a caller has supplied enough intent for grounded handling."""

    UNKNOWN = "UNKNOWN"
    CLEAR = "CLEAR"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"


def _bounded_signal(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between zero and one")
    return value


def _safe_code(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    value = value.strip()
    if _SAFE_CODE.fullmatch(value) is None:
        raise ValueError(f"{name} has an invalid format")
    return value


class UserIntent(_ContractModel):
    """Bounded intent assessment supplied by an upstream request interpreter."""

    intent_code: str = Field(default="unknown", min_length=1, max_length=64)
    clarity: IntentClarity = IntentClarity.UNKNOWN

    @field_validator("intent_code", mode="before")
    @classmethod
    def validate_intent_code(cls, value: object) -> str:
        return _safe_code(value, name="intent_code")


class DecisionPolicy(_ContractModel):
    """Explicit thresholds and risk allowlist used by the deterministic layer."""

    min_evidence_count: int = Field(default=1, ge=1, le=100)
    min_retrieval_quality: float = Field(default=0.65, ge=0.0, le=1.0)
    min_citation_support: float = Field(default=0.80, ge=0.0, le=1.0)
    min_provider_confidence_signal: float = Field(default=0.60, ge=0.0, le=1.0)
    max_retrieval_attempts: int = Field(default=1, ge=0, le=10)
    answerable_risk_levels: tuple[DomainRisk, ...] = (DomainRisk.LOW,)

    @field_validator(
        "min_retrieval_quality",
        "min_citation_support",
        "min_provider_confidence_signal",
        mode="before",
    )
    @classmethod
    def validate_threshold(cls, value: object, info) -> float:
        return _bounded_signal(value, name=info.field_name)

    @field_validator("answerable_risk_levels", mode="before")
    @classmethod
    def normalize_risk_levels(cls, value: object) -> tuple[DomainRisk, ...]:
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, (list, tuple)):
            raise ValueError("answerable_risk_levels must be a sequence")
        return tuple(value)


class DecisionInput(_ContractModel):
    """All signals the policy may inspect for one deterministic decision."""

    contract_version: Literal[DECISION_CONTRACT_VERSION] = DECISION_CONTRACT_VERSION
    evidence_bundle: EvidenceBundle | None = None

    # Optional request scope lets the layer revalidate the bundle against the
    # authenticated caller's scope when the caller has it at this seam.
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=128)
    collection_id: str | None = Field(default=None, min_length=1, max_length=128)

    retrieval_quality: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_count: int = Field(default=0, ge=0, le=100)
    citation_support: float = Field(default=0.0, ge=0.0, le=1.0)
    provider_confidence_signal: float | None = Field(default=None, ge=0.0, le=1.0)
    domain_risk: DomainRisk = DomainRisk.UNKNOWN
    user_intent: UserIntent = Field(default_factory=UserIntent)
    policy: DecisionPolicy = Field(default_factory=DecisionPolicy)

    # Attempts are zero-based: attempt 0 is the first retrieval result.  A
    # policy value of 1 permits one additional retrieval attempt.
    retrieval_attempt: int = Field(default=0, ge=0, le=100)
    retrieval_available: bool = True
    integrity_ok: bool = True
    policy_allows_answer: bool = True
    human_review_required: bool = False
    cited_evidence_ids: tuple[str, ...] | None = None

    @field_validator(
        "retrieval_quality",
        "citation_support",
        "provider_confidence_signal",
        mode="before",
    )
    @classmethod
    def validate_signal(cls, value: object, info) -> float | None:
        if value is None and info.field_name == "provider_confidence_signal":
            return None
        return _bounded_signal(value, name=info.field_name)

    @field_validator("cited_evidence_ids", mode="before")
    @classmethod
    def normalize_citation_ids(cls, value: object) -> tuple[str, ...] | None:
        if value is None:
            return None
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, (list, tuple)):
            raise ValueError("cited_evidence_ids must be a sequence")
        return tuple(value)

    @model_validator(mode="after")
    def validate_scope_and_bundle_count(self) -> "DecisionInput":
        scope_values = (self.tenant_id, self.workspace_id, self.collection_id)
        if any(value is not None for value in scope_values) and not all(value is not None for value in scope_values):
            raise ValueError("decision scope must include tenant, workspace, and collection")
        if self.evidence_bundle is not None:
            if self.evidence_count != len(self.evidence_bundle.evidence):
                raise ValueError("evidence_count must match evidence_bundle")
            if all(value is not None for value in scope_values):
                expected = EvidenceScope(
                    tenant_id=self.tenant_id,
                    workspace_id=self.workspace_id,
                    collection_id=self.collection_id,
                )
                if self.evidence_bundle.scope != expected:
                    raise ValueError("decision scope does not match evidence_bundle")
        if self.cited_evidence_ids is not None and isinstance(self.cited_evidence_ids, (str, bytes, bytearray)):
            raise ValueError("cited_evidence_ids must be a sequence")
        return self

    @property
    def request_scope(self) -> EvidenceScope | None:
        if self.tenant_id is None:
            return None
        return EvidenceScope(
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            collection_id=self.collection_id,
        )


class Decision(_ContractModel):
    """Safe, explicit output of the decision layer."""

    contract_version: Literal[DECISION_CONTRACT_VERSION] = DECISION_CONTRACT_VERSION
    action: DecisionAction
    reason_code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=512)
    evidence_bundle_id: str | None = None
    retrieval_attempt: int = Field(ge=0, le=100)
    retry_allowed: bool = False
    requires_clarification: bool = False
    requires_human_review: bool = False

    @field_validator("reason_code", mode="before")
    @classmethod
    def validate_reason_code(cls, value: object) -> str:
        return _safe_code(value, name="reason_code")

    @model_validator(mode="after")
    def validate_action_flags(self) -> "Decision":
        if self.retry_allowed != (self.action is DecisionAction.RETRIEVE_AGAIN):
            raise ValueError("retry_allowed must match action")
        if self.requires_clarification != (self.action is DecisionAction.ASK_FOR_CLARIFICATION):
            raise ValueError("requires_clarification must match action")
        if self.requires_human_review != (self.action is DecisionAction.ESCALATE):
            raise ValueError("requires_human_review must match action")
        if self.action is DecisionAction.ANSWER and not self.evidence_bundle_id:
            raise ValueError("ANSWER requires an evidence bundle")
        return self

    @property
    def safe_message(self) -> str:
        return self.message

    @property
    def reason(self) -> str:
        return self.reason_code


DecisionRequest = DecisionInput
DecisionResult = Decision
DecisionContext = DecisionInput
DecisionOutput = Decision
RiskLevel = DomainRisk


__all__ = [
    "DECISION_CONTRACT_VERSION",
    "Decision",
    "DecisionAction",
    "DecisionContext",
    "DecisionInput",
    "DecisionOutput",
    "DecisionPolicy",
    "DecisionRequest",
    "DecisionResult",
    "DomainRisk",
    "IntentClarity",
    "RiskLevel",
    "UserIntent",
]
