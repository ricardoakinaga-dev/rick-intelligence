from __future__ import annotations

import asyncio

import pytest

from core.telemetry import ApiTelemetry
from models import SessionSnapshot
from services.chat_history import InMemoryChatHistoryStore
from services.chat_service import ChatApplicationService


SESSION = SessionSnapshot(
    authenticated=True,
    session_state="active",
    user_id="user-a",
    tenant_id="tenant-a",
    workspace_id="workspace-a",
    permissions=["chat.query"],
)


class FailingStreamBackend:
    async def generate_stream(self, **_kwargs):
        yield {"type": "delta", "delta": "resposta parcial"}
        raise RuntimeError("provider details must not escape")


class BlockingStreamBackend:
    def __init__(self):
        self.released = asyncio.Event()

    async def generate_stream(self, **_kwargs):
        yield {"type": "delta", "delta": "antes do cancelamento"}
        await self.released.wait()


class CompletingStreamBackend:
    async def generate_stream(self, **_kwargs):
        yield {
            "type": "final",
            "result": {"answer": "resposta concluída", "citations": [], "metadata": {}},
        }


class FailingOutcomeHistory(InMemoryChatHistoryStore):
    def record_stream_outcome(self, **_kwargs):
        raise OSError("durable history is unavailable")


async def _collect(events):
    return [event async for event in events]


@pytest.mark.asyncio
async def test_stream_error_after_delta_persists_partial_and_records_live_metrics():
    history = InMemoryChatHistoryStore()
    telemetry = ApiTelemetry()
    service = ChatApplicationService(FailingStreamBackend(), history, telemetry=telemetry)

    events = await _collect(service.stream_events(
        session=SESSION, message="pergunta", conversation_id="conv-error",
        collection_id=None, workspace_id=None, mode="grounded",
    ))

    assert [event["type"] for event in events] == ["start", "delta", "error"]
    assert events[0]["provisional"] is True
    assert events[1]["provisional"] is True
    assert events[2]["provisional"] is False
    assert events[-1]["code"] == "generation_failed"
    stored = history.list_history(session=SESSION)[0]
    assert stored["metadata"]["stream_status"] == "partial"
    assert stored["metadata"]["error_code"] == "generation_failed"
    assert history.get_context(session=SESSION, conversation_id="conv-error") == []
    stream = telemetry.snapshot()["stream"]
    assert any(item["labels"].get("status") == "partial" for item in stream["outcomes"])
    assert stream["ttft"]["count"] == 1
    assert stream["duration"]["count"] == 1


@pytest.mark.asyncio
async def test_closing_live_stream_persists_cancelled_outcome_without_leaking_partial_context():
    history = InMemoryChatHistoryStore()
    backend = BlockingStreamBackend()
    telemetry = ApiTelemetry()
    service = ChatApplicationService(backend, history, telemetry=telemetry)
    events = service.stream_events(
        session=SESSION, message="pergunta", conversation_id="conv-cancel",
        collection_id=None, workspace_id=None, mode="grounded",
    )

    assert (await anext(events))["type"] == "start"
    assert (await anext(events))["type"] == "delta"
    await events.aclose()

    stored = history.list_history(session=SESSION)[0]
    assert stored["metadata"]["stream_status"] == "cancelled"
    assert stored["answer"] == "antes do cancelamento"
    assert history.get_context(session=SESSION, conversation_id="conv-cancel") == []
    assert any(
        item["labels"].get("status") == "cancelled"
        for item in telemetry.snapshot()["stream"]["outcomes"]
    )


@pytest.mark.asyncio
async def test_validated_completion_persists_complete_status_and_context():
    history = InMemoryChatHistoryStore()
    telemetry = ApiTelemetry()
    service = ChatApplicationService(CompletingStreamBackend(), history, telemetry=telemetry)

    events = await _collect(service.stream_events(
        session=SESSION, message="pergunta concluída", conversation_id="conv-complete",
        collection_id=None, workspace_id=None, mode="grounded",
    ))

    assert [event["type"] for event in events] == ["start", "delta", "completion"]
    assert events[0]["provisional"] is True
    assert events[1]["provisional"] is True
    assert events[2]["provisional"] is False
    stored = history.list_history(session=SESSION)[0]
    assert stored["metadata"]["stream_status"] == "complete"
    assert stored["metadata"]["stream_mode"] == "live"
    assert history.get_context(session=SESSION, conversation_id="conv-complete") == [
        {"role": "user", "content": "pergunta concluída"},
        {"role": "assistant", "content": "resposta concluída"},
    ]
    assert any(
        item["labels"].get("status") == "complete"
        for item in telemetry.snapshot()["stream"]["outcomes"]
    )


@pytest.mark.asyncio
async def test_stream_outcome_persistence_failure_is_explicit_and_metrics_are_kept():
    telemetry = ApiTelemetry()
    service = ChatApplicationService(
        FailingStreamBackend(), FailingOutcomeHistory(), telemetry=telemetry,
    )

    with pytest.raises(RuntimeError, match="stream outcome persistence failed"):
        await _collect(service.stream_events(
            session=SESSION, message="pergunta", conversation_id="conv-failing-history",
            collection_id=None, workspace_id=None, mode="grounded",
        ))

    assert any(
        item["labels"].get("status") == "partial"
        for item in telemetry.snapshot()["stream"]["outcomes"]
    )
