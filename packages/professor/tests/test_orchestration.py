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
from rick_contracts.providers import ChatCompletionChunk, ChatCompletionResult, ProviderUsage
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
        return ChatCompletionResult(model="deterministic", content=self.content, finish_reason="stop", correlation_id="corr-1")


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


class StreamingProviderDouble(ProviderDouble):
    async def stream(self, *, messages, conversation_id: str):
        self.calls += 1
        self.messages.append((messages, conversation_id))
        for character in self.content:
            yield ChatCompletionChunk(
                model="deterministic", delta=character, correlation_id="corr-1",
            )
        yield ChatCompletionChunk(model="deterministic", finish_reason="stop", correlation_id="corr-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["completion", "stream_fallback"])
async def test_omitted_typed_conclusion_is_unsuccessful(path):
    class MissingConclusion(ProviderDouble):
        async def complete(self, **kwargs):
            result = ChatCompletionResult(
                model="test", content="Grounded answer [cite:ev-1]", correlation_id="c",
            )
            assert result.finish_reason == "unknown"
            return result

    orchestrator = ProfessorOrchestrator(
        retrieval=RetrievalDouble([_evidence()]), chat_provider=MissingConclusion(),
    )
    if path == "completion":
        response = await orchestrator.run(_request())
    else:
        response = [event async for event in orchestrator.stream(_request())][-1]["response"]
    assert response.evidence_status == "GENERATION_FAILED"
    assert response.metadata["failure_stage"] == "completion_incomplete"
    assert response.citations == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tail", ["content", "new_tool", "existing_tool", "terminal", "usage"])
async def test_terminal_stream_allows_only_usage_tail(tail):
    closed = asyncio.Event()
    tool = {"index": 0, "id": "call-1", "type": "function",
            "function": {"name": "report_status", "arguments": "{}"}}

    class TerminalStream:
        async def stream(self, **kwargs):
            try:
                yield ChatCompletionChunk(model="test", delta="Grounded answer [cite:ev-1]", correlation_id="c")
                if tail == "existing_tool":
                    yield ChatCompletionChunk(model="test", tool_calls=[tool], correlation_id="c")
                yield ChatCompletionChunk(model="test", finish_reason="stop", correlation_id="c")
                if tail == "usage":
                    yield ChatCompletionChunk(model="test", correlation_id="c",
                        usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))
                elif tail == "content":
                    yield ChatCompletionChunk(model="test", delta="forbidden continuation", correlation_id="c")
                elif tail == "terminal":
                    yield ChatCompletionChunk(model="test", finish_reason="stop", correlation_id="c")
                else:
                    yield ChatCompletionChunk(model="test", tool_calls=[tool], correlation_id="c")
            finally:
                closed.set()

    events = [event async for event in ProfessorOrchestrator(
        retrieval=RetrievalDouble([_evidence()]), chat_provider=TerminalStream(),
        limits=ProfessorLimits(max_tool_calls=1),
    ).stream(_request())]
    response = events[-1]["response"]
    assert closed.is_set()
    if tail == "usage":
        assert response.evidence_status == "APPROVED_EVIDENCE"
    else:
        assert response.evidence_status == "GENERATION_FAILED"
        assert response.metadata["failure_stage"] == "provider_failed"
        assert response.citations == []
        assert all(event.get("delta") != "forbidden continuation" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["completion", "stream", "stream_fallback"])
