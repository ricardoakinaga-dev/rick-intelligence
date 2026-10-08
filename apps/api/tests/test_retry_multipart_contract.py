"""Exercise binary transport and resource ownership through the HTTP API.

The ingestion double observes transport only; parser/publication and retry
budgets are exercised separately in test_phase16_root.py.
"""
from __future__ import annotations

import hashlib
import time
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app import create_app
from conftest import make_settings


class CapturingIngestion:
    def __init__(self):
        self.calls = []
        self.job = {
            "job_id": "original", "status": "failed", "stage": "failed",
            "tenant_id": "default", "workspace_id": "default",
            "collection_id": "rag_phase0", "error_code": "storage_unavailable",
        }

    def get_status(self, job_id, **scope):
        return self.job if job_id == "original" else None

    def upload(self, *args, **kwargs):
        raise AssertionError("A retry must use the retry service boundary")

    def retry(self, job_id, *, source, filename, **scope):
        raw = source.encode() if isinstance(source, str) else source.file.read()
        self.calls.append({
            "job_id": job_id, "filename": filename, "bytes": raw,
            "checksum": hashlib.sha256(raw).hexdigest(), "scope": scope,
            "file": getattr(source, "file", None),
        })
        return {**self.job, "job_id": "retried", "status": "published", "stage": "published"}


@pytest.fixture()
def transport_client():
    app = create_app(make_settings())
    service = CapturingIngestion()
    app.state.providers.ingestion = service
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/auth/login", json={
            "email": "km@example.com", "password": "password123", "tenant_id": "default",
        })
        assert response.status_code == 200
        yield client, service


@pytest.mark.parametrize("filename,mime,content", [
    ("original.pdf", "application/pdf", b"%PDF-1.4\n\xe2\xe3\xcf\xd3\x00\xff\n"),
    ("original.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK\x03\x04\x00\xff\x80\r\n"),
    ("original.txt", "text/plain", "Fonte com acentuação\r\n".encode()),
])
def test_retry_preserves_exact_bytes_name_checksum_and_scope(transport_client, filename, mime, content):
    client, service = transport_client
    response = client.post("/api/v1/ingestion/jobs/original/retry", files={"file": (filename, content, mime)})
    assert response.status_code == 200, response.text
    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["bytes"] == content
    assert call["checksum"] == hashlib.sha256(content).hexdigest()
    assert call["filename"] == filename
    assert call["scope"]["tenant_id"] == "default"
    assert call["scope"]["workspace_id"] == "default"
    assert "rag_phase0" in call["scope"]["allowed_collection_ids"] or "*" in call["scope"]["allowed_collection_ids"]
    assert call["file"].closed


def test_retry_legacy_json_remains_supported(transport_client):
    client, service = transport_client
    response = client.post("/api/v1/ingestion/jobs/original/retry", json={"filename": "source.txt", "content": "fonte"})
    assert response.status_code == 200
    assert service.calls[0]["bytes"] == b"fonte"


