"""Hermetic tests for the root Professor lane."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
for _package in ("contracts", "professor"):
    _source = str(_ROOT / "packages" / _package / "src")
    if _source not in sys.path:
        sys.path.insert(0, _source)

from rick_contracts.professor import ProfessorRequest
from rick_contracts.providers import ChatCompletionChunk, ChatCompletionResult
from rick_contracts.security import RetrievalContext
from rick_professor import ProfessorLimits, ProfessorOrchestrator


def _request() -> ProfessorRequest:
    return ProfessorRequest(
        query="What does the source say?",
        conversation_id="conversation-1",
        retrieval_context=RetrievalContext(
            user_id="user-1",
            workspace_id="workspace-1",
            tenant_id="tenant-1",
            allowed_collection_ids=["collection-1"],
            permissions=["chat.query", "sources.read"],
        ),
    )


def _evidence(*, confidence: float = 0.9, tenant_id: str | None = "tenant-1", workspace_id: str = "workspace-1", collection_id: str = "collection-1", text: str = "A supported fact.") -> dict:
    return {
        "evidence_id": "ev-1",
        "document_id": "document-1",
        "chunk_id": "chunk-1",
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "collection_id": collection_id,
        "text": text,
        "title": "Source one",
        "checksum": "checksum-1",
        "confidence_score": confidence,
    }


class RetrievalDouble:
    def __init__(self, evidence: list[dict]) -> None:
        self.evidence = evidence
        self.calls = 0
        self.contexts: list[dict] = []

    async def retrieve(self, *, query: str, context: dict) -> dict:
        self.calls += 1
        self.contexts.append(context)
        return {"evidence": self.evidence}


class ProviderDouble:
    def __init__(self, content: str = "Grounded answer [cite:ev-1]") -> None:
        self.content = content
        self.calls = 0
        self.messages = []

    async def complete(self, *, messages, conversation_id: str) -> ChatCompletionResult:
        self.calls += 1
        self.messages.append((messages, conversation_id))
        return ChatCompletionResult(model="deterministic", content=self.content, correlation_id="corr-1")


@pytest.mark.asyncio
async def test_no_evidence_is_safe_and_does_not_generate() -> None:
    retrieval = RetrievalDouble([])
    provider = ProviderDouble()

    response = await ProfessorOrchestrator(retrieval=retrieval, chat_provider=provider).run(_request())

    assert response.evidence_status == "NO_EVIDENCE"
    assert response.citations == []
    assert response.evidence == []
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_weak_evidence_is_gated_before_provider() -> None:
    retrieval = RetrievalDouble([_evidence(confidence=0.49)])
    provider = ProviderDouble()

    response = await ProfessorOrchestrator(retrieval=retrieval, chat_provider=provider).run(_request())

    assert response.evidence_status == "WEAK_EVIDENCE"
    assert response.citations == []
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_approved_evidence_is_the_only_generation_path_and_citation_is_derived() -> None:
    retrieval = RetrievalDouble([_evidence()])
    provider = ProviderDouble()

    response = await ProfessorOrchestrator(retrieval=retrieval, chat_provider=provider).run(_request())

    assert response.evidence_status == "APPROVED_EVIDENCE"
    assert response.answer == "Grounded answer"
    assert [citation.document_id for citation in response.citations] == ["document-1"]
    assert response.citations[0].chunk_id == "chunk-1"
    assert provider.calls == 1
    assert "A supported fact." in provider.messages[0][0][0].content
    assert retrieval.contexts[0]["workspace_id"] == "workspace-1"


@pytest.mark.asyncio
async def test_unknown_or_forged_citation_marker_is_rejected() -> None:
    retrieval = RetrievalDouble([_evidence()])
    provider = ProviderDouble("Answer [cite:ev-forged]")

    response = await ProfessorOrchestrator(retrieval=retrieval, chat_provider=provider).run(_request())

    assert response.evidence_status == "CITATION_INVALID"
    assert response.citations == []
    assert "ev-forged" not in response.answer


@pytest.mark.asyncio
async def test_out_of_scope_evidence_cannot_reach_generation_or_response() -> None:
    retrieval = RetrievalDouble([_evidence(collection_id="secret-collection", text="secret")])
    provider = ProviderDouble()

    response = await ProfessorOrchestrator(retrieval=retrieval, chat_provider=provider).run(_request())

    assert response.evidence_status == "NO_EVIDENCE"
    assert response.evidence == []
    assert "secret" not in provider.messages
    assert provider.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": "tenant-2"},
        {"tenant_id": None},
        {"workspace_id": "workspace-2"},
        {"collection_id": "secret-collection"},
    ],
)
async def test_evidence_scope_is_fail_closed_at_professor_boundary(overrides: dict) -> None:
    retrieval = RetrievalDouble([_evidence(**overrides)])
    provider = ProviderDouble()

    response = await ProfessorOrchestrator(retrieval=retrieval, chat_provider=provider).run(_request())

    assert response.evidence_status == "NO_EVIDENCE"
    assert response.evidence == []
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_provider_failure_is_translated_without_exception_details() -> None:
    retrieval = RetrievalDouble([_evidence()])

    class FailingProvider(ProviderDouble):
        async def complete(self, *, messages, conversation_id: str) -> ChatCompletionResult:
            raise RuntimeError("secret api key and provider response")

    response = await ProfessorOrchestrator(retrieval=retrieval, chat_provider=FailingProvider()).run(_request())

    assert response.evidence_status == "GENERATION_FAILED"
    assert "secret" not in response.answer.lower()
    assert "api key" not in str(response.metadata).lower()
    assert set(response.metadata) == {"failure_stage", "evidence_count"}


@pytest.mark.asyncio
async def test_evidence_and_answer_are_bounded() -> None:
    retrieval = RetrievalDouble([_evidence(text="x" * 1000)])
    provider = ProviderDouble("y" * 1000 + " [cite:ev-1]")
    limits = ProfessorLimits(max_evidence_chars=100, max_evidence_item_chars=80, max_answer_chars=40)

    response = await ProfessorOrchestrator(retrieval=retrieval, chat_provider=provider, limits=limits).run(_request())

    assert len(response.evidence[0].text) == 80
    assert len(response.answer) <= 40


@pytest.mark.asyncio
async def test_cancellation_releases_acquired_lease() -> None:
    retrieval = RetrievalDouble([_evidence()])
    started = asyncio.Event()
    release_seen = asyncio.Event()

    class BlockingProvider(ProviderDouble):
        async def complete(self, *, messages, conversation_id: str) -> ChatCompletionResult:
            started.set()
            await asyncio.Future()

    class LeaseDouble:
        def __init__(self) -> None:
            self.acquires = 0
            self.releases = 0

        async def acquire(self, *, key: str, owner: str, ttl_ms: int) -> dict:
            self.acquires += 1
            return {"acquired": True}

        async def release(self, *, key: str, owner: str) -> dict:
            self.releases += 1
            release_seen.set()
            return {"released": True}

    lease = LeaseDouble()
    task = asyncio.create_task(
        ProfessorOrchestrator(
            retrieval=retrieval,
            chat_provider=BlockingProvider(),
            lease_manager=lease,
        ).run(_request())
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.wait_for(release_seen.wait(), timeout=1)
    assert lease.acquires == 1
    assert lease.releases == 1


@pytest.mark.asyncio
async def test_lease_renewal_loss_cancels_generation_and_releases_owner() -> None:
    retrieval = RetrievalDouble([_evidence()])
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingProvider(ProviderDouble):
        async def complete(self, *, messages, conversation_id: str) -> ChatCompletionResult:
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    class LeaseDouble:
        def __init__(self) -> None:
            self.renewals = 0
            self.releases = 0

        async def acquire(self, *, key: str, owner: str, ttl_ms: int) -> dict:
            return {"acquired": True}

        async def renew(self, *, key: str, owner: str, ttl_ms: int) -> dict:
            self.renewals += 1
            return {"renewed": False}

        async def release(self, *, key: str, owner: str) -> dict:
            self.releases += 1
            return {"released": True}

    lease = LeaseDouble()
    task = asyncio.create_task(
        ProfessorOrchestrator(
            retrieval=retrieval,
            chat_provider=BlockingProvider(),
            lease_manager=lease,
            limits=ProfessorLimits(lease_ttl_ms=30),
        ).run(_request())
    )

    response = await asyncio.wait_for(task, timeout=1)

    assert response.evidence_status == "GENERATION_FAILED"
    assert response.metadata["failure_stage"] == "lease_lost"
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    assert lease.renewals >= 1
    assert lease.releases == 1


@pytest.mark.asyncio
async def test_high_level_lease_handle_is_released() -> None:
    retrieval = RetrievalDouble([])

    class LeaseHandle:
        pass

    class HighLevelLease:
        def __init__(self) -> None:
            self.handle = LeaseHandle()
            self.released = None

        async def acquire(self, key: str, ttl_ms: int) -> LeaseHandle:
            return self.handle

        async def release(self, handle: LeaseHandle) -> bool:
            self.released = handle
            return True

    lease = HighLevelLease()
    response = await ProfessorOrchestrator(
        retrieval=retrieval,
        chat_provider=ProviderDouble(),
        lease_manager=lease,
    ).run(_request())

    assert response.evidence_status == "NO_EVIDENCE"
    assert lease.released is lease.handle


@pytest.mark.asyncio
async def test_stream_lease_loss_cancels_slow_provider_and_emits_safe_terminal_result() -> None:
    retrieval = RetrievalDouble([_evidence()])
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowStreamingProvider(ProviderDouble):
        async def stream(self, *, messages, conversation_id: str):
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            yield ChatCompletionChunk(
                model="deterministic", delta="late", finish_reason="stop", correlation_id="corr-stream"
            )

    class LeaseDouble:
        def __init__(self) -> None:
            self.renewals = 0
            self.releases = 0

        async def acquire(self, *, key: str, owner: str, ttl_ms: int) -> dict:
            return {"acquired": True}

        async def renew(self, *, key: str, owner: str, ttl_ms: int) -> dict:
            self.renewals += 1
            return {"renewed": False}

        async def release(self, *, key: str, owner: str) -> dict:
            self.releases += 1
            return {"released": True}

    lease = LeaseDouble()
    orchestrator = ProfessorOrchestrator(
        retrieval=retrieval,
        chat_provider=SlowStreamingProvider(),
        lease_manager=lease,
        limits=ProfessorLimits(lease_ttl_ms=30),
    )

    async def consume():
        return [event async for event in orchestrator.stream(_request())]

    events = await asyncio.wait_for(consume(), timeout=1)

    assert started.is_set()
    assert cancelled.is_set()
    assert lease.renewals >= 1
    assert lease.releases == 1
    assert events[-1]["kind"] == "final"
    assert events[-1]["response"].metadata["failure_stage"] == "lease_lost"
