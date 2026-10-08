"""Actual publication gates observe persisted catalog writes after detachment."""
import asyncio

import pytest

from test_decision_policy_publication import CountedProvider, _backend, _request


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["json", "stream", "buffered_stream"])
async def test_persisted_archive_during_generation_denies_publication(path):
    provider = CountedProvider(wait=True)
    if path == "buffered_stream":
        provider.chat_completion_stream = None
    backend, store, _, _ = _backend(provider=provider)
    async def run():
        if path == "json":
            return await backend.orchestrator.run(_request()), []
        events = [event async for event in backend.orchestrator.stream(_request())]
        return events[-1]["response"], events
    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(provider.started.wait(), 2)
        collection = store.get_collection("default", "rag_phase0", tenant_id="default")
        collection.status = "archived"
        # The public catalog writer participates in the common fence.
        store.upsert_collection(collection)
    finally:
        provider.resume.set()
    response, events = await asyncio.wait_for(task, 2)
    assert provider.calls == 1
    assert response.evidence_status == "CITATION_INVALID"
    assert response.citations == response.evidence == []
    assert response.metadata["decision_reason"] == "publication_sources_changed"
    assert response.metadata["publication_validation"] == "failed"
    assert all(event.get("provisional") is True for event in events if event["kind"] == "delta")
