"""Reject offsets beyond any common Unicode representation of the message.

These controls do not select the provider's exact Unicode indexing convention.
"""
import pytest

from test_production_rework13_metadata import (
    citation, completion, frame, openai_wire, public_response, trailer,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "openai_compatible"])
@pytest.mark.parametrize("mode", ["buffer", "early", "delta", "terminal"])
@pytest.mark.parametrize("text,end", [("é", 3), ("😀", 5), ("e\u0301", 4), ("日本語", 200)])
async def test_impossible_unicode_citation_endpoint(kind, mode, text, end):
    annotations = {"annotations": [citation(0, end)]}
    if mode == "buffer":
        payload = completion(text)
        payload["choices"][0]["message"].update(annotations)
    else:
        first = {"content": text[:1]}
        last = {"content": text[1:]}
        if mode == "delta":
            first.update(annotations)
        if mode == "terminal":
            last.update(annotations)
        events = ([frame(annotations)] if mode == "early" else []) + [
            frame(first), frame(last, "stop"), trailer(),
        ]
        payload = openai_wire(events)
    await public_response(kind, "buffer" if mode == "buffer" else "stream", payload, False, text)
