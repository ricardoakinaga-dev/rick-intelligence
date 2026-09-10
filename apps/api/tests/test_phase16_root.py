"""Public Phase 1.6 lifecycle: upload -> publish -> retrieve -> mutate safely."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app import create_app
from conftest import make_settings


def _client(**overrides) -> TestClient:
    values = {
        "environment": "local",
        "chat_backend_mode": "professor",
        "compat_api_key": "phase16-secret",
    }
    values.update(overrides)
    return TestClient(create_app(make_settings(**values)), raise_server_exceptions=False)


def _login(client: TestClient, email: str, *, tenant_id: str = "default") -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123", "tenant_id": tenant_id},
    )
    assert response.status_code == 200, response.text


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    for _ in range(100):
        response = client.get(f"/api/v1/ingestion/jobs/{job_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["job"]["status"] in {"published", "failed", "cancelled"}:
            job = body["job"]
            return {
                "status": body["status"],
                "job": job,
                "document": body.get("document"),
                "job_id": job["job_id"],
                "document_id": job.get("document_id"),
            }
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _upload(client: TestClient, *, filename: str, content: bytes, content_type: str = "text/plain") -> dict:
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, content, content_type)},
        data={"collection_id": "rag_phase0"},
    )
    assert response.status_code == 202, response.text
    return _wait_for_job(client, response.json()["job_id"])


def test_upload_publishes_and_root_chat_cites_uploaded_provenance() -> None:
    client = _client()
    _login(client, "km@example.com")
    content = (
        b"# Protocolo de ordenha\n\n"
        b"Mastite alfa exige higiene do ubre e avaliacao veterinaria imediata."
    )

    body = _upload(client, filename="alfa.md", content=content, content_type="text/markdown")
    job = body["job"]
    assert job["status"] == "published"
    assert job["metadata"] == {
        "execution": "process-local",
        "durability": "process-local",
        "restart_recovery": False,
        "storage": "private-temporary",
    }
    assert "path" not in str(body).lower()
    document_id = body["document_id"]

    status = client.get(f"/api/v1/ingestion/jobs/{body['job_id']}")
    assert status.status_code == 200
    assert status.json()["job"]["document_id"] == document_id

    documents = client.get("/api/v1/documents").json()["items"]
    listed = next(item for item in documents if item["document_id"] == document_id)
    assert listed["title"] == "alfa.md"
    assert "text" not in listed

    response = client.post(
        "/api/v1/chat",
        json={"message": "Qual protocolo de higiene para mastite alfa?"},
    )
    assert response.status_code == 200, response.text
    citation_ids = {citation["document_id"] for citation in response.json()["citations"]}
    assert document_id in citation_ids
    citation = next(c for c in response.json()["citations"] if c["document_id"] == document_id)
    assert citation["title"] == "alfa.md"
    assert citation["page_start"] == 1 and citation["page_end"] == 1
    assert citation["checksum"]


def test_default_local_stub_backend_uses_root_retrieval_after_upload(monkeypatch) -> None:
    monkeypatch.delenv("RICK_API_ROOT_RETRIEVAL", raising=False)
    client = TestClient(create_app(make_settings()))
    _login(client, "km@example.com")
    uploaded = _upload(client, filename="default.txt", content=b"Fonte local padrao para consulta")
    document_id = uploaded["document_id"]

    response = client.post("/api/v1/chat", json={"message": "Fonte local padrao"})

    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["backend"] == "stub"
    assert document_id in {item["document_id"] for item in response.json()["citations"]}


def test_root_ingestion_publishes_only_bounded_worker_events() -> None:
    client = _client()
    _login(client, "km@example.com")
    content = b"root worker event source that must never enter telemetry"

    uploaded = _upload(client, filename="worker-events.txt", content=content)
    events = [
        event for event in client.app.state.telemetry.snapshot()["events"]
        if event["event"].startswith("worker.ingestion.")
    ]
    names = [event["event"] for event in events]
    assert names == [
        "worker.ingestion.enqueued",
        "worker.ingestion.started",
        "worker.ingestion.published",
    ]
    rendered = str(events)
    assert uploaded["job_id"] not in rendered
    assert "worker-events.txt" not in rendered
    assert "root worker event source" not in rendered
    assert "tenant_id" not in rendered
    assert "workspace_id" not in rendered
    assert "collection_id" not in rendered
    for event in events:
        assert set(event["fields"]) <= {
            "job_ref", "worker_ref", "request_ref", "correlation_ref", "status",
            "stage", "progress", "attempt", "attempts", "error_code", "changed", "count",
        }


def test_root_ingestion_reentrant_and_broken_sinks_cannot_change_outcome() -> None:
    client = _client()
    _login(client, "km@example.com")
    service = client.app.state.providers.ingestion
    observed: list[str] = []

    def reentrant_sink(event):
        observed.append(event["event"])
        assert service.list_jobs(
            tenant_id="default",
            workspace_id="default",
            allowed_collection_ids=["rag_phase0"],
        )

    service.event_sink = reentrant_sink
    uploaded = _upload(client, filename="reentrant.txt", content=b"reentrant root worker")
    assert uploaded["job"]["status"] == "published"
    assert "worker.ingestion.published" in observed

    def broken_sink(_event):
        raise RuntimeError("sink failure must stay outside ingestion")

    service.event_sink = broken_sink
    second = _upload(client, filename="broken-sink.txt", content=b"broken sink root worker")
    assert second["job"]["status"] == "published"


def test_public_upload_returns_a_cancellable_job_before_slow_processing(monkeypatch) -> None:
    import threading

    from rick_ingestion import ParsedDocument, ParsedPage

    started = threading.Event()
    release = threading.Event()

    class SlowParser:
        def parse(self, path, *, workspace_id):
            started.set()
            release.wait(2)
            return ParsedDocument(text="cancelled source", pages=[ParsedPage(page_number=1, text="cancelled source")])

    monkeypatch.setattr(
        "rick_ingestion.pipeline.parser_for",
        lambda path, *, pdf_heartbeat=None: SlowParser(),
    )
    client = _client()
    _login(client, "km@example.com")

    submitted = client.post(
        "/api/v1/documents/upload",
        files={"file": ("slow.txt", b"slow source " * 20, "text/plain")},
        data={"collection_id": "rag_phase0"},
    )

    assert submitted.status_code == 202, submitted.text
    submitted_body = submitted.json()
    assert submitted_body["status"] == "queued"
    assert started.wait(1)
    cancelled = client.post(f"/api/v1/ingestion/jobs/{submitted_body['job_id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    release.set()
    terminal = _wait_for_job(client, submitted_body["job_id"])
    assert terminal["status"] == "cancelled"


def test_unscoped_legacy_cancel_fails_closed_without_mutating_job(monkeypatch) -> None:
    client = _client()
    _login(client, "km@example.com")
    uploaded = _upload(client, filename="legacy-cancel.txt", content=b"legacy cancel contract")
    service = client.app.state.providers.ingestion
    calls: list[str] = []

    def unscoped_cancel(job_id: str) -> bool:
        calls.append(job_id)
        return True

    monkeypatch.setattr(service, "cancel", unscoped_cancel)

    response = client.post(f"/api/v1/ingestion/jobs/{uploaded['job_id']}/cancel")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"
    assert calls == []
    status = client.get(f"/api/v1/ingestion/jobs/{uploaded['job_id']}")
    assert status.status_code == 200
    assert status.json()["job"]["status"] == "published"


def test_document_listing_is_acl_filtered_and_cursor_bounded() -> None:
    client = _client()
    _login(client, "km@example.com")
    for name in ("page-a.txt", "page-b.txt"):
        _upload(client, filename=name, content=name.encode())

    first = client.get("/api/v1/documents", params={"limit": 1}).json()
    assert len(first["items"]) == 1
    assert first["next_cursor"]
    second = client.get(
        "/api/v1/documents",
        params={"limit": 1, "cursor": first["next_cursor"]},
    ).json()
    assert len(second["items"]) == 1
    assert second["items"][0]["document_id"] != first["items"][0]["document_id"]
    assert first["total"] == second["total"] == 3


def test_document_listing_applies_acl_before_limit() -> None:
    from rick_knowledge import Document

    client = _client()
    identity = client.app.state.providers.identity
    identity._users.seed({
        "user_id": "limited",
        "email": "limited@example.com",
        "role": "VETERINARIAN",
        "tenant_id": "default",
        "workspace_id": "default",
        "status": "active",
        "permission_overrides": {"add": ["documents.read"], "remove": []},
        "authorized_collection_ids": ["rag_phase0"],
        "password_plain": "password123",
        "password_version": 1,
        "role_version": 1,
    })
    store = client.app.state.providers.knowledge
    store.upsert_document(Document(
        document_id="a-secret",
        workspace_id="default",
        collection_id="private-collection",
        tenant_id="default",
        title="must not consume the page",
        status="published",
    ))
    store.upsert_document(Document(
        document_id="b-visible",
        workspace_id="default",
        collection_id="rag_phase0",
        tenant_id="default",
        title="visible",
        status="published",
    ))
    _login(client, "limited@example.com")

    response = client.get("/api/v1/documents", params={"limit": 1})

    assert response.status_code == 200, response.text
    assert [item["document_id"] for item in response.json()["items"]] == ["b-visible"]
    assert response.json()["total"] == 2


def test_upload_rejects_unsupported_and_bounded_oversized_content() -> None:
    client = _client(max_upload_bytes=1024)
    _login(client, "km@example.com")

    unsupported = client.post(
        "/api/v1/documents/upload",
        files={"file": ("payload.exe", b"not a document", "application/octet-stream")},
        data={"collection_id": "rag_phase0"},
    )
    assert unsupported.status_code == 415
    assert unsupported.json()["error"]["code"] == "unsupported_media_type"

    mismatched_type = client.post(
        "/api/v1/documents/upload",
        files={"file": ("payload.txt", b"text payload", "application/pdf")},
        data={"collection_id": "rag_phase0"},
    )
    assert mismatched_type.status_code == 415
    assert mismatched_type.json()["error"]["code"] == "unsupported_media_type"

    oversized = client.post(
        "/api/v1/documents/upload",
        files={"file": ("large.txt", b"x" * 1025, "text/plain")},
        data={"collection_id": "rag_phase0"},
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "request_too_large"


def test_json_ingestion_rejects_nonfinite_and_duplicate_request_fields() -> None:
    client = _client()
    _login(client, "km@example.com")
    headers = {"Content-Type": "application/json"}

    nonfinite = client.post(
        "/api/v1/documents/upload",
        content=b'{"filename":"strict.txt","collection_id":"rag_phase0","content":"ok","metadata":NaN}',
        headers=headers,
    )
    duplicate = client.post(
        "/api/v1/documents/upload",
        content=b'{"filename":"strict.txt","collection_id":"rag_phase0","content":"first","content":"second"}',
        headers=headers,
    )

    assert nonfinite.status_code == 400
    assert nonfinite.json()["error"]["code"] == "validation_error"
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["code"] == "validation_error"


def test_retry_requires_a_new_bounded_source_and_never_relabels_failed_attempt() -> None:
    client = _client()
    _login(client, "km@example.com")
    providers = client.app.state.providers
    application = providers.ingestion
    canonical = application.ingestion
    original_vectors = canonical.vectors

    class FailOnceVectorStore:
        def __init__(self, delegate):
            self.delegate = delegate
            self.fail_next = True

        def upsert_points(self, points):
            if self.fail_next:
                self.fail_next = False
                self.delegate.upsert_points(points[:1])
                raise RuntimeError("simulated vector store outage")
            return self.delegate.upsert_points(points)

        def delete_document(self, document_id, collection_id):
            return self.delegate.delete_document(document_id, collection_id)

        def count_for_document(self, document_id, collection_id):
            return self.delegate.count_for_document(document_id, collection_id)

        def all_points(self):
            return self.delegate.all_points()

    failing_vectors = FailOnceVectorStore(original_vectors)
    canonical.vectors = failing_vectors
    application.refresh_callback = lambda: providers.retrieval.attach_points(failing_vectors.all_points())

    failed_body = _upload(client, filename="retry.txt", content=b"temporary provider failure " * 20)
    assert failed_body["status"] == "failed"
    assert failed_body["job"]["error_code"] == "storage_unavailable"
    assert failed_body["job"]["retryable"] is True

    retried = client.post(
        f"/api/v1/ingestion/jobs/{failed_body['job_id']}/retry",
        json={"filename": "retry.txt", "content": "retry succeeds " * 20},
    )
    assert retried.status_code == 200, retried.text
    retry_body = retried.json()
    assert retry_body["status"] == "published"
    assert retry_body["job_id"] != failed_body["job_id"]
    assert client.get(f"/api/v1/ingestion/jobs/{failed_body['job_id']}").json()["status"] == "failed"

    permanent = client.post(
        "/api/v1/documents/upload",
        files={"file": ("bad.exe", b"not supported", "application/octet-stream")},
        data={"collection_id": "rag_phase0"},
    )
    assert permanent.status_code == 415


def test_retry_budget_is_finite() -> None:
    client = _client()
    _login(client, "km@example.com")
    application = client.app.state.providers.ingestion
    canonical = application.ingestion
    delegate = canonical.vectors

    class AlwaysFailVectorStore:
        def upsert_points(self, points):
            raise RuntimeError("persistent vector outage")

        def delete_document(self, document_id, collection_id):
            return delegate.delete_document(document_id, collection_id)

        def count_for_document(self, document_id, collection_id):
            return delegate.count_for_document(document_id, collection_id)

        def all_points(self):
            return delegate.all_points()

    canonical.vectors = AlwaysFailVectorStore()
    failed = _upload(client, filename="budget.txt", content=b"retry budget " * 20)
    for index in range(3):
        retry = client.post(
            f"/api/v1/ingestion/jobs/{failed['job_id']}/retry",
            json={"filename": "budget.txt", "content": f"retry {index} " * 20},
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["status"] == "failed"

    exhausted = client.post(
        f"/api/v1/ingestion/jobs/{failed['job_id']}/retry",
        json={"filename": "budget.txt", "content": "one more retry " * 20},
    )
    assert exhausted.status_code == 409
    assert exhausted.json()["error"]["code"] == "conflict"


def test_chunked_multipart_cannot_bypass_upload_limit() -> None:
    import httpx

    class Chunks(httpx.SyncByteStream):
        def __init__(self, parts: list[bytes]) -> None:
            self.parts = parts

        def __iter__(self):
            yield from self.parts

    client = _client(max_upload_bytes=100)
    _login(client, "km@example.com")
    boundary = "phase16-boundary"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"collection_id\"\r\n\r\n"
        f"rag_phase0\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"x.txt\"\r\n"
        "Content-Type: text/plain\r\n\r\n"
    ).encode() + b"x" * 150 + f"\r\n--{boundary}--\r\n".encode()
    response = client.post(
        "/api/v1/documents/upload",
        content=Chunks([body[:80], body[80:]]),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_chunked_json_cannot_bypass_request_limit() -> None:
    import httpx

    class Chunks(httpx.SyncByteStream):
        def __init__(self, parts: list[bytes]) -> None:
            self.parts = parts

        def __iter__(self):
            yield from self.parts

    client = _client(max_json_bytes=100)
    _login(client, "km@example.com")
    body = b'{"filename":"x.txt","collection_id":"rag_phase0","content":"' + b"x" * 150 + b'"}'
    response = client.post(
        "/api/v1/documents/upload",
        content=Chunks([body[:37], body[37:]]),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_reindex_and_delete_remove_old_retrieval_state_without_cross_scope_oracle() -> None:
    client = _client()
    _login(client, "km@example.com")
    uploaded = _upload(client, filename="beta.txt", content=b"Frase beta original sobre manejo")
    old_id = uploaded["document_id"]

    reindexed = client.post(
        "/api/v1/ingestion/reindex",
        json={"document_id": old_id, "content": "Frase beta atualizada sobre manejo seguro"},
    )
    assert reindexed.status_code == 200, reindexed.text
    new_id = reindexed.json()["document_id"]
    assert new_id and new_id != old_id

    deleted = client.delete(f"/api/v1/documents/{new_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert client.get(f"/api/v1/documents/{new_id}").status_code == 404
    assert client.post(
        "/api/v1/chat",
        json={"message": "Frase beta atualizada sobre manejo seguro"},
    ).json()["citations"] == []

    _login(client, "vet@example.com")
    assert client.get(f"/api/v1/ingestion/jobs/{uploaded['job_id']}").status_code == 403
    assert client.get(f"/api/v1/documents/{new_id}").status_code == 403


def test_tenant_scope_is_propagated_and_cross_tenant_lifecycle_is_opaque() -> None:
    owner = _client()
    foreign = TestClient(owner.app, raise_server_exceptions=False)
    identity = owner.app.state.providers.identity
    identity._users.seed({
        "user_id": "km-tenant-b",
        "email": "km-tenant-b@example.com",
        "role": "KNOWLEDGE_MANAGER",
        "tenant_id": "tenant-b",
        "workspace_id": "default",
        "status": "active",
        "permission_overrides": {"add": [], "remove": []},
        "authorized_collection_ids": [],
        "password_plain": "password123",
        "password_version": 1,
        "role_version": 1,
    })

    _login(owner, "km@example.com")
    _login(foreign, "km-tenant-b@example.com", tenant_id="tenant-b")
    owner_upload = _upload(owner, filename="tenant-a.txt", content=b"tenant a source")
    foreign_upload = _upload(foreign, filename="tenant-b.txt", content=b"tenant b source")

    owner_job = owner_upload["job"]
    foreign_job = foreign_upload["job"]
    owner_document_id = owner_upload["document_id"]
    foreign_document_id = foreign_upload["document_id"]
    assert owner_job["tenant_id"] == "default"
    assert foreign_job["tenant_id"] == "tenant-b"
    assert owner.app.state.providers.knowledge.get_document(owner_document_id).tenant_id == "default"
    assert owner.app.state.providers.knowledge.get_document(foreign_document_id).tenant_id == "tenant-b"

    owner_collections = owner.get("/api/v1/collections")
    foreign_collections = foreign.get("/api/v1/collections")
    assert owner_collections.status_code == 200, owner_collections.text
    assert foreign_collections.status_code == 200, foreign_collections.text
    assert "rag_phase0" in {item["collection_id"] for item in owner_collections.json()["items"]}
    assert "rag_phase0" in {item["collection_id"] for item in foreign_collections.json()["items"]}

    owner_documents = owner.get("/api/v1/documents")
    foreign_documents = foreign.get("/api/v1/documents")
    assert owner_documents.status_code == 200, owner_documents.text
    assert foreign_documents.status_code == 200, foreign_documents.text
    owner_listed_ids = {item["document_id"] for item in owner_documents.json()["items"]}
    foreign_listed_ids = {item["document_id"] for item in foreign_documents.json()["items"]}
    assert owner_document_id in owner_listed_ids
    assert foreign_document_id not in owner_listed_ids
    assert foreign_document_id in foreign_listed_ids
    assert owner_document_id not in foreign_listed_ids

    assert owner.get(f"/api/v1/documents/{foreign_document_id}").status_code == 404
    assert foreign.get(f"/api/v1/documents/{owner_document_id}").status_code == 404
    assert owner.get(f"/api/v1/ingestion/jobs/{foreign_upload['job_id']}").status_code == 404
    assert foreign.get(f"/api/v1/ingestion/jobs/{owner_upload['job_id']}").status_code == 404
    assert owner_document_id in {
        item["document_id"]
        for item in owner.post("/api/v1/search", json={"query": "tenant a source"}).json()["items"]
    }
    assert foreign_document_id not in {
        item["document_id"]
        for item in owner.post("/api/v1/search", json={"query": "tenant b source"}).json()["items"]
    }
    assert foreign_document_id in {
        item["document_id"]
        for item in foreign.post("/api/v1/search", json={"query": "tenant b source"}).json()["items"]
    }
    assert owner_document_id not in {
        item["document_id"]
        for item in foreign.post("/api/v1/search", json={"query": "tenant a source"}).json()["items"]
    }

    assert foreign.delete(f"/api/v1/documents/{owner_document_id}").status_code == 404
    assert foreign.post(
        "/api/v1/ingestion/reindex",
        json={"document_id": owner_document_id, "content": "cross tenant probe"},
    ).status_code == 404
    assert foreign.post(f"/api/v1/ingestion/jobs/{owner_upload['job_id']}/cancel").status_code == 404
    assert foreign.post(
        f"/api/v1/ingestion/jobs/{owner_upload['job_id']}/retry",
        json={"filename": "cross.txt", "content": "cross tenant probe"},
    ).status_code == 404
    assert owner.get(f"/api/v1/documents/{owner_document_id}").status_code == 200
    assert foreign.get(f"/api/v1/documents/{foreign_document_id}").status_code == 200


def test_legacy_knowledge_rollback_keeps_non_default_tenant_empty(monkeypatch) -> None:
    client = _client()
    identity = client.app.state.providers.identity
    identity._users.seed({
        "user_id": "km-tenant-c",
        "email": "km-tenant-c@example.com",
        "role": "KNOWLEDGE_MANAGER",
        "tenant_id": "tenant-c",
        "workspace_id": "default",
        "status": "active",
        "permission_overrides": {"add": [], "remove": []},
        "authorized_collection_ids": [],
        "password_plain": "password123",
        "password_version": 1,
        "role_version": 1,
    })
    _login(client, "km-tenant-c@example.com", tenant_id="tenant-c")
    monkeypatch.setenv("RICK_API_ROOT_KNOWLEDGE", "0")

    assert client.get("/api/v1/collections").json() == {"items": [], "total": 0}
    assert client.get("/api/v1/documents").json()["items"] == []
    assert client.get("/api/v1/documents/doc-stub-1").status_code == 404


def test_reindex_retirement_failure_keeps_the_old_public_version() -> None:
    client = _client()
    _login(client, "km@example.com")
    uploaded = _upload(client, filename="atomic-api.txt", content=b"versao antiga consultavel " * 20)
    old_id = uploaded["document_id"]
    application = client.app.state.providers.ingestion
    canonical = application.ingestion
    delegate = canonical.vectors

    class FailOldRetirement:
        def upsert_points(self, points):
            return delegate.upsert_points(points)

        def delete_document(self, document_id, collection_id):
            if document_id == old_id:
                raise RuntimeError("old retirement unavailable")
            return delegate.delete_document(document_id, collection_id)

        def count_for_document(self, document_id, collection_id):
            return delegate.count_for_document(document_id, collection_id)

        def all_points(self):
            return delegate.all_points()

    canonical.vectors = FailOldRetirement()
    failed = client.post(
        "/api/v1/ingestion/reindex",
        json={"document_id": old_id, "content": "versao nova sem aposentadoria segura " * 20},
    )

    assert failed.status_code == 200, failed.text
    body = failed.json()
    assert body["status"] == "failed"
    assert body["job"]["error_code"] == "storage_unavailable"
    assert client.get(f"/api/v1/documents/{old_id}").status_code == 200
    assert canonical.vectors.count_for_document(old_id, "rag_phase0") > 0
    assert body["document_id"]
    assert client.get(f"/api/v1/documents/{body['document_id']}").status_code == 404


def test_delete_snapshot_failure_preserves_document_and_vectors() -> None:
    client = _client()
    _login(client, "km@example.com")
    uploaded = _upload(client, filename="snapshot.txt", content=b"preservar documento e vetores " * 20)
    document_id = uploaded["document_id"]
    canonical = client.app.state.providers.ingestion.ingestion
    delegate = canonical.vectors
    before = delegate.all_points()

    class UnreadableSnapshot:
        def all_points(self, **kwargs):
            raise RuntimeError("private storage failure")

        def delete_document(self, *args):
            raise AssertionError("deletion must not start without the snapshot")

    canonical.vectors = UnreadableSnapshot()
    response = client.delete(f"/api/v1/documents/{document_id}")
    assert response.status_code == 503
    assert "private storage failure" not in response.text
    assert delegate.all_points() == before
    assert client.get(f"/api/v1/documents/{document_id}").status_code == 200


def test_delete_waits_for_operation_without_blocking_publication_lock() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    client = _client()
    application = client.app.state.providers.ingestion
    canonical = application.ingestion
    operation = canonical.operation_guard()
    attempted = Event()

    def observed_guard():
        attempted.set()
        return operation

    canonical.operation_guard = observed_guard
    with ThreadPoolExecutor(max_workers=1) as pool:
        with operation:
            pending = pool.submit(
                application.delete_document, "missing-document",
                workspace_id="default", allowed_collection_ids=["rag_phase0"],
            )
            assert attempted.wait(2)
            acquired = application._lock.acquire(timeout=0.2)
            try:
                assert acquired, "waiting mutation must not block async publication"
            finally:
                if acquired:
                    application._lock.release()
        assert pending.result(timeout=2) is None


def test_delete_chunk_snapshot_failure_never_starts_deletion() -> None:
    client = _client()
    _login(client, "km@example.com")
    uploaded = _upload(client, filename="chunks.txt", content=b"preservar chunks publicados " * 400)
    document_id = uploaded["document_id"]
    canonical = client.app.state.providers.ingestion.ingestion
    knowledge = canonical.knowledge
    points = canonical.vectors.all_points()
    chunks = knowledge.get_chunks(document_id)
    deletes = []

    class UnreadableChunks:
        def __getattr__(self, name):
            return getattr(knowledge, name)

        def get_chunks(self, target_id):
            raise RuntimeError("private chunk failure")

        def delete_document(self, target_id):
            deletes.append(target_id)
            knowledge.delete_document(target_id)
            raise RuntimeError("lost acknowledgement")

    canonical.knowledge = UnreadableChunks()
    response = client.delete(f"/api/v1/documents/{document_id}")
    assert response.status_code == 503
    assert "private chunk failure" not in response.text
    assert deletes == []
    assert canonical.vectors.all_points() == points
    assert chunks and knowledge.get_chunks(document_id) == chunks
    assert knowledge.get_document(document_id).status == "published"


def test_delete_failure_is_compensated_without_hiding_the_document() -> None:
    client = _client()
    _login(client, "km@example.com")
    uploaded = _upload(client, filename="delete-atomic.txt", content=b"nao perder este documento " * 20)
    document_id = uploaded["document_id"]
    application = client.app.state.providers.ingestion
    canonical = application.ingestion
    original_knowledge = canonical.knowledge

    class FailAfterMetadataDelete:
        def __getattr__(self, name):
            return getattr(original_knowledge, name)

        def delete_document(self, target_id):
            result = original_knowledge.delete_document(target_id)
            raise RuntimeError("metadata acknowledgement lost")

    canonical.knowledge = FailAfterMetadataDelete()
    deleted = client.delete(f"/api/v1/documents/{document_id}")

    assert deleted.status_code == 503
    assert deleted.json()["error"]["code"] == "storage_unavailable"
    assert client.get(f"/api/v1/documents/{document_id}").status_code == 200
    assert canonical.vectors.count_for_document(document_id, "rag_phase0") > 0


def test_readiness_reports_selected_local_components_and_admin_jobs_are_real() -> None:
    client = _client()
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    names = {check["name"] for check in ready.json()["checks"]}
    assert {"kernel", "retrieval", "ingestion", "storage"} <= names

    _login(client, "admin@example.com")
    jobs = client.get("/api/v1/admin/jobs")
    assert jobs.status_code == 200
    assert jobs.json()["metadata"]["durability"] == "process-local"


def test_admin_jobs_legacy_fallback_applies_tenant_workspace_and_collection_acl(monkeypatch) -> None:
    client = _client()
    identity = client.app.state.providers.identity
    identity._users.seed({
        "user_id": "restricted-runtime",
        "email": "restricted-runtime@example.com",
        "role": "VETERINARIAN",
        "tenant_id": "default",
        "workspace_id": "default",
        "status": "active",
        "permission_overrides": {"add": ["runtime.manage"], "remove": []},
        "authorized_collection_ids": ["collection-a"],
        "password_plain": "password123",
        "password_version": 1,
        "role_version": 1,
    })
    _login(client, "restricted-runtime@example.com")
    service = client.app.state.providers.ingestion

    def legacy_list_jobs():
        return [
            {
                "job_id": "visible",
                "status": "queued",
                "stage": "queued",
                "tenant_id": "default",
                "workspace_id": "default",
                "collection_id": "collection-a",
            },
            {
                "job_id": "foreign-collection",
                "status": "queued",
                "stage": "queued",
                "tenant_id": "default",
                "workspace_id": "default",
                "collection_id": "collection-b",
            },
            {
                "job_id": "foreign-tenant",
                "status": "queued",
                "stage": "queued",
                "tenant_id": "tenant-b",
                "workspace_id": "default",
                "collection_id": "collection-a",
            },
            {
                "job_id": "foreign-workspace",
                "status": "queued",
                "stage": "queued",
                "tenant_id": "default",
                "workspace_id": "workspace-b",
                "collection_id": "collection-a",
            },
        ]

    monkeypatch.setattr(service, "list_jobs", legacy_list_jobs)

    response = client.get("/api/v1/admin/jobs")

    assert response.status_code == 200, response.text
    assert [item["job_id"] for item in response.json()["items"]] == ["visible"]
