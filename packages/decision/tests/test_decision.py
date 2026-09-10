"""Focused tests for deterministic and conservative DecisionLayer behavior."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[3]
for _package in ("evidence", "decision"):
    _source = str(_ROOT / "packages" / _package / "src")
    if _source not in sys.path:
        sys.path.insert(0, _source)

from rick_decision import (  # noqa: E402
    CitationSupportMetrics,
    DecisionAction,
    DecisionInput,
    DecisionLayer,
    DecisionPolicy,
    DomainRisk,
    IntentClarity,
    UserIntent,
)
from rick_evidence import EvidenceScope, EvidenceValidator  # noqa: E402


def _bundle():
    scope = EvidenceScope(tenant_id="tenant-a", workspace_id="workspace-a", collection_id="collection-a")
    return EvidenceValidator().build_bundle(
        query="What does the source say?",
        scope=scope,
        candidates=[{
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "collection_id": "collection-a",
            "document_id": "document-a",
            "document_version": "version-1",
            "chunk_id": "chunk-a-0001",
            "source": "source.txt",
            "checksum": "sha256:fixture",
            "text": "The source records a bounded fact.",
            "score": 0.9,
            "reranking_score": 0.8,
        }],
    )


def _input(**overrides):
    bundle = overrides.pop("evidence_bundle", _bundle())
    values = {
        "evidence_bundle": bundle,
        "evidence_count": len(bundle.evidence),
        "retrieval_quality": 0.90,
        "citation_support": 0.90,
        "provider_confidence_signal": 0.90,
        "domain_risk": DomainRisk.LOW,
        "user_intent": UserIntent(intent_code="source_question", clarity=IntentClarity.CLEAR),
    }
    values.update(overrides)
    return DecisionInput(**values)


def test_answer_is_the_only_success_path_and_is_repeatable() -> None:
    layer = DecisionLayer()
    request = _input(cited_evidence_ids=[_bundle().evidence[0].evidence_id])
    first = layer.decide(request)
    second = layer.decide(request)

    assert first.action is DecisionAction.ANSWER
    assert first.evidence_bundle_id == request.evidence_bundle.bundle_id
    assert first.model_dump() == second.model_dump()
    assert not first.retry_allowed


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"domain_risk": DomainRisk.HIGH}, DecisionAction.ESCALATE),
        ({"domain_risk": DomainRisk.UNKNOWN}, DecisionAction.ESCALATE),
        ({"human_review_required": True}, DecisionAction.ESCALATE),
        ({"user_intent": UserIntent(clarity=IntentClarity.AMBIGUOUS)}, DecisionAction.ASK_FOR_CLARIFICATION),
        ({"user_intent": UserIntent(clarity=IntentClarity.UNSUPPORTED)}, DecisionAction.ABSTAIN),
        ({"policy_allows_answer": False}, DecisionAction.ABSTAIN),
        ({"provider_confidence_signal": None}, DecisionAction.ABSTAIN),
    ],
)
def test_conservative_precedence(overrides, expected) -> None:
    assert DecisionLayer().decide(_input(**overrides)).action is expected


def test_weak_evidence_retries_once_then_abstains() -> None:
    layer = DecisionLayer()
    retry = layer.decide(_input(retrieval_quality=0.10, retrieval_attempt=0))
    exhausted = layer.decide(_input(retrieval_quality=0.10, retrieval_attempt=1))

    assert retry.action is DecisionAction.RETRIEVE_AGAIN
    assert retry.retry_allowed
    assert exhausted.action is DecisionAction.ABSTAIN


def test_unknown_or_duplicate_citations_never_answer() -> None:
    bundle = _bundle()
    identifier = bundle.evidence[0].evidence_id
    unknown = DecisionLayer().decide(_input(cited_evidence_ids=["ev_" + "f" * 32]))
    duplicate = DecisionLayer().decide(_input(cited_evidence_ids=[identifier, identifier]))

    assert unknown.action is DecisionAction.ABSTAIN
    assert duplicate.action is DecisionAction.ABSTAIN
    assert unknown.reason_code == "citation_registry_invalid"


def test_scope_is_revalidated_at_the_decision_seam() -> None:
    bundle = _bundle()
    with pytest.raises(ValidationError):
        _input(
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            collection_id="collection-other",
            evidence_bundle=bundle,
        )


def test_policy_can_explicitly_allow_medium_risk_but_never_unknown_by_default() -> None:
    policy = DecisionPolicy(answerable_risk_levels=(DomainRisk.LOW, DomainRisk.MEDIUM))
    medium = DecisionLayer().decide(_input(domain_risk=DomainRisk.MEDIUM, policy=policy))
    unknown = DecisionLayer().decide(_input(domain_risk=DomainRisk.UNKNOWN, policy=policy))

    assert medium.action is DecisionAction.ANSWER
    assert unknown.action is DecisionAction.ESCALATE


def _citation_metrics(**overrides):
    values = {
        "status": "PASS",
        "citation_precision": 1.0,
        "citation_recall": 1.0,
        "citation_completeness": 1.0,
        "unsupported_claim_rate": 0.0,
        "evaluated_claims": 1,
        "source": "approved_claim_support",
    }
    values.update(overrides)
    return CitationSupportMetrics(**values)


def test_strict_policy_requires_observed_citation_support_metrics() -> None:
    policy = DecisionPolicy(
        require_citation_support_metrics=True,
        required_citation_support_source="approved_claim_support",
        max_retrieval_attempts=0,
    )

    decision = DecisionLayer().decide(_input(policy=policy, citation_support=1.0))

    assert decision.action is DecisionAction.ABSTAIN
    assert decision.reason_code.startswith("citation_support_metrics_missing")


def test_strict_policy_consumes_all_citation_support_metrics() -> None:
    policy = DecisionPolicy(
        require_citation_support_metrics=True,
        required_citation_support_source="approved_claim_support",
        max_retrieval_attempts=0,
    )
    accepted = DecisionLayer().decide(
        _input(policy=policy, citation_support_metrics=_citation_metrics())
    )
    rejected = DecisionLayer().decide(
        _input(
            policy=policy,
            citation_support_metrics=_citation_metrics(
                citation_precision=0.79,
            ),
        )
    )

    assert accepted.action is DecisionAction.ANSWER
    assert rejected.action is DecisionAction.ABSTAIN
    assert rejected.reason_code.startswith("citation_precision_below_minimum")


def test_strict_policy_rejects_inconclusive_and_unsupported_claim_observations() -> None:
    policy = DecisionPolicy(
        require_citation_support_metrics=True,
        required_citation_support_source="approved_claim_support",
        max_retrieval_attempts=0,
    )
    inconclusive = DecisionLayer().decide(
        _input(
            policy=policy,
            citation_support_metrics=_citation_metrics(status="INCONCLUSIVE"),
        )
    )
    unsupported = DecisionLayer().decide(
        _input(
            policy=policy,
            citation_support_metrics=_citation_metrics(unsupported_claim_rate=0.01),
        )
    )

    assert inconclusive.reason_code.startswith("citation_support_metrics_not_pass")
    assert unsupported.reason_code.startswith("unsupported_claim_rate_above_maximum")
    assert inconclusive.action is DecisionAction.ABSTAIN
    assert unsupported.action is DecisionAction.ABSTAIN
