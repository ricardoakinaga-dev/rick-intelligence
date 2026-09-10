"""Focused local job-journal and restart-recovery coverage."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import threading
import time

import pytest

from services.ingestion_service import IngestionApplicationError, IngestionApplicationService
from services.job_journal import JobJournal, JobJournalError


def _job(job_id: str, *, status: str = "queued", document_id: str | None = None) -> dict:
    now = time.time()
    return {
        "job_id": job_id,
        "document_id": document_id,
        "status": status,
        "stage": status,
        "progress": 0.0 if status != "published" else 1.0,
        "attempt": 1,
        "error_code": None,
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "collection_id": "collection-a",
        "created_at": now,
        "started_at": None,
        "finished_at": now if status in {"published", "failed", "cancelled"} else None,
        "cancel_requested": False,
        "metadata": {"execution": "process-local", "unsafe": "discard me"},
    }


class _FakeIngestion:
    def __init__(self, *, block: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.reindex_calls: list[tuple[str, Path, dict]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = block

    def ingest(self, path: Path, **kwargs):
        self.calls.append((str(path), dict(kwargs)))
        self.started.set()
        if self.block:
            self.release.wait(2)
        job_id = kwargs.get("job_id", f"new-{len(self.calls)}")
        now = time.time()
        if callable(kwargs.get("cancel_check")) and kwargs["cancel_check"]():
            return {
                **_job(job_id, status="cancelled"),
                "cancel_requested": True,
                "finished_at": now,
            }
        return {
            "job_id": job_id,
            "document_id": f"document-{job_id}",
            "status": "published",
            "stage": "published",
            "progress": 1.0,
            "attempt": 1,
            "error_code": None,
            "tenant_id": kwargs.get("tenant_id", "tenant-a"),
            "workspace_id": kwargs.get("workspace_id", "workspace-a"),
            "collection_id": kwargs.get("collection_id", "collection-a"),
            "created_at": now,
            "started_at": now,
            "finished_at": now,
            "cancel_requested": False,
            "metadata": {},
        }

    def reindex(self, document_id: str, path: Path, **kwargs):
        self.reindex_calls.append((document_id, Path(path), dict(kwargs)))
        now = time.time()
        return {
            **_job("reindex-job", status="published", document_id=document_id),
            "stage": "published",
            "progress": 1.0,
            "finished_at": now,
        }

    def cancel(self, _job_id: str) -> bool:
        return True


class _ForeignResultIngestion(_FakeIngestion):
    def reindex(self, document_id: str, path: Path, **kwargs):
        self.reindex_calls.append((document_id, Path(path), dict(kwargs)))
        return {
            **_job("foreign-result", status="published", document_id="foreign-document"),
            "tenant_id": "tenant-b",
            "workspace_id": "workspace-b",
            "collection_id": "collection-b",
            "finished_at": time.time(),
        }


def test_job_journal_reopens_with_wal_private_files_and_atomic_upsert(tmp_path: Path) -> None:
    journal_path = tmp_path / "private" / "jobs.sqlite"
    source = tmp_path / "staging" / "source.txt"
    source.parent.mkdir()
    source.write_text("source", encoding="utf-8")

    journal = JobJournal(journal_path, max_rows=8)
    journal.upsert(_job("job-1"), source_path=source, display_filename="source.txt")
    final = _job("job-1", status="published", document_id="document-1")
    final["progress"] = 1.0
    journal.upsert(final, source_path=source, display_filename="source.txt")

    assert journal.get("job-1")["status"] == "published"
    assert journal.row_count() == 1
    with sqlite3.connect(journal_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    journal.close()

    assert os.stat(journal_path).st_mode & 0o777 == 0o600
    assert os.stat(journal_path.parent).st_mode & 0o777 == 0o700

    reopened = JobJournal(journal_path)
    record = reopened.get("job-1")
    assert record is not None
    assert record["status"] == "published"
    assert record["source_path"] == str(source)
    reopened.close()


def test_job_journal_rejects_oversized_or_nonfinite_persisted_json(tmp_path: Path) -> None:
    journal_path = tmp_path / "jobs.sqlite"
    journal = JobJournal(journal_path)
    journal.upsert(_job("corrupt-job"))
    journal.close()

    with sqlite3.connect(journal_path) as connection:
        oversized = '{"allowed_collection_ids":["collection-a"]}' + (" " * (32 * 1024))
        connection.execute(
            "UPDATE ingestion_jobs SET acl_json=? WHERE job_id=?",
            (oversized, "corrupt-job"),
        )
        connection.commit()

    reopened = JobJournal(journal_path)
    assert reopened.get("corrupt-job") is None
    reopened.close()

    with sqlite3.connect(journal_path) as connection:
        connection.execute(
            "UPDATE ingestion_jobs SET metadata_json=? WHERE job_id=?",
            ('{"execution":NaN}', "corrupt-job"),
        )
        connection.commit()

    reopened = JobJournal(journal_path)
    assert reopened.get("corrupt-job") is None
    reopened.close()


def test_journal_hardening_failure_rolls_back_before_commit(tmp_path: Path, monkeypatch) -> None:
    journal = JobJournal(tmp_path / "jobs.sqlite")

    def fail_hardening() -> None:
        raise JobJournalError("simulated filesystem hardening failure")

    monkeypatch.setattr(journal, "_harden_filesystem_permissions", fail_hardening)
    with pytest.raises(JobJournalError, match="hardening"):
        journal.upsert(_job("not-persisted"))
    assert journal.get("not-persisted") is None
    assert journal.row_count() == 0
    journal.close()


def test_reopen_restores_published_source_for_reindex(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    source = staging / "doc.txt"
    source.write_text("published source", encoding="utf-8")
    journal_path = tmp_path / "jobs.sqlite"

    with JobJournal(journal_path) as journal:
        journal.upsert(
            _job("published-job", status="published", document_id="document-1"),
            source_path=source,
            display_filename="doc.txt",
        )

    reopened = JobJournal(journal_path)
    ingestion = _FakeIngestion()
    service = IngestionApplicationService(
        ingestion,
        staging_root=staging,
        max_jobs=2,
        job_journal=reopened,
    )
    result = service.reindex(
        "document-1",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )

    assert result["status"] == "published"
    assert ingestion.reindex_calls
    assert ingestion.reindex_calls[0][1] == source.resolve()
    service.shutdown(wait=True)
    reopened.close()


def test_reindex_rejects_adapter_scope_drift_and_cleans_replacement_source(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    journal = JobJournal(tmp_path / "jobs.sqlite")
    ingestion = _ForeignResultIngestion()
    service = IngestionApplicationService(
        ingestion,
        staging_root=staging,
        job_journal=journal,
    )

    with pytest.raises(IngestionApplicationError, match="invalid job scope"):
        service.reindex(
            "document-a",
            collection_id="collection-a",
            workspace_id="workspace-a",
            tenant_id="tenant-a",
            source=b"replacement",
            filename="replacement.txt",
        )

    assert ingestion.reindex_calls
    assert list(staging.iterdir()) == []
    assert journal.row_count() == 0
    service.shutdown(wait=True)
    journal.close()


def test_recovery_submission_is_bounded_by_max_jobs(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    journal_path = tmp_path / "jobs.sqlite"
    journal = JobJournal(journal_path, max_rows=16)
    for index in range(5):
        source = staging / f"job-{index}.txt"
        source.write_text(f"source-{index}", encoding="utf-8")
        record = _job(f"job-{index}")
        record["created_at"] = float(index)
        journal.upsert(record, source_path=source, display_filename=source.name)

    ingestion = _FakeIngestion()
    service = IngestionApplicationService(
        ingestion,
        staging_root=staging,
        max_jobs=2,
        job_journal=journal,
    )
    deadline = time.time() + 2
    while time.time() < deadline and len(ingestion.calls) < 2:
        time.sleep(0.01)

    assert len(ingestion.calls) == 2
    assert service._async_pending <= 2
    service.shutdown(wait=True)
    journal.close()


def test_placeholder_final_cancelled_and_retry_state_are_journaled(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    journal = JobJournal(tmp_path / "jobs.sqlite")
    ingestion = _FakeIngestion(block=True)
    service = IngestionApplicationService(
        ingestion,
        staging_root=staging,
        max_jobs=4,
        job_journal=journal,
    )

    submitted = service.submit_upload(
        b"queued source",
        filename="queued.txt",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )
    assert journal.get(submitted["job_id"])["status"] in {"queued", "validating"}
    assert ingestion.started.wait(1)
    cancelled = service.cancel(
        submitted["job_id"],
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        allowed_collection_ids=["collection-a"],
    )
    assert cancelled["status"] == "cancelled"
    assert journal.get(submitted["job_id"])["status"] == "cancelled"
    ingestion.release.set()
    service.shutdown(wait=True)
    journal.close()

    retry_journal = JobJournal(tmp_path / "retry.sqlite")
    failed = _job("failed-job", status="failed")
    failed["error_code"] = "storage_unavailable"
    retry_journal.upsert(failed)
    retry_service = IngestionApplicationService(
        _FakeIngestion(),
        staging_root=tmp_path / "retry-staging",
        job_journal=retry_journal,
    )
    retried = retry_service.retry(
        "failed-job",
        source=b"retry source",
        filename="retry.txt",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        allowed_collection_ids=["collection-a"],
    )
    assert retried["status"] == "published"
    original = retry_journal.get("failed-job")
    assert original["retry_count"] == 1
    assert original["acl_snapshot"]["allowed_collection_ids"] == ["collection-a"]
    retry_service.shutdown(wait=True)
    retry_journal.close()


def test_missing_recovery_source_is_failed_safely(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    journal = JobJournal(tmp_path / "jobs.sqlite")
    missing = staging / "gone.txt"
    journal.upsert(_job("missing-job"), source_path=missing, display_filename="gone.txt")

    service = IngestionApplicationService(
        _FakeIngestion(),
        staging_root=staging,
        job_journal=journal,
    )

    status = service.get_status(
        "missing-job",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        allowed_collection_ids=["collection-a"],
    )
    assert status is not None
    assert status["status"] == "failed"
    assert status["error_code"] == "recovery_required"
    assert status["recovery_required"] is True
    persisted = journal.get("missing-job")
    assert persisted["status"] == "failed"
    assert persisted["error_code"] == "recovery_required"
    assert persisted["source_path"] is None
    service.shutdown(wait=True)
    journal.close()


def test_recovery_rejects_incomplete_scope_without_default_fallback(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    source = staging / "unsafe.txt"
    source.write_text("must not resume", encoding="utf-8")
    journal_path = tmp_path / "jobs.sqlite"
    journal = JobJournal(journal_path)
    journal.upsert(_job("unsafe-job"), source_path=source, display_filename=source.name)
    journal.close()

    with sqlite3.connect(journal_path) as connection:
        connection.execute("UPDATE ingestion_jobs SET tenant_id = '' WHERE job_id = 'unsafe-job'")
        connection.commit()

    reopened = JobJournal(journal_path)
    ingestion = _FakeIngestion()
    service = IngestionApplicationService(
        ingestion,
        staging_root=staging,
        job_journal=reopened,
    )

    assert ingestion.calls == []
    assert not source.exists()
    persisted = reopened.get("unsafe-job")
    assert persisted["status"] == "failed"
    assert persisted["error_code"] == "recovery_required"
    assert persisted["tenant_id"] == ""
    assert persisted["source_path"] is None
    assert service.get_status(
        "unsafe-job",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        allowed_collection_ids=["collection-a"],
    ) is None
    service.shutdown(wait=True)
    reopened.close()


def test_failed_source_reference_survives_unlink_failure_and_retries_on_restart(
    tmp_path: Path, monkeypatch
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    source = staging / "failed.txt"
    source.write_text("private failed source", encoding="utf-8")
    journal_path = tmp_path / "jobs.sqlite"
    journal = JobJournal(journal_path)
    service = IngestionApplicationService(
        _FakeIngestion(),
        staging_root=staging,
        job_journal=journal,
    )
    failed = _job("failed-cleanup", status="failed")
    failed["error_code"] = "storage_unavailable"

    def fail_unlink(_path: Path, missing_ok: bool = False) -> None:
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    result = service._record_result(failed, source, display_filename=source.name)
    assert result["status"] == "failed"
    assert source.exists()
    assert service._job_paths["failed-cleanup"] == source
    assert journal.get("failed-cleanup")["source_path"] == str(source)
    service.shutdown(wait=True)
    journal.close()
    monkeypatch.undo()

    reopened = JobJournal(journal_path)
    recovered = IngestionApplicationService(
        _FakeIngestion(),
        staging_root=staging,
        job_journal=reopened,
    )
    assert not source.exists()
    assert recovered._job_paths.get("failed-cleanup") is None
    assert reopened.get("failed-cleanup")["source_path"] is None
    recovered.shutdown(wait=True)
    reopened.close()


def test_cleanup_lease_survives_both_journal_and_unlink_failure(tmp_path: Path, monkeypatch) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    source = staging / "double-failure.txt"
    source.write_text("private source requiring durable cleanup", encoding="utf-8")
    journal_path = tmp_path / "jobs.sqlite"
    journal = JobJournal(journal_path)
    service = IngestionApplicationService(
        _FakeIngestion(),
        staging_root=staging,
        job_journal=journal,
    )
    failed = _job("double-cleanup-failure", status="failed")
    failed["error_code"] = "storage_unavailable"

    def fail_unlink(_path: Path, missing_ok: bool = False) -> None:
        raise OSError("simulated unlink failure")

    def fail_journal(*_args, **_kwargs) -> None:
        raise JobJournalError("simulated journal failure")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    monkeypatch.setattr(journal, "upsert", fail_journal)

    result = service._record_result(failed, source, display_filename=source.name)

    assert result["status"] == "failed"
    assert source.exists()
    leases = list((staging / ".cleanup-leases").glob("lease-*.json"))
    assert len(leases) == 1
    assert leases[0].stat().st_mode & 0o777 == 0o600
    service.shutdown(wait=True)
    journal.close()
    monkeypatch.undo()

    reopened = JobJournal(journal_path)
    recovered = IngestionApplicationService(
        _FakeIngestion(),
        staging_root=staging,
        job_journal=reopened,
    )
    assert not source.exists()
    assert not leases[0].exists()
    assert not (staging / ".cleanup-leases").exists()
    recovered.shutdown(wait=True)
    reopened.close()


def test_cleanup_lease_json_fails_closed_for_oversized_or_nonfinite_markers(tmp_path: Path) -> None:
    for suffix, raw_payload in (
        (
            "oversized",
            '{"version":1,"job_id":"lease-oversized","source_path":"SOURCE",'
            '"tenant_id":"tenant-a","workspace_id":"workspace-a",'
            '"collection_id":"collection-a","padding":"' + ("x" * (8 * 1024)) + '"}',
        ),
        (
            "nonfinite",
            '{"version":1,"job_id":"lease-nonfinite","source_path":"SOURCE",'
            '"tenant_id":"tenant-a","workspace_id":"workspace-a",'
            '"collection_id":"collection-a","padding":NaN}',
        ),
    ):
        staging = tmp_path / suffix
        source = staging / "source.txt"
        source.parent.mkdir(parents=True)
        source.write_text("private source", encoding="utf-8")
        job_id = f"lease-{suffix}"
        lease_root = staging / ".cleanup-leases"
        lease_root.mkdir(mode=0o700)
        marker = lease_root / IngestionApplicationService._cleanup_lease_filename(job_id)
        marker.write_text(raw_payload.replace("SOURCE", str(source)), encoding="utf-8")

        service = IngestionApplicationService(_FakeIngestion(), staging_root=staging)

        assert source.exists()
        assert marker.exists()
        service.shutdown(wait=True)


def test_staging_failure_quarantines_unowned_source_until_restart_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    journal_path = tmp_path / "jobs.sqlite"
    journal = JobJournal(journal_path)
    service = IngestionApplicationService(
        _FakeIngestion(),
        staging_root=staging,
        max_bytes=3,
        max_staged_bytes=8,
        job_journal=journal,
    )

    def fail_unlink(_path: Path, missing_ok: bool = False) -> None:
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(IngestionApplicationError, match="exceeds size"):
        service._write_staged(
            b"oversized",
            suffix=".txt",
            cleanup_scope=("tenant-a", "workspace-a", "collection-a"),
        )
    cleanup_rows = [
        record for record in journal.list_jobs()
        if record["job_id"].startswith("cleanup-")
    ]
    assert len(cleanup_rows) == 1
    retained_source = Path(cleanup_rows[0]["source_path"])
    assert retained_source.exists()
    service.shutdown(wait=True)
    journal.close()
    monkeypatch.undo()

    reopened = JobJournal(journal_path)
    recovered = IngestionApplicationService(
        _FakeIngestion(),
        staging_root=staging,
        job_journal=reopened,
    )
    assert not retained_source.exists()
    assert reopened.get(cleanup_rows[0]["job_id"])["source_path"] is None
    recovered.shutdown(wait=True)
    reopened.close()


def test_job_journal_rejects_missing_scope_in_new_rows(tmp_path: Path) -> None:
    journal = JobJournal(tmp_path / "jobs.sqlite")
    incomplete = _job("incomplete-job")
    incomplete.pop("tenant_id")

    with pytest.raises(ValueError, match="tenant_id is required"):
        journal.upsert(incomplete)
    assert journal.row_count() == 0
    journal.close()


def test_acl_snapshot_is_whitelisted_and_no_journal_keeps_legacy_metadata(tmp_path: Path) -> None:
    journal = JobJournal(tmp_path / "jobs.sqlite")
    record = _job("acl-job")
    journal.upsert(
        record,
        acl_snapshot={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "collection_id": "collection-a",
            "allowed_collection_ids": ["collection-a", "collection-b", "collection-a"],
            "permissions": ["documents.read"],
            "secret": "must not persist",
        },
    )
    snapshot = journal.get("acl-job")["acl_snapshot"]
    assert snapshot == {
        "authorization_snapshot_version": 1,
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "collection_id": "collection-a",
        "allowed_collection_ids": ["collection-a", "collection-b"],
        "permissions": ["documents.read"],
    }
    assert "secret" not in snapshot
    journal.close()

    service = IngestionApplicationService(_FakeIngestion(), staging_root=tmp_path / "no-journal")
    result = service.upload(
        b"legacy compatibility",
        filename="compat.txt",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )
    assert result["metadata"] == {
        "execution": "process-local",
        "durability": "process-local",
        "restart_recovery": False,
        "storage": "private-temporary",
    }
    service.shutdown(wait=True)