def test_retry_reuses_same_docx_bytes_after_transient_storage_failure(monkeypatch):
    import zipfile

    from rick_ingestion.parsers import InProcessParserRunner, ParsedDocument, ParsedPage
    from rick_ingestion import pipeline as ingestion_pipeline

    app = create_app(make_settings())
    source = BytesIO()
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", b"<document/>")
    source_bytes = source.getvalue()
    expected_checksum = hashlib.sha256(source_bytes).hexdigest()

    with TestClient(app, raise_server_exceptions=False) as client:
        login = client.post("/api/v1/auth/login", json={
            "email": "km@example.com", "password": "password123", "tenant_id": "default",
        })
        assert login.status_code == 200, login.text

        application = client.app.state.providers.ingestion
        pipeline = application.ingestion
        original_vectors = pipeline.vectors
        observed: list[dict[str, object]] = []
        retry_scopes: list[dict[str, object]] = []
        original_run_ingest = application._run_ingest
        original_retry = application.retry

        class SyntheticDocxParser:
            def parse(self, path, *, workspace_id):
                return ParsedDocument(
                    text="Synthetic DOCX parser output for retry verification.",
                    pages=[ParsedPage(
                        page_number=1,
                        text="Synthetic DOCX parser output for retry verification.",
                    )],
                )

        monkeypatch.setattr(
            ingestion_pipeline,
            "parser_for",
            lambda path, **kwargs: SyntheticDocxParser(),
        )
        monkeypatch.setattr(pipeline, "parser_runner", InProcessParserRunner())

        def capture_run_ingest(path, *, display_filename, tenant_id, workspace_id,
                               collection_id, **kwargs):
            observed.append({
                "bytes": path.read_bytes(),
                "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
                "filename": display_filename,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "collection_id": collection_id,
            })
            return original_run_ingest(
                path,
                display_filename=display_filename,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                collection_id=collection_id,
                **kwargs,
            )

        def capture_retry(job_id, **kwargs):
            retry_scopes.append({
                key: kwargs[key]
                for key in ("tenant_id", "workspace_id", "allowed_collection_ids")
            })
            return original_retry(job_id, **kwargs)

        class FailOnceVectorStore:
            def __init__(self, delegate):
                self.delegate = delegate
                self.fail_next = True

            def upsert_points(self, points):
                if self.fail_next:
                    self.fail_next = False
                    self.delegate.upsert_points(points[:1])
                    raise RuntimeError("simulated transient vector-store outage")
                return self.delegate.upsert_points(points)

            def delete_document(self, document_id, collection_id):
                return self.delegate.delete_document(document_id, collection_id)

            def count_for_document(self, document_id, collection_id):
                return self.delegate.count_for_document(document_id, collection_id)

            def all_points(self):
                return self.delegate.all_points()

        failing_vectors = FailOnceVectorStore(original_vectors)
        pipeline.vectors = failing_vectors
        client.app.state.providers.ingestion.refresh_callback = (
            lambda: client.app.state.providers.retrieval.attach_points(failing_vectors.all_points())
        )
        monkeypatch.setattr(application, "_run_ingest", capture_run_ingest)
        monkeypatch.setattr(application, "retry", capture_retry)

        upload = client.post(
            "/api/v1/documents/upload",
            files={"file": (
                "retained-source.docx",
                source_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )},
            data={"collection_id": "rag_phase0"},
        )
        assert upload.status_code == 202, upload.text
        original_job_id = upload.json()["job_id"]
        for _ in range(100):
            original_status = client.get(f"/api/v1/ingestion/jobs/{original_job_id}")
            assert original_status.status_code == 200, original_status.text
            if original_status.json()["status"] in {"failed", "published", "cancelled"}:
                break
            time.sleep(0.005)
        else:
            pytest.fail("initial upload did not reach a terminal job state")

        failed_job = original_status.json()["job"]
        assert failed_job["status"] == "failed"
        assert failed_job["error_code"] == "storage_unavailable"
        assert failed_job["attempt"] == 1

        retried = client.post(
            f"/api/v1/ingestion/jobs/{original_job_id}/retry",
            files={"file": (
                "retained-source.docx",
                source_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )},
        )
        assert retried.status_code == 200, retried.text
        retry_body = retried.json()
        retry_job = retry_body["job"]
        assert retry_job["status"] == "published"
        assert retry_job["attempt"] == 1
        assert retry_job["job_id"] != original_job_id

        original_after_retry = client.get(f"/api/v1/ingestion/jobs/{original_job_id}")
        assert original_after_retry.status_code == 200
        assert original_after_retry.json()["job"]["status"] == "failed"
        assert original_after_retry.json()["job"]["attempt"] == 1

        assert len(observed) == 2
        assert [item["bytes"] for item in observed] == [source_bytes, source_bytes]
        assert [item["checksum"] for item in observed] == [expected_checksum, expected_checksum]
        assert [item["filename"] for item in observed] == ["retained-source.docx"] * 2
        assert all(item["tenant_id"] == "default" for item in observed)
        assert all(item["workspace_id"] == "default" for item in observed)
        assert all(item["collection_id"] == "rag_phase0" for item in observed)
        assert len(retry_scopes) == 1
        assert retry_scopes[0]["tenant_id"] == "default"
        assert retry_scopes[0]["workspace_id"] == "default"
        assert (
            "rag_phase0" in retry_scopes[0]["allowed_collection_ids"]
            or "*" in retry_scopes[0]["allowed_collection_ids"]
        )

        listed = client.get("/api/v1/documents")
        assert listed.status_code == 200, listed.text
        published_document = next(
            item for item in listed.json()["items"]
            if item["document_id"] == retry_job["document_id"]
        )
        assert published_document["content_checksum"] == expected_checksum


@pytest.mark.parametrize("case", ["empty", "duplicate", "extra_field", "wrong_mime"])
def test_retry_rejects_invalid_multipart_before_ingestion(transport_client, case):
    client, service = transport_client
    files = [("file", ("source.pdf", b"%PDF-1.4\n\xff", "application/pdf"))]
    data = None
    expected = 400
    if case == "empty":
        files = [("file", ("source.pdf", b"", "application/pdf"))]
    elif case == "duplicate":
        files = files + files
    elif case == "extra_field":
        data = {"collection_id": "other-tenant-collection"}
    elif case == "wrong_mime":
        files = [("file", ("source.pdf", b"%PDF-1.4", "image/png"))]
        expected = 415
    response = client.post("/api/v1/ingestion/jobs/original/retry", files=files, data=data)
    assert response.status_code == expected, response.text
    assert service.calls == []


def test_invisible_retry_does_not_read_source(transport_client, monkeypatch):
    client, service = transport_client
    service.job["tenant_id"] = "another-tenant"

    async def forbidden_parse(*args, **kwargs):
        raise AssertionError("An invisible job must be denied before parsing")

    monkeypatch.setattr("starlette.requests.Request.form", forbidden_parse)
    response = client.post("/api/v1/ingestion/jobs/original/retry", files={"file": ("source.txt", b"source")})
    assert response.status_code == 404
    assert service.calls == []


@pytest.mark.parametrize("path", ["/api/v1/documents/upload", "/api/v1/ingestion/jobs/original/retry"])
def test_rejected_multipart_closes_every_parsed_file(transport_client, monkeypatch, path):
    client, service = transport_client
    opened = []
    original_init = UploadFile.__init__

    def capture(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        opened.append(self.file)

    monkeypatch.setattr(UploadFile, "__init__", capture)
    response = client.post(path, files=[
        ("unexpected", ("extra.pdf", b"%PDF-1.4\xff", "application/pdf")),
    ], data={"collection_id": "rag_phase0"} if path.endswith("upload") else None)
    assert response.status_code == 400
    assert opened
    assert all(file.closed for file in opened)
    assert service.calls == []


def test_retry_schema_advertises_binary_and_legacy_transports(transport_client):
    client, _ = transport_client
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/ingestion/jobs/{job_id}/retry"]["post"]
    content = operation["requestBody"]["content"]
    assert content["multipart/form-data"]["schema"]["properties"]["file"]["format"] == "binary"
    assert content["application/json"]["schema"]["required"] == ["filename", "content"]