@pytest.mark.parametrize(
    ("content", "status", "answer"),
    [
        ("Uncited answer", "CITATION_INVALID", None),
        ("I cannot answer from the sources.", "CITATION_INVALID", None),
        ("Answer [cite:ev-forged]", "CITATION_INVALID", None),
        ("Answer [citation:ev-1]", "CITATION_INVALID", None),
        ("Answer [cite:]", "CITATION_INVALID", None),
        ("Answer [cite:ev-1] [cite:ev-forged]", "CITATION_INVALID", None),
        ("Grounded answer [cite:ev-1]", "APPROVED_EVIDENCE", "Grounded answer"),
        ("Grounded answer [cite:ev-1] [cite:ev-1]", "APPROVED_EVIDENCE", "Grounded answer"),
    ],
)
async def test_completion_paths_require_valid_citations(path: str, content: str, status: str, answer: str | None) -> None:
    retrieval = RetrievalDouble([_evidence()])
    provider = StreamingProviderDouble(content) if path == "stream" else ProviderDouble(content)
    orchestrator = ProfessorOrchestrator(retrieval=retrieval, chat_provider=provider)
    request = _request()

    if path == "completion":
        response = await orchestrator.run(request)
    else:
        events = [event async for event in orchestrator.stream(request)]
        assert [event["kind"] for event in events].count("final") == 1
        assert events[-1]["kind"] == "final"
        assert "".join(event["delta"] for event in events if event["kind"] == "delta") == content
        assert all("response" not in event for event in events if event["kind"] == "delta")
        response = events[-1]["response"]

    assert response.evidence_status == status
    assert response.conversation_id == request.conversation_id
    assert len(response.evidence) == 1
    assert response.metadata["evidence_count"] == 1
    if answer is None:
        assert response.answer == "I could not verify the source references in the generated response."
        assert response.citations == []
    else:
        assert response.answer == answer
        assert [citation.model_dump() for citation in response.citations] == [{
            "document_id": "document-1", "chunk_id": "chunk-1", "title": "Source one",
            "collection_id": "collection-1", "page_start": None, "page_end": None,
            "checksum": "checksum-1",
        }]
        assert response.metadata["provider_model"] == "deterministic"
    assert provider.calls == retrieval.calls == 1
    assert retrieval.contexts == [request.retrieval_context.model_dump()]
    messages, conversation_id = provider.messages[0]
    assert conversation_id == request.conversation_id
    assert messages[1].content == f"User request:\n{request.query}"
    assert "SOURCE ev-1\nA supported fact.\nEND SOURCE ev-1" in messages[0].content
    assert "marker [cite:<evidence_id>] using an id from the supplied sources. Never invent ids." in messages[0].content


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
    assert response.evidence_status == "GENERATION_FAILED"
    assert response.metadata["failure_stage"] == "answer_budget_exceeded"


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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_evidence_items": 1.0},
        {"max_retrieval_rounds": 0},
        {"max_retrieval_rounds": 1.0},
        {"max_tool_calls": -1},
        {"max_tool_calls": True},
        {"max_provider_calls": 0},
        {"max_provider_calls": 1.0},
        {"max_tokens": 0},
        {"max_tokens": 1.0},
        {"max_reasoning_seconds": 0},
        {"max_reasoning_seconds": True},
        {"max_reasoning_seconds": float("inf")},
        {"max_total_request_seconds": 0},
        {"max_total_request_seconds": True},
        {"max_total_request_seconds": float("nan")},
    ],
)
def test_request_budgets_reject_unusable_limits(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ProfessorLimits(**kwargs)


@pytest.mark.asyncio
async def test_reasoning_timeout_is_translated_to_a_safe_response() -> None:
    class SlowRetrieval:
        async def retrieve(self, *, query: str, context: dict) -> dict:
            await asyncio.sleep(1)
            return {"evidence": []}

    response = await ProfessorOrchestrator(
        retrieval=SlowRetrieval(),
        chat_provider=ProviderDouble(),
        limits=ProfessorLimits(max_reasoning_seconds=0.01, max_total_request_seconds=1),
    ).run(_request())

    assert response.evidence_status == "GENERATION_FAILED"
    assert response.metadata["failure_stage"] == "reasoning_timeout"


@pytest.mark.asyncio
async def test_total_request_timeout_covers_lease_acquisition() -> None:
    class SlowLease:
        async def acquire(self, *, key: str, owner: str, ttl_ms: int) -> dict:
            await asyncio.sleep(1)
            return {"acquired": True}

    response = await ProfessorOrchestrator(
        retrieval=RetrievalDouble([]),
        chat_provider=ProviderDouble(),
        lease_manager=SlowLease(),
        limits=ProfessorLimits(max_reasoning_seconds=1, max_total_request_seconds=0.01),
    ).run(_request())

    assert response.evidence_status == "GENERATION_FAILED"
    assert response.metadata["failure_stage"] == "total_request_timeout"


@pytest.mark.asyncio
async def test_provider_token_budget_is_enforced_from_reported_usage() -> None:
    class MeteredProvider(ProviderDouble):
        async def complete(self, *, messages, conversation_id: str) -> ChatCompletionResult:
            return ChatCompletionResult(
                model="metered",
                content="Grounded answer [cite:ev-1]",
                finish_reason="stop",
                correlation_id="corr-metered",
                usage=ProviderUsage(prompt_tokens=10, completion_tokens=90, total_tokens=100),
            )

    response = await ProfessorOrchestrator(
        retrieval=RetrievalDouble([_evidence()]),
        chat_provider=MeteredProvider(),
        limits=ProfessorLimits(max_tokens=99),
    ).run(_request())

    assert response.evidence_status == "GENERATION_FAILED"
    assert response.metadata["failure_stage"] == "token_budget_exceeded"


@pytest.mark.asyncio
async def test_provider_tool_calls_are_counted_and_rejected_without_execution() -> None:
    class ToolProvider(ProviderDouble):
        async def complete(self, *, messages, conversation_id: str) -> ChatCompletionResult:
            return ChatCompletionResult.model_validate(
                {
                    "model": "tool-provider",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "report_status", "arguments": "{}"},
                        },
                        {
                            "id": "call-2",
                            "type": "function",
                            "function": {"name": "report_status", "arguments": "{}"},
                        },
                    ],
                    "correlation_id": "corr-tools",
                }
            )

    response = await ProfessorOrchestrator(
        retrieval=RetrievalDouble([_evidence()]),
        chat_provider=ToolProvider(),
        limits=ProfessorLimits(max_tool_calls=1),
    ).run(_request())

    assert response.evidence_status == "GENERATION_FAILED"
    assert response.metadata["failure_stage"] == "tool_calls_budget_exceeded"


