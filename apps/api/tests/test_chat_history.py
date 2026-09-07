from conftest import login_as


def test_chat_history_and_sources_are_scoped_and_bounded(client):
    from services.chat_history import InMemoryChatHistoryStore

    client.app.state.providers.chat_history = InMemoryChatHistoryStore()
    login_as(client, "km@example.com")

    response = client.post("/api/v1/chat", json={"message": "Quais fontes estão disponíveis?"})
    assert response.status_code == 200, response.text

    history = client.get("/api/v1/history", params={"limit": 10})
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    item = history.json()["items"][0]
    assert item["question"] == "Quais fontes estão disponíveis?"
    assert "tenant_id" not in item and "user_id" not in item

    sources = client.get("/api/v1/sources", params={"limit": 10})
    assert sources.status_code == 200, sources.text
    # The stub no longer fabricates a source when no retrieval evidence exists.
    assert sources.json()["total"] == 0


def test_history_store_does_not_cross_user_scope(client):
    from services.chat_history import InMemoryChatHistoryStore

    client.app.state.providers.chat_history = InMemoryChatHistoryStore()
    login_as(client, "km@example.com")
    assert client.post("/api/v1/chat", json={"message": "pergunta privada"}).status_code == 200
    client.post("/api/v1/auth/logout")

    login_as(client, "vet@example.com")
    history = client.get("/api/v1/history")
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 0
