"""Deterministic conservative implementation of the DecisionLayer contract."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from rick_evidence import EvidenceValidator

from rick_decision.contracts import (
    Decision,
    DecisionAction,
    DecisionInput,
    DomainRisk,
    IntentClarity,
)


_MESSAGES = {
    DecisionAction.ANSWER: "The available evidence passed the configured grounding checks.",
    DecisionAction.RETRIEVE_AGAIN: "The available evidence did not pass grounding checks; retrieve authorized evidence again.",
    DecisionAction.ASK_FOR_CLARIFICATION: "Please clarify the request before a grounded answer is generated.",
    DecisionAction.ABSTAIN: "The available evidence is insufficient for a grounded answer.",
    DecisionAction.ESCALATE: "This request requires additional review before an answer is generated.",
}


@runtime_checkable
class DecisionLayerProtocol(Protocol):
    """Typed integration seam for a synchronous decision implementation."""

    def decide(self, decision_input: DecisionInput) -> Decision:
        """Return exactly one of the five declared decision actions."""


class DecisionLayer:
    """Default deterministic policy implementation.

    Evaluation order is intentionally fixed: input/evidence integrity, human
    review and risk, intent, policy, evidence sufficiency, citation registry,
    and provider signal.  Risk and integrity gates take precedence over all
    answer-oriented signals.  No signal is interpreted as a calibrated
    probability.
    """

    def __init__(self, *, evidence_validator: EvidenceValidator | None = None) -> None:
        self._evidence_validator = evidence_validator or EvidenceValidator()

    def _make(
        self,
        decision_input: DecisionInput,
        action: DecisionAction,
        reason_code: str,
        *,
        evidence_bundle_id: str | None = None,
    ) -> Decision:
        return Decision(
            action=action,
            reason_code=reason_code,
            message=_MESSAGES[action],
            evidence_bundle_id=evidence_bundle_id,
            retrieval_attempt=decision_input.retrieval_attempt,
            retry_allowed=action is DecisionAction.RETRIEVE_AGAIN,
            requires_clarification=action is DecisionAction.ASK_FOR_CLARIFICATION,
            requires_human_review=action is DecisionAction.ESCALATE,
        )

    def _retry_or_abstain(self, decision_input: DecisionInput, reason_code: str) -> Decision:
        policy = decision_input.policy
        if (
            decision_input.retrieval_available
            and decision_input.retrieval_attempt < policy.max_retrieval_attempts
        ):
            return self._make(decision_input, DecisionAction.RETRIEVE_AGAIN, reason_code)
        return self._make(
            decision_input,
            DecisionAction.ABSTAIN,
            f"{reason_code}_exhausted" if len(reason_code) <= 54 else "evidence_insufficient",
        )

    def decide(self, decision_input: DecisionInput) -> Decision:
        """Evaluate one validated input without I/O or nondeterministic state."""

        if not isinstance(decision_input, DecisionInput):
            raise TypeError("decision_input must be DecisionInput")

        bundle = decision_input.evidence_bundle
        bundle_id = bundle.bundle_id if bundle is not None else None

        if not decision_input.integrity_ok:
            return self._make(decision_input, DecisionAction.ESCALATE, "input_integrity_failed", evidence_bundle_id=bundle_id)
        if bundle is None and decision_input.evidence_count > 0:
            return self._make(decision_input, DecisionAction.ESCALATE, "evidence_bundle_missing")
        if bundle is not None:
            report = self._evidence_validator.validate_bundle(
                bundle,
                expected_scope=decision_input.request_scope,
            )
            if not report.valid:
                return self._make(decision_input, DecisionAction.ESCALATE, "evidence_validation_failed", evidence_bundle_id=bundle_id)

        if decision_input.human_review_required:
            return self._make(decision_input, DecisionAction.ESCALATE, "human_review_required", evidence_bundle_id=bundle_id)

        risk = decision_input.domain_risk
        if risk not in decision_input.policy.answerable_risk_levels:
            reason = "risk_unknown" if risk is DomainRisk.UNKNOWN else "risk_requires_review"
            return self._make(decision_input, DecisionAction.ESCALATE, reason, evidence_bundle_id=bundle_id)

        intent = decision_input.user_intent
        if intent.clarity in (IntentClarity.UNKNOWN, IntentClarity.AMBIGUOUS):
            return self._make(decision_input, DecisionAction.ASK_FOR_CLARIFICATION, "intent_needs_clarification", evidence_bundle_id=bundle_id)
        if intent.clarity is IntentClarity.UNSUPPORTED:
            return self._make(decision_input, DecisionAction.ABSTAIN, "intent_unsupported", evidence_bundle_id=bundle_id)

        if not decision_input.policy_allows_answer:
            return self._make(decision_input, DecisionAction.ABSTAIN, "policy_denied", evidence_bundle_id=bundle_id)

        if bundle is None:
            return self._retry_or_abstain(decision_input, "evidence_bundle_missing")
        if decision_input.evidence_count < decision_input.policy.min_evidence_count:
            return self._retry_or_abstain(decision_input, "evidence_count_below_minimum")
        if decision_input.retrieval_quality < decision_input.policy.min_retrieval_quality:
            return self._retry_or_abstain(decision_input, "retrieval_quality_below_minimum")

        if decision_input.cited_evidence_ids is not None:
            citation_report = self._evidence_validator.validate_citations(
                bundle,
                decision_input.cited_evidence_ids,
            )
            if not citation_report.valid:
                return self._make(decision_input, DecisionAction.ABSTAIN, "citation_registry_invalid", evidence_bundle_id=bundle_id)
        if decision_input.citation_support < decision_input.policy.min_citation_support:
            return self._retry_or_abstain(decision_input, "citation_support_below_minimum")

        provider_signal = decision_input.provider_confidence_signal
        if provider_signal is None:
            return self._make(decision_input, DecisionAction.ABSTAIN, "provider_signal_missing", evidence_bundle_id=bundle_id)
        if provider_signal < decision_input.policy.min_provider_confidence_signal:
            return self._make(decision_input, DecisionAction.ABSTAIN, "provider_signal_below_minimum", evidence_bundle_id=bundle_id)

        return self._make(decision_input, DecisionAction.ANSWER, "grounded_evidence", evidence_bundle_id=bundle_id)

    evaluate = decide


# Explicit names make the implementation choice discoverable while retaining
# one behavior and one contract.
DeterministicDecisionLayer = DecisionLayer
ConservativeDecisionLayer = DecisionLayer


__all__ = [
    "ConservativeDecisionLayer",
    "DecisionLayer",
    "DecisionLayerProtocol",
    "DeterministicDecisionLayer",
]
