"""
Operational upload retention helpers.

Keeps retention/cleanup rules for non-canonical uploaded documents in one place,
so ingestion, admin runtime, and external schedulers all use the same policy.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from core.config import DOCUMENTS_DIR
from services.admin_service import get_tenant_by_workspace
from services.document_registry import list_workspace_items
from services.vector_service import delete_document_chunks


class OperationalRetentionSummary(BaseModel):
    workspace_id: str
    retention_mode: str = "keep_latest"
    retention_hours: int = 24
    operational_documents: int = 0
    operational_chunks: int = 0
    eligible_documents: int = 0
    eligible_chunks: int = 0
    eligible_document_ids: list[str] = Field(default_factory=list)
    oldest_eligible_created_at: str | None = None
    generated_at: str


class OperationalCleanupResult(BaseModel):
    workspace_id: str
    retention_mode: str = "keep_latest"
    retention_hours: int = 24
    deleted_documents: int = 0
    deleted_chunks: int = 0
    deleted_document_ids: list[str] = Field(default_factory=list)
    remaining_operational_documents: int = 0
    remaining_operational_chunks: int = 0
    generated_at: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def get_operational_retention_policy(workspace_id: str) -> tuple[str, int]:
    tenant = get_tenant_by_workspace(workspace_id) or {}
    mode = tenant.get("operational_retention_mode", "keep_latest")
    if mode not in {"keep_latest", "keep_all"}:
        mode = "keep_latest"
    try:
        hours = int(tenant.get("operational_retention_hours", 24) or 24)
    except Exception:
        hours = 24
    return mode, max(1, hours)


def summarize_operational_retention(workspace_id: str = "default") -> OperationalRetentionSummary:
    """Summarize operational uploads and which ones are past the tenant TTL."""
    mode, hours = get_operational_retention_policy(workspace_id)
    cutoff = _utc_now() - timedelta(hours=hours)
    items = list_workspace_items(workspace_id, catalog_scope="operational")

    eligible_items = []
    for item in items:
        created_at_dt = _parse_timestamp(item.get("created_at"))
        if created_at_dt and created_at_dt < cutoff:
            eligible_items.append(item)

    oldest = min(
        (item.get("created_at") for item in eligible_items if item.get("created_at")),
        default=None,
    )

    return OperationalRetentionSummary(
        workspace_id=workspace_id,
        retention_mode=mode,
        retention_hours=hours,
        operational_documents=len(items),
        operational_chunks=sum(item.get("chunk_count", 0) for item in items),
        eligible_documents=len(eligible_items),
        eligible_chunks=sum(item.get("chunk_count", 0) for item in eligible_items),
        eligible_document_ids=[item["document_id"] for item in eligible_items],
        oldest_eligible_created_at=oldest,
        generated_at=_utc_now().isoformat().replace("+00:00", "Z"),
    )


def cleanup_operational_uploads(workspace_id: str = "default") -> OperationalCleanupResult:
    """Delete operational uploads that are older than the tenant TTL."""
    summary = summarize_operational_retention(workspace_id)
    doc_dir = DOCUMENTS_DIR / workspace_id

    deleted_documents = 0
    deleted_chunks = 0
    deleted_ids: list[str] = []
    eligible_lookup = set(summary.eligible_document_ids)
    for item in list_workspace_items(workspace_id, catalog_scope="operational"):
        document_id = item["document_id"]
        if document_id not in eligible_lookup:
            continue
        raw_path = doc_dir / f"{document_id}_raw.json"
        chunks_path = doc_dir / f"{document_id}_chunks.json"
        try:
            delete_document_chunks(document_id)
        except Exception:
            pass
        try:
            raw_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            chunks_path.unlink(missing_ok=True)
        except Exception:
            pass
        deleted_documents += 1
        deleted_chunks += int(item.get("chunk_count", 0) or 0)
        deleted_ids.append(document_id)

    remaining = list_workspace_items(workspace_id, catalog_scope="operational")
    return OperationalCleanupResult(
        workspace_id=workspace_id,
        retention_mode=summary.retention_mode,
        retention_hours=summary.retention_hours,
        deleted_documents=deleted_documents,
        deleted_chunks=deleted_chunks,
        deleted_document_ids=deleted_ids,
        remaining_operational_documents=len(remaining),
        remaining_operational_chunks=sum(item.get("chunk_count", 0) for item in remaining),
        generated_at=_utc_now().isoformat().replace("+00:00", "Z"),
    )
