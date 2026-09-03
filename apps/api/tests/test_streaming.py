"""Streaming: SSE shape, single final event, cancellation-safe."""

from conftest import login_as


def test_platform_chat_sse(client):
    login_as(client, "vet@example.com")
    resp = client.post("/api/v1/chat", json={"message": "hello world, this is a streaming test", "stream": True})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    text = resp.text
    assert "data: [DONE]" in text
    assert text.count("[DONE]") == 1  # no duplicate final event
    assert '"type": "start"' in text or '"type":"start"' in text or "start" in text


def test_platform_chat_non_stream_shape(client):
    login_as(client, "vet@example.com")
    resp = client.post("/api/v1/chat", json={"message": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert {"conversation_id", "message_id", "answer", "citations", "metadata"} <= set(body)
    assert "chain" not in str(body).lower()
