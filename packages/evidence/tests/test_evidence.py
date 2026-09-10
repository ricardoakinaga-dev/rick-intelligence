"""Focused contract tests for the server-issued evidence lane."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(_ROOT / "packages" / "evidence" / "src"))

from rick_evidence import (  # noqa: E402
    Evidence,
    EvidenceBundle,
    EvidenceScope,
    EvidenceValidationError,
    EvidenceValidator,
    server_evidence_id,
)
from rick_contracts.rag import EvidenceDto  # noqa: E402


def _scope() -> EvidenceScope:
    return EvidenceScope(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        collection_id="collection-a",
    )


def _candidate(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "collection_id": "collection-a",
        "document_id": "document-a",
        "document_version": "version-1",
        "chunk_id": "chunk-a-0001",
        "source": "source.txt",
        "checksum": "sha256:fixture",
        "text": "The source records a bounded fact about the archive.",
        "score": 0.9,
        "reranking_score": 0.8,
    }
    value.update(overrides)
    return value


def test_issue_generates_a_stable_id_and_replaces_candidate_id() -> None:
    validator = EvidenceValidator()
    first = validator.issue({**_candidate(), "evidence_id": "forged"}, scope=_scope())
    second = validator.issue({**_candidate(), "evidence_id": "another-forged-id"}, scope=_scope())

    assert first.evidence_id.startswith("ev_")
    assert first.evidence_id == second.evidence_id
    assert first.evidence_id == server_evidence_id(first)
    assert first.citation_marker == f"[cite:{first.evidence_id}]"


def test_existing_retrieval_dto_is_an_input_only_and_gets_new_provenance_id() -> None:
    dto = EvidenceDto(
        evidence_id="ev-retrieval-owned",
        document_id="document-a",
        chunk_id="chunk-a-0001",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        collection_id="collection-a",
        text="The source records a bounded fact.",
        source="source.txt",
        checksum="sha256:fixture",
        score=0.9,
    )

    issued = EvidenceValidator().issue(dto, scope=_scope(), document_version="version-1")

    assert issued.evidence_id != dto.evidence_id
    assert issued.document_version == "version-1"
    assert issued.retrieval_score == 0.9


def test_direct_forged_or_mutated_identifier_is_rejected() -> None:
    validator = EvidenceValidator()
    issued = validator.issue(_candidate(), scope=_scope())
    with pytest.raises(ValidationError):
        Evidence.model_validate({**issued.model_dump(), "evidence_id": "ev_" + "0" * 32})

    with pytest.raises(ValidationError):
        Evidence.model_validate({**issued.model_dump(), "text": "changed"})


def test_bundle_is_single_scope_and_has_an_exact_citation_map() -> None:
    validator = EvidenceValidator()
    item = validator.issue(_candidate(), scope=_scope())
    bundle = EvidenceBundle.build(
        tenant_id=_scope().tenant_id,
        workspace_id=_scope().workspace_id,
        collection_id=_scope().collection_id,
        query="What does the source say?",
        evidence=[item],
    )

    assert bundle.bundle_id.startswith("eb_")
    assert bundle.citation_for(item.evidence_id) == item.citation_marker
    assert validator.validate_bundle(bundle, expected_scope=_scope()).valid
    with pytest.raises(TypeError):
        bundle.citation_map["forged"] = "[cite:forged]"

    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(
            {
                **bundle.model_dump(),
                "workspace_id": "workspace-other",
            }
        )


def test_candidate_scope_and_required_version_fail_closed() -> None:
    validator = EvidenceValidator()
    with pytest.raises(EvidenceValidationError) as mismatch:
        validator.issue({**_candidate(), "tenant_id": "tenant-other"}, scope=_scope())
    assert mismatch.value.code == "candidate_scope_mismatch"

    with pytest.raises(EvidenceValidationError) as missing:
        validator.issue({key: value for key, value in _candidate().items() if key != "document_version"}, scope=_scope())
    assert missing.value.code == "document_version_missing"


def test_citation_and_claim_support_are_deterministic_and_bounded() -> None:
    validator = EvidenceValidator()
    item = validator.issue(_candidate(), scope=_scope())
    bundle = EvidenceBundle.build(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        collection_id="collection-a",
        query="archive fact",
        evidence=[item],
    )

    citation = validator.validate_citations(bundle, [item.evidence_id])
    support = validator.validate_claim_support(
        claim="The source records a bounded fact about the archive.",
        bundle=bundle,
        cited_evidence_ids=[item.evidence_id],
    )
    forged = validator.validate_citations(bundle, ["ev_" + "f" * 32])

    assert citation.valid
    assert support.valid
    assert support.coverage == 1.0
    assert not forged.valid
    assert "unknown_citation" in forged.error_codes


def test_nonfinite_scores_and_oversized_bundles_are_rejected() -> None:
    validator = EvidenceValidator(max_bundle_items=1)
    with pytest.raises(EvidenceValidationError):
        validator.issue(_candidate(score=math.nan), scope=_scope())

    item = validator.issue(_candidate(), scope=_scope())
    with pytest.raises(EvidenceValidationError) as limited:
        validator.build_bundle(
            query="q",
            candidates=[_candidate(), _candidate(text="another fact")],
            scope=_scope(),
        )
    assert limited.value.code == "evidence_limit_exceeded"


def test_authority_replaces_untrusted_projection_fields() -> None:
    class Authority:
        def resolve(self, candidate, *, scope):
            return {
                "tenant_id": scope.tenant_id,
                "workspace_id": scope.workspace_id,
                "collection_id": scope.collection_id,
                "document_id": "document-a",
                "document_version": "canonical-v2",
                "chunk_id": "chunk-a-0001",
                "source": "canonical.txt",
                "checksum": "sha256:canonical",
                "text": "The canonical source is authoritative.",
            }

    issued = EvidenceValidator(authority=Authority(), require_authority=True).issue(
        {
            **_candidate(),
            "text": "forged projection text",
            "checksum": "sha256:forged",
            "document_version": "canonical-v2",
        },
        scope=_scope(),
    )

    assert issued.text == "The canonical source is authoritative."
    assert issued.checksum == "sha256:canonical"
    assert issued.source == "canonical.txt"


def test_required_authority_rejects_missing_canonical_record() -> None:
    class MissingAuthority:
        def resolve(self, candidate, *, scope):
            return None

    with pytest.raises(EvidenceValidationError) as caught:
        EvidenceValidator(authority=MissingAuthority(), require_authority=True).issue(
            _candidate(), scope=_scope()
        )
    assert caught.value.code == "authoritative_evidence_missing"