@pytest.mark.asyncio
async def test_streaming_provider_tool_calls_are_budgeted_before_content_is_published() -> None:
    class ToolStreamingProvider(ProviderDouble):
        async def stream(self, *, messages, conversation_id: str):
            yield ChatCompletionChunk(
                model="tool-stream-provider",
                delta="partial [cite:ev-1]",
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call-stream-1",
                        "type": "function",
                        "function": {"name": "report_status", "arguments": "{}"},
                    }
                ],
                finish_reason="stop",
                correlation_id="corr-stream-tools",
            )

    events = [
        event
        async for event in ProfessorOrchestrator(
            retrieval=RetrievalDouble([_evidence()]),
            chat_provider=ToolStreamingProvider(),
            limits=ProfessorLimits(max_tool_calls=0),
        ).stream(_request())
    ]

    assert events[-1]["kind"] == "final"
    assert events[-1]["response"].metadata["failure_stage"] == "tool_calls_budget_exceeded"
    assert not any(event["kind"] == "delta" for event in events)


@pytest.mark.asyncio
async def test_stream_reasoning_timeout_emits_safe_terminal_response() -> None:
    class SlowStreamingProvider(ProviderDouble):
        async def stream(self, *, messages, conversation_id: str):
            await asyncio.sleep(1)
            yield ChatCompletionChunk(
                model="slow", delta="late", finish_reason="stop", correlation_id="corr-slow"
            )

    events = [
        event
        async for event in ProfessorOrchestrator(
            retrieval=RetrievalDouble([_evidence()]),
            chat_provider=SlowStreamingProvider(),
            limits=ProfessorLimits(max_reasoning_seconds=0.01, max_total_request_seconds=1),
        ).stream(_request())
    ]

    assert events[-1]["kind"] == "final"
    assert events[-1]["response"].metadata["failure_stage"] == "reasoning_timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["completion", "stream", "stream_fallback"])
