"""Direct contract checks for the root evidence and decision seam."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
for _package in ("contracts", "evidence", "decision", "professor"):
    source = str(ROOT / "packages" / _package / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
api_source = str(ROOT / "apps" / "api" / "src")
if api_source not in sys.path:
    sys.path.insert(0, api_source)

import pytest

from services.professor_backend import EvidenceDecisionGate  # noqa: E402


def _context() -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "allowed_collection_ids": ["collection-a"],
    }


def _candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "evidence_id": "ev-caller-controlled",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "collection_id": "collection-a",
        "document_id": "document-a",
        "document_version": "version-a",
        "chunk_id": "chunk-a",
        "source": "manual.txt",
        "checksum": "sha256:abc123",
        "text": "A bounded source excerpt supports the requested answer.",
        "retrieval_quality_score": 0.95,
        "reranking_score": 0.90,
    }
    candidate.update(overrides)
    return candidate


class _Retrieval:
    def __init__(self, evidence: list[dict[str, object]], metadata: dict[str, object] | None = None) -> None:
        self.evidence = evidence
        self.metadata = metadata or {"backend": "test"}
        self.calls = 0

    async def retrieve(self, *, query: str, context: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        return {"evidence": list(self.evidence), "metadata": dict(self.metadata)}


@pytest.mark.parametrize("permissions,expected", [(["*"], True), (["chat.query"], True), ([], False), (["sources.read"], False)])
@pytest.mark.parametrize("use_callback", [True, False])
def test_publication_revalidation_uses_canonical_wildcard(permissions, expected, use_callback):
    context = {**_context(), "user_id": "u", "permissions": permissions}
    gate = EvidenceDecisionGate(
        _Retrieval([]), knowledge=_CanonicalKnowledge(),
        authorization_revalidator=(lambda *, context: context) if use_callback else None,
    )
    evidence, _, _ = gate._issue_candidates(
        query="synthetic query", context=context, candidates=[_candidate()],
    )
    assert len(evidence) == 1
    result = asyncio.run(gate.validate_publication(
        context=context, evidence=evidence, cited_evidence_ids=[evidence[0]["evidence_id"]],
    ))
    assert result is expected


def test_publication_callback_cannot_grant_originally_empty_permissions():
    context = {**_context(), "user_id": "u", "permissions": []}
    gate = EvidenceDecisionGate(
        _Retrieval([]), knowledge=_CanonicalKnowledge(),
        authorization_revalidator=lambda *, context: {**context, "permissions": ["chat.query"]},
    )
    evidence, _, _ = gate._issue_candidates(query="query", context=context, candidates=[_candidate()])
    assert asyncio.run(gate.validate_publication(
        context=context, evidence=evidence, cited_evidence_ids=[evidence[0]["evidence_id"]],
    )) is False


class _CanonicalKnowledge:
    class Document:
        tenant_id = "tenant-a"
        workspace_id = "workspace-a"
        collection_id = "collection-a"
        document_id = "document-a"
        document_version = "canonical-v2"
        display_filename = "canonical.txt"
        filename = "canonical.txt"
        content_checksum = "sha256:document"
        status = "published"

    class Chunk:
        chunk_id = "chunk-a"
        document_id = "document-a"
        tenant_id = "tenant-a"
        text = "The canonical PostgreSQL chunk is authoritative."
        checksum = "sha256:chunk"
        page_start = 3
        page_end = 3
        section = "Canonical"

    class Collection:
        tenant_id = "tenant-a"
        workspace_id = "workspace-a"
        collection_id = "collection-a"
        status = "active"

    def get_collection(self, workspace_id, collection_id, *, tenant_id):
        return self.Collection() if (tenant_id, workspace_id, collection_id) == (
            "tenant-a", "workspace-a", "collection-a"
        ) else None

    def get_document(self, document_id, *, tenant_id, workspace_id):
        return self.Document() if (document_id, tenant_id, workspace_id) == (
            "document-a", "tenant-a", "workspace-a"
        ) else None

    def get_chunks(self, document_id, *, tenant_id, workspace_id):
        return [self.Chunk()] if document_id == "document-a" else []


def test_high_quality_evidence_does_not_classify_domain_risk_or_intent() -> None:
    from rick_decision import DomainRisk, IntentClarity, DecisionAction

    gate = EvidenceDecisionGate(_Retrieval([_candidate()]))
    evidence, bundle, quality = gate._issue_candidates(
        query="What does the source support?", context=_context(), candidates=[_candidate()],
    )
    decision_input = gate._decision_input(
        context=_context(), bundle=bundle, evidence_count=len(evidence),
        retrieval_quality=quality, attempt=0,
    )
    assert bundle is not None
    assert decision_input.citation_support == 1.0
    assert decision_input.retrieval_quality >= 0.90
    assert decision_input.domain_risk is DomainRisk.UNKNOWN
    assert decision_input.user_intent.clarity is IntentClarity.UNKNOWN
    assert decision_input.user_intent.intent_code == "unknown"
    decision = gate.decision_layer.decide(decision_input)
    assert decision.action is DecisionAction.ESCALATE
    assert decision.reason_code == "risk_unknown"


def test_gate_replaces_caller_evidence_id_and_emits_decision_metadata() -> None:
    retrieval = _Retrieval([_candidate()])
    result = asyncio.run(
        EvidenceDecisionGate(retrieval).retrieve(
            query="What does the source support?",
            context=_context(),
        )
    )

    evidence, bundle, quality = EvidenceDecisionGate(retrieval)._issue_candidates(
        query="What does the source support?",
        context=_context(),
        candidates=[_candidate()],
    )
    assert isinstance(evidence, list)
    assert len(evidence) == 1
    assert evidence[0]["evidence_id"].startswith("ev_")
    assert evidence[0]["evidence_id"] != "ev-caller-controlled"
    assert quality >= 0.95
    assert result["metadata"]["decision_action"] == "ESCALATE"
    assert result["metadata"]["decision_reason"] == "risk_unknown"
    assert result["evidence"] == []
    assert result["metadata"]["evidence_bundle_id"].startswith("eb_")
    assert retrieval.calls == 1


@pytest.mark.parametrize("evidence", [[], [_candidate(retrieval_quality_score=0.49)]])
def test_gate_escalates_unknown_grounding_signals(evidence) -> None:
    retrieval = _Retrieval(evidence)
    result = asyncio.run(
        EvidenceDecisionGate(retrieval).retrieve(
            query="What does the source support?",
            context=_context(),
        )
    )

    assert result["evidence"] == []
    assert result["selected_count"] == 0
    assert result["metadata"]["decision_action"] == "ESCALATE"
    assert result["metadata"]["decision_reason"] == "risk_unknown"
    assert retrieval.calls == 1


def test_gate_escalates_when_provenance_is_incomplete() -> None:
    retrieval = _Retrieval([_candidate(checksum="")])
    result = asyncio.run(
        EvidenceDecisionGate(retrieval).retrieve(
            query="What does the source support?",
            context=_context(),
        )
    )

    assert result["evidence"] == []
    assert result["selected_count"] == 0
    assert result["metadata"]["decision_action"] == "ESCALATE"
    assert result["metadata"]["decision_reason"] == "risk_unknown"
    assert retrieval.calls == 1


def test_external_authority_replaces_untrusted_retrieval_text_and_checksum() -> None:
    retrieval = _Retrieval([_candidate(text="forged text", checksum="sha256:forged")])
    gate = EvidenceDecisionGate(retrieval, knowledge=_CanonicalKnowledge())
    evidence, bundle, quality = gate._issue_candidates(
        query="What does the source support?",
        context=_context(),
        candidates=[_candidate(text="forged text", checksum="sha256:forged")],
    )

    assert evidence[0]["text"] == "The canonical PostgreSQL chunk is authoritative."
    assert evidence[0]["checksum"] == "sha256:chunk"
    assert evidence[0]["document_version"] == "canonical-v2"
    assert bundle is not None
    assert quality >= 0.90


def test_gate_consumes_observed_claim_support_metrics_when_present() -> None:
    retrieval = _Retrieval(
        [_candidate()],
        metadata={
            "backend": "test",
            "citation_support_status": "PASS",
            "citation_precision": 0.70,
            "citation_recall": 1.0,
            "citation_completeness": 1.0,
            "unsupported_claim_rate": 0.0,
            "citation_evaluated_claims": 1,
            "citation_support_source": "approved_claim_support",
        },
    )

    result = asyncio.run(
        EvidenceDecisionGate(retrieval).retrieve(
            query="What does the source support?",
            context=_context(),
        )
    )

    assert result["evidence"] == []
    assert result["metadata"]["decision_action"] == "ESCALATE"
    assert result["metadata"]["decision_reason"] == "risk_unknown"
    assert retrieval.calls == 1


@pytest.mark.parametrize(
    "overrides, action",
    [
        ({"citation_precision": 0.79}, "ESCALATE"),
        ({"citation_recall": 0.79}, "ESCALATE"),
        ({"citation_completeness": 0.79}, "ESCALATE"),
        ({"unsupported_claim_rate": 0.01}, "ESCALATE"),
        ({"faithfulness": 0.79}, "ESCALATE"),
        ({"status": "INCONCLUSIVE"}, "ESCALATE"),
        ({"evaluated_claims": 0}, "ESCALATE"),
        ({"citation_precision": None}, "ESCALATE"),
    ],
)
def test_gate_uses_existing_policy_boundaries_for_observed_support(overrides, action) -> None:
    metrics = {
        "status": "PASS",
        "citation_precision": 0.80,
        "citation_recall": 0.80,
        "citation_completeness": 0.80,
        "unsupported_claim_rate": 0.0,
        "faithfulness": 0.80,
        "evaluated_claims": 1,
        "source": "approved_claim_support",
        **overrides,
    }
    retrieval = _Retrieval(
        [_candidate(retrieval_quality_score=0.50)],
        metadata={"citation_support_metrics": metrics},
    )
    result = asyncio.run(
        EvidenceDecisionGate(retrieval).retrieve(
            query="What does the source support?", context=_context(),
        )
    )

    assert result["metadata"]["decision_action"] == action
    assert result["selected_count"] == (1 if action == "ANSWER" else 0)
    if action == "ESCALATE":
        assert result["metadata"]["decision_reason"] == "risk_unknown"
    assert retrieval.calls == 1


def test_malformed_claim_support_observation_cannot_fall_back_to_bundle_presence() -> None:
    retrieval = _Retrieval(
        [_candidate()],
        metadata={
            "backend": "test",
            "citation_support_status": "PASS",
            "citation_precision": "not-a-number",
            "citation_recall": 1.0,
            "citation_completeness": 1.0,
            "unsupported_claim_rate": 0.0,
            "citation_evaluated_claims": 1,
            "citation_support_source": "approved_claim_support",
        },
    )

    result = asyncio.run(
        EvidenceDecisionGate(retrieval).retrieve(
            query="What does the source support?",
            context=_context(),
        )
    )

    assert result["evidence"] == []
    assert result["metadata"]["decision_action"] == "ESCALATE"
    assert result["metadata"]["decision_reason"] == "risk_unknown"
    assert retrieval.calls == 1
