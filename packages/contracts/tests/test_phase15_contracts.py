"""Executable Phase 1.5 contract invariants."""

import math

import pytest
from pydantic import ValidationError

from rick_contracts import (
    ChatCompletionResult,
    EmbeddingResult,
    LeaseResult,
    ProfessorRequest,
    ProfessorResponse,
    ProviderMessage,
    ProviderToolCall,
    RetrievalContext,
)
from rick_contracts.chat import Citation
from rick_contracts.rag import EvidenceDto


def _context() -> RetrievalContext:
    return RetrievalContext(
        user_id="user-1",
        workspace_id="workspace-1",
        tenant_id="tenant-1",
        allowed_collection_ids=["collection-1"],
        permissions=["chat.query"],
    )


def _evidence() -> EvidenceDto:
    return EvidenceDto(
        evidence_id="ev-chunk-1",
        document_id="doc-1",
        chunk_id="chunk-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        collection_id="collection-1",
        text="A grounded veterinary fact.",
        source="manual.txt",
        checksum="sha256:fixture",
        score=0.9,
    )


def test_provider_contracts_reject_unknown_fields_and_invalid_version():
    with pytest.raises(ValidationError):
        ProviderMessage(role="user", content="hello", secret="must-not-cross")
    with pytest.raises(ValidationError):
        ChatCompletionResult(model="m", content="ok", contract_version="provider-contract-v0")


def test_embedding_contract_requires_finite_exact_dimension():
    with pytest.raises(ValidationError):
        EmbeddingResult(model="m", dimensions=2, vector=[1.0], correlation_id="corr")
    with pytest.raises(ValidationError):
        EmbeddingResult(model="m", dimensions=2, vector=[1.0, math.inf], correlation_id="corr")


def test_provider_tool_call_requires_safe_json_arguments_and_content_or_call():
    call = ProviderToolCall(
        id="call-1",
        type="function",
        function={"name": "report_status", "arguments": '{"status":"ok"}'},
    )
    result = ChatCompletionResult(
        model="m",
        content="",
        tool_calls=[call],
        correlation_id="corr",
    )
    assert result.tool_calls[0].function.name == "report_status"
    with pytest.raises(ValidationError):
        ProviderToolCall(
            id="call-1",
            type="function",
            function={"name": "report_status", "arguments": "not-json"},
        )
    with pytest.raises(ValidationError):
        ChatCompletionResult(model="m", content="", correlation_id="corr")


def test_lease_contract_requires_only_the_operation_outcome():
    assert LeaseResult(operation="acquire", key="k", acquired=True, correlation_id="corr").acquired is True
    with pytest.raises(ValidationError):
        LeaseResult(operation="release", key="k", released=None, correlation_id="corr")
    with pytest.raises(ValidationError):
        LeaseResult(operation="acquire", key="k", acquired=True, renewed=False, correlation_id="corr")


def test_professor_contract_preserves_typed_provenance_and_rejects_extra_fields():
    request = ProfessorRequest(query="What fact?", conversation_id="conv-1", retrieval_context=_context())
    assert request.retrieval_context.workspace_id == "workspace-1"
    response = ProfessorResponse(
        conversation_id="conv-1",
        answer="Grounded answer.",
        evidence_status="APPROVED_EVIDENCE",
        evidence=[_evidence()],
        citations=[Citation(document_id="doc-1", chunk_id="chunk-1", collection_id="collection-1")],
        metadata={"backend": "deterministic", "selected_count": 1},
    )
    assert response.evidence[0].checksum == "sha256:fixture"
    with pytest.raises(ValidationError):
        ProfessorResponse(
            conversation_id="conv-1",
            answer="bad",
            evidence_status="NO_EVIDENCE",
            unexpected="not allowed",
        )


def test_evidence_contract_rejects_unbounded_or_nonfinite_fields():
    with pytest.raises(ValidationError):
        EvidenceDto(**{**_evidence().model_dump(), "unexpected": "not allowed"})
    with pytest.raises(ValidationError):
        EvidenceDto(**{**_evidence().model_dump(), "confidence_score": math.nan})