@pytest.mark.parametrize("reason", ["length", "content_filter", "unknown", "tool_calls"])
async def test_non_stop_completions_are_never_approved(path, reason):
    class Provider(ProviderDouble):
        async def complete(self, **kwargs):
            result = await super().complete(**kwargs)
            return result.model_copy(update={"finish_reason": reason})

        async def stream(self, **kwargs):
            yield ChatCompletionChunk(model="test", delta="Grounded answer [cite:ev-1]", correlation_id="c")
            yield ChatCompletionChunk(model="test", finish_reason=reason, correlation_id="c")

    provider = Provider()
    if path == "stream_fallback":
        provider.stream = None
    orchestrator = ProfessorOrchestrator(retrieval=RetrievalDouble([_evidence()]), chat_provider=provider)
    if path == "completion":
        response = await orchestrator.run(_request())
    else:
        response = [event async for event in orchestrator.stream(_request())][-1]["response"]
    assert response.evidence_status == "GENERATION_FAILED"
    assert response.metadata["failure_stage"] == "completion_incomplete"
    assert response.citations == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_stop", "length_then_stop", "text_after_stop", "oversized", "reported_tokens"])
async def test_broken_provider_stream_never_completes_successfully(case):
    closed = asyncio.Event()

    class BrokenStream:
        async def stream(self, **kwargs):
            try:
                if case == "oversized":
                    yield ChatCompletionChunk(model="test", delta="x" * 50_000, correlation_id="c")
                elif case == "reported_tokens":
                    yield ChatCompletionChunk(model="test", delta="text", correlation_id="c",
                        usage=ProviderUsage(prompt_tokens=9_000, completion_tokens=1, total_tokens=9_001))
                else:
                    yield ChatCompletionChunk(model="test", delta="Grounded answer [cite:ev-1]", correlation_id="c")
                    if case == "length_then_stop":
                        yield ChatCompletionChunk(model="test", finish_reason="length", correlation_id="c")
                        yield ChatCompletionChunk(model="test", finish_reason="stop", correlation_id="c")
                    if case == "text_after_stop":
                        yield ChatCompletionChunk(model="test", finish_reason="stop", correlation_id="c")
                        yield ChatCompletionChunk(model="test", delta="unapproved continuation", correlation_id="c")
            finally:
                closed.set()

    events = [event async for event in ProfessorOrchestrator(
        retrieval=RetrievalDouble([_evidence()]), chat_provider=BrokenStream(),
    ).stream(_request())]
    assert events[-1]["response"].evidence_status == "GENERATION_FAILED"
    assert events[-1]["response"].citations == []
    assert closed.is_set()
    if case in {"oversized", "reported_tokens"}:
        assert [event["kind"] for event in events] == ["final"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["json", "stream"])
@pytest.mark.parametrize("validator", ["missing", "false", "raises", "malformed"])
async def test_required_final_publication_hook_cannot_be_bypassed(path, validator):
    class Retrieval(RetrievalDouble):
        async def validate_publication(self, **kwargs):
            if validator == "raises":
                raise RuntimeError("private publication failure")
            return {"valid": True} if validator == "malformed" else False

    retrieval = Retrieval([_evidence()])
    if validator == "missing":
        retrieval.validate_publication = None
    orchestrator = ProfessorOrchestrator(
        retrieval=retrieval, chat_provider=StreamingProviderDouble(),
        require_publication_revalidation=True,
    )
    if path == "json":
        result = await orchestrator.run(_request())
    else:
        result = [event async for event in orchestrator.stream(_request())][-1]["response"]
    assert result.evidence_status == "CITATION_INVALID"
    assert result.citations == result.evidence == []
    assert "private" not in result.answer


@pytest.mark.asyncio
async def test_final_validation_runs_after_json_lease_release():
    valid = True

    class Retrieval(RetrievalDouble):
        async def validate_publication(self, **kwargs):
            return valid

    class Lease:
        async def acquire(self, **kwargs):
            return {"acquired": True}

        async def release(self, **kwargs):
            nonlocal valid
            valid = False

    result = await ProfessorOrchestrator(
        retrieval=Retrieval([_evidence()]), chat_provider=ProviderDouble(),
        lease_manager=Lease(), require_publication_revalidation=True,
    ).run(_request())
    assert result.evidence_status == "CITATION_INVALID"
    assert result.citations == []
