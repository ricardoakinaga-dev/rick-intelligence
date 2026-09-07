from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "knowledge" / "src"))

from rick_ingestion import (  # noqa: E402
    ALLOWED_OPERATIONS,
    ALLOWED_SOURCE_TYPES,
    InvalidChecksumError,
    InvalidUploadFieldError,
    InvalidUploadSizeError,
    MAX_UPLOAD_BYTES,
    UnsupportedOperationError,
    UnsupportedSourceTypeError,
    UploadJobEnvelope,
)


VALID = {
    "tenant_id": "tenant-a",
    "workspace_id": "workspace-a",
    "collection_id": "collection-a",
    "job_id": "job-123",
    "idempotency_key": "idem-123",
    "source_key": "upload-123.txt",
    "checksum": "sha256:" + "a" * 64,
    "size_bytes": 42,
    "source_type": "txt",
    "request_id": "request-123",
    "correlation_id": "correlation-123",
}


def make_envelope(**overrides: object) -> UploadJobEnvelope:
    values = {**VALID, **overrides}
    return UploadJobEnvelope(**values)  # type: ignore[arg-type]


def test_valid_envelope_payload_scope_and_diagnostics() -> None:
    envelope = make_envelope()

    assert envelope.operation == "ingest"
    assert envelope.payload() == {
        "operation": "ingest",
        "source_key": "upload-123.txt",
        "request_id": "request-123",
        "correlation_id": "correlation-123",
        "collection_id": "collection-a",
        "workspace_id": "workspace-a",
        "tenant_id": "tenant-a",
    }
    scope = envelope.scope()
    assert (scope.tenant_id, scope.workspace_id, scope.source_id) == (
        "tenant-a",
        "workspace-a",
        "upload-123.txt",
    )
    assert envelope.as_dict()["checksum"] == VALID["checksum"]
    assert envelope.as_dict()["size_bytes"] == 42
    assert envelope.to_dict() == envelope.as_dict()


@pytest.mark.parametrize(
    "field",
    (
        "tenant_id",
        "workspace_id",
        "collection_id",
        "job_id",
        "idempotency_key",
        "source_key",
        "request_id",
        "correlation_id",
    ),
)
def test_required_identifier_fields_are_non_empty_safe_tokens(field: str) -> None:
    with pytest.raises(InvalidUploadFieldError, match=field):
        make_envelope(**{field: ""})


@pytest.mark.parametrize("value", ["a/b", "a\\b", "a b", "a\nb", "é", ".", "secret-token"])
def test_identifiers_reject_paths_whitespace_control_unicode_and_secrets(value: str) -> None:
    with pytest.raises(InvalidUploadFieldError):
        make_envelope(source_key=value)


def test_required_constructor_arguments_are_mandatory() -> None:
    with pytest.raises(TypeError):
        UploadJobEnvelope()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "checksum",
    ["", "sha256:" + "a" * 63, "sha256:" + "A" * 64, "md5:" + "a" * 64],
)
def test_checksum_is_exact_lowercase_sha256(checksum: str) -> None:
    with pytest.raises(InvalidChecksumError):
        make_envelope(checksum=checksum)


@pytest.mark.parametrize("size", [-1, MAX_UPLOAD_BYTES + 1, True, 1.5])
def test_size_is_bounded_integer(size: object) -> None:
    with pytest.raises(InvalidUploadSizeError):
        make_envelope(size_bytes=size)


def test_size_bounds_are_inclusive() -> None:
    assert make_envelope(size_bytes=0).size_bytes == 0
    assert make_envelope(size_bytes=MAX_UPLOAD_BYTES).size_bytes == MAX_UPLOAD_BYTES


@pytest.mark.parametrize("source_type", ["", "HTML", "exe", "pdf/"])
def test_source_type_allowlist(source_type: str) -> None:
    with pytest.raises(UnsupportedSourceTypeError):
        make_envelope(source_type=source_type)
    assert all(make_envelope(source_type=value).source_type == value for value in ALLOWED_SOURCE_TYPES)


@pytest.mark.parametrize("operation", ["", "archive", "INGEST", "ingest/"])
def test_operation_allowlist(operation: str) -> None:
    with pytest.raises(UnsupportedOperationError):
        make_envelope(operation=operation)
    assert all(make_envelope(operation=value).operation == value for value in ALLOWED_OPERATIONS)


def test_payload_excludes_content_secrets_checksum_size_and_path_metadata() -> None:
    envelope = make_envelope()
    payload = envelope.payload()
    forbidden_keys = {
        "checksum",
        "size_bytes",
        "source_type",
        "job_id",
        "idempotency_key",
        "filename",
        "path",
        "url",
        "token",
        "content",
        "bytes",
    }

    assert not forbidden_keys.intersection(payload)
    assert all(not isinstance(value, (bytes, bytearray, memoryview)) for value in payload.values())
    assert "https://" not in repr(payload)
    assert "Bearer" not in repr(payload)
    assert envelope.as_dict()["checksum"] not in payload.values()


def test_envelope_is_immutable_and_returns_fresh_metadata() -> None:
    envelope = make_envelope()

    with pytest.raises(FrozenInstanceError):
        envelope.tenant_id = "other"  # type: ignore[misc]

    payload = envelope.payload()
    payload["tenant_id"] = "other"
    assert envelope.tenant_id == "tenant-a"
