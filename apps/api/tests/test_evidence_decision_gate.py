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
    def __init__(self, evidence: list[dict[str, object]]) -> None:
        self.evidence = evidence
        self.calls = 0

    async def retrieve(self, *, query: str, context: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        return {"evidence": list(self.evidence), "metadata": {"backend": "test"}}


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
        text = "The canonical PostgreSQL chunk is authoritative."
        checksum = "sha256:chunk"
        page_start = 3
        page_end = 3
        section = "Canonical"

    def get_document(self, document_id, *, tenant_id, workspace_id):
        return self.Document() if (document_id, tenant_id, workspace_id) == (
            "document-a", "tenant-a", "workspace-a"
        ) else None

    def get_chunks(self, document_id, *, tenant_id, workspace_id):
        return [self.Chunk()] if document_id == "document-a" else []


def test_gate_replaces_caller_evidence_id_and_emits_decision_metadata() -> None:
    retrieval = _Retrieval([_candidate()])
    result = asyncio.run(
        EvidenceDecisionGate(retrieval).retrieve(
            query="What does the source support?",
            context=_context(),
        )
    )

    evidence = result["evidence"]
    assert isinstance(evidence, list)
    assert len(evidence) == 1
    assert evidence[0]["evidence_id"].startswith("ev_")
    assert evidence[0]["evidence_id"] != "ev-caller-controlled"
    assert result["metadata"]["decision_action"] == "ANSWER"
    assert result["metadata"]["evidence_bundle_id"].startswith("eb_")
    assert retrieval.calls == 1


def test_gate_retries_then_abstains_when_provenance_is_incomplete() -> None:
    retrieval = _Retrieval([_candidate(checksum="")])
    result = asyncio.run(
        EvidenceDecisionGate(retrieval).retrieve(
            query="What does the source support?",
            context=_context(),
        )
    )

    assert result["evidence"] == []
    assert result["selected_count"] == 0
    assert result["metadata"]["decision_action"] == "ABSTAIN"
    assert result["metadata"]["decision_reason"].startswith("evidence_bundle_missing")
    assert retrieval.calls == 2


def test_external_authority_replaces_untrusted_retrieval_text_and_checksum() -> None:
    retrieval = _Retrieval([_candidate(text="forged text", checksum="sha256:forged")])
    result = asyncio.run(
        EvidenceDecisionGate(retrieval, knowledge=_CanonicalKnowledge()).retrieve(
            query="What does the source support?",
            context=_context(),
        )
    )

    assert result["metadata"]["decision_action"] == "ANSWER"
    evidence = result["evidence"]
    assert evidence[0]["text"] == "The canonical PostgreSQL chunk is authoritative."
    assert evidence[0]["checksum"] == "sha256:chunk"
    assert evidence[0]["document_version"] == "canonical-v2"
