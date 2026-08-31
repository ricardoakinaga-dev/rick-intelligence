"""
Integrity Service — corpus audit and repair.

Provides:
- audit_corpus_integrity(): full workspace integrity check
- repair_document(): per-document repair from disk

Does not modify Qdrant or disk unless repair is explicitly called.
"""
from __future__ import annotations

import math
from typing import Optional
from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel

from core.config import DOCUMENTS_DIR, QDRANT_COLLECTION, EMBEDDING_DIM


# ─── Pydantic models ──────────────────────────────────────────────────────────


class IntegrityIssue(BaseModel):
    """A single integrity issue found in a document."""
    issue_type: str
    severity: str
    detail: str


class DocumentIntegrityResult(BaseModel):
    """Integrity result for a single document."""
    document_id: str
    chunk_count_registry: int
    chunk_count_qdrant: int | None = None
    chunking_strategy: str
    status: str  # "ok" | "issues" | "missing_from_qdrant"
    issues: list[IntegrityIssue] = []
    repair_action: Optional[str] = None


class CorpusIntegrityReport(BaseModel):
    """Full workspace integrity audit result."""
    workspace_id: str
    total_documents: int
    total_with_issues: int
    total_ok: int
    by_issue_type: dict[str, int]
    documents: list[DocumentIntegrityResult]
    recommendations: list[str]
    generated_at: str


class RepairResult(BaseModel):
    """Result of a repair operation on a single document."""
    document_id: str
    workspace_id: str
    success: bool
    chunks_reindexed: int = 0
    embeddings_valid: bool = False
    qdrant_restored: bool = False
    message: str


class QdrantIndexDriftSummary(BaseModel):
    workspace_id: str
    total_points: int = 0
    canonical_points: int = 0
    noncanonical_points: int = 0
    noncanonical_documents: int = 0
    noncanonical_document_ids: list[str] = []
    generated_at: str


class QdrantPruneResult(BaseModel):
    workspace_id: str
    deleted_points: int = 0
    deleted_documents: int = 0
    deleted_document_ids: list[str] = []
    canonical_points_remaining: int = 0
    total_points_remaining: int = 0
    generated_at: str


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _embedding_is_valid(emb: object) -> bool:
    """Return True if emb is a list of EMBEDDING_DIM finite floats."""
    if not isinstance(emb, list):
        return False
    if len(emb) != EMBEDDING_DIM:
        return False
    for x in emb:
        if not isinstance(x, (int, float)):
            return False
        if not math.isfinite(x):
            return False
    return True


def _scroll_qdrant_by_document(
    client, document_id: str, workspace_id: str, with_vectors: bool = False
) -> list[dict]:
    """
    Scroll all Qdrant points for a given document_id.

    Uses offset-based pagination. Returns list of point records (dict-like).
    """
    all_points = []
    offset = None
    while True:
        result, offset = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter={
                "must": [
                    {
                        "key": "document_id",
                        "match": {"value": document_id}
                    },
                    {
                        "key": "workspace_id",
                        "match": {"value": workspace_id}
                    }
                ]
            },
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=with_vectors,
        )
        all_points.extend(result)
        if offset is None:
            break
    return all_points


def _scroll_workspace_points(client, workspace_id: str, with_vectors: bool = False) -> list[dict]:
    """Return all Qdrant points for a workspace."""
    all_points = []
    offset = None
    while True:
        result, offset = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter={
                "must": [
                    {
                        "key": "workspace_id",
                        "match": {"value": workspace_id}
                    }
                ]
            },
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=with_vectors,
        )
        all_points.extend(result)
        if offset is None:
            break
    return all_points


def summarize_workspace_index_drift(workspace_id: str = "default") -> QdrantIndexDriftSummary:
    """Compare workspace points in Qdrant against the canonical on-disk registry."""
    from services.document_registry import get_document_registry
    from services.vector_service import get_client

    registry = get_document_registry(workspace_id)
    canonical_ids = set(registry.keys())
    client = get_client()
    points = _scroll_workspace_points(client, workspace_id, with_vectors=False)

    noncanonical_document_ids = sorted(
        {
            (point.payload or {}).get("document_id")
            for point in points
            if (point.payload or {}).get("document_id")
            and (point.payload or {}).get("document_id") not in canonical_ids
        }
    )
    noncanonical_points = sum(
        1
        for point in points
        if (point.payload or {}).get("document_id")
        and (point.payload or {}).get("document_id") not in canonical_ids
    )

    return QdrantIndexDriftSummary(
        workspace_id=workspace_id,
        total_points=len(points),
        canonical_points=len(points) - noncanonical_points,
        noncanonical_points=noncanonical_points,
        noncanonical_documents=len(noncanonical_document_ids),
        noncanonical_document_ids=noncanonical_document_ids,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def prune_workspace_index_to_registry(workspace_id: str = "default") -> QdrantPruneResult:
    """Delete Qdrant points from a workspace that do not belong to the canonical registry."""
    from qdrant_client.models import PointIdsList
    from services.vector_service import get_client

    client = get_client()
    drift = summarize_workspace_index_drift(workspace_id)
    if drift.noncanonical_points == 0:
        return QdrantPruneResult(
            workspace_id=workspace_id,
            deleted_points=0,
            deleted_documents=0,
            deleted_document_ids=[],
            canonical_points_remaining=drift.canonical_points,
            total_points_remaining=drift.total_points,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    points = _scroll_workspace_points(client, workspace_id, with_vectors=False)
    point_ids = [
        point.id
        for point in points
        if (point.payload or {}).get("document_id") in set(drift.noncanonical_document_ids)
    ]

    if point_ids:
        client.delete(
            collection_name=QDRANT_COLLECTION,
            points_selector=PointIdsList(points=point_ids),
            wait=True,
        )

    remaining = summarize_workspace_index_drift(workspace_id)
    return QdrantPruneResult(
        workspace_id=workspace_id,
        deleted_points=len(point_ids),
        deleted_documents=len(drift.noncanonical_document_ids),
        deleted_document_ids=drift.noncanonical_document_ids,
        canonical_points_remaining=remaining.canonical_points,
        total_points_remaining=remaining.total_points,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ─── Core audit ────────────────────────────────────────────────────────────────


def audit_corpus_integrity(
    workspace_id: str = "default",
    check_embeddings: bool = False,
) -> CorpusIntegrityReport:
    """
    Audit the integrity of a workspace's corpus.

    Checks:
    - Document present in registry but missing or count-mismatched in Qdrant
    - Orphan points in Qdrant (no matching registry document)
    - Invalid embeddings (optional, requires reading vectors — expensive for large corpora)

    Returns a structured CorpusIntegrityReport with per-document results and
    overall recommendations.

    Parameters:
        workspace_id: workspace to audit
        check_embeddings: if True, reads and validates embedding vectors from Qdrant
                          (expensive for large corpora; embeds are not stored in chunks file)
    """
    from services.document_registry import get_document_registry
    from services.vector_service import get_client, QDRANT_COLLECTION

    registry = get_document_registry(workspace_id)
    document_ids_in_registry = set(registry.keys())

    try:
        client = get_client()
    except Exception as e:
        return CorpusIntegrityReport(
            workspace_id=workspace_id,
            total_documents=len(registry),
            total_with_issues=len(registry),
            total_ok=0,
            by_issue_type={"qdrant_unavailable": len(registry)},
            documents=[],
            recommendations=[f"Qdrant unavailable: {e}"],
            generated_at="",
        )

    # Count Qdrant points per document via scroll + groupby
    # (count() with filter requires exact; scroll gives us per-doc detail)
    qdrant_points_by_doc: dict[str, list[dict]] = defaultdict(list)
    offset = None
    try:
        while True:
            result, offset = client.scroll(
                collection_name=QDRANT_COLLECTION,
                scroll_filter={
                    "must": [
                        {"key": "workspace_id", "match": {"value": workspace_id}}
                    ]
                },
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=check_embeddings,
            )
            for point in result:
                payload = point.payload or {}
                doc_id = payload.get("document_id")
                if doc_id:
                    qdrant_points_by_doc[doc_id].append(point)
            if offset is None:
                break
    except Exception:
        pass

    qdrant_doc_ids = set(qdrant_points_by_doc.keys())
    orphan_doc_ids = qdrant_doc_ids - document_ids_in_registry

    by_issue_type: dict[str, int] = defaultdict(int)
    documents: list[DocumentIntegrityResult] = []
    recommendations: list[str] = []

    # ── Check registry documents ────────────────────────────────────────────
    for doc_id, meta in sorted(registry.items()):
        reg_chunk_count = meta.get("chunk_count", 0)
        reg_strategy = meta.get("chunking_strategy", "recursive")
        qdrant_points = qdrant_points_by_doc.get(doc_id, [])
        qdrant_count = len(qdrant_points)

        issues: list[IntegrityIssue] = []
        status = "ok"

        if not qdrant_points:
            # Document has chunks on disk but zero points in Qdrant
            issues.append(IntegrityIssue(
                issue_type="missing_from_qdrant",
                severity="critical",
                detail=f"Document has {reg_chunk_count} chunks on disk but 0 points indexed in Qdrant",
            ))
            by_issue_type["missing_from_qdrant"] += 1
            status = "missing_from_qdrant"
        elif qdrant_count != reg_chunk_count:
            issues.append(IntegrityIssue(
                issue_type="count_mismatch",
                severity="high",
                detail=f"Registry says {reg_chunk_count} chunks, Qdrant has {qdrant_count} points",
            ))
            by_issue_type["count_mismatch"] += 1
            status = "issues"

        # Check embedding validity if requested
        embedding_issues = 0
        no_dense_issues = 0
        if check_embeddings and qdrant_points:
            for point in qdrant_points:
                vec = point.vector
                if not (vec and "dense" in vec):
                    no_dense_issues += 1
                elif not _embedding_is_valid(vec["dense"]):
                    embedding_issues += 1
            if no_dense_issues > 0:
                issues.append(IntegrityIssue(
                    issue_type="invalid_embedding",
                    severity="high",
                    detail=f"{no_dense_issues}/{qdrant_count} chunks missing dense vector in Qdrant",
                ))
                by_issue_type["invalid_embedding"] += 1
                status = "issues"
            elif embedding_issues > 0:
                issues.append(IntegrityIssue(
                    issue_type="invalid_embedding",
                    severity="high",
                    detail=f"{embedding_issues}/{qdrant_count} chunks have invalid/corrupt embeddings in Qdrant",
                ))
                by_issue_type["invalid_embedding"] += 1
                status = "issues"

        # Check for duplicate chunk_ids within this document
        chunk_ids_seen: set[str] = set()
        dup_chunk_ids: list[str] = []
        for point in qdrant_points:
            cid = (point.payload or {}).get("chunk_id", "")
            if cid in chunk_ids_seen:
                dup_chunk_ids.append(cid)
            chunk_ids_seen.add(cid)
        if dup_chunk_ids:
            issues.append(IntegrityIssue(
                issue_type="duplicate_chunk_id",
                severity="high",
                detail=f"Duplicate chunk_ids in Qdrant: {dup_chunk_ids[:5]}",
            ))
            by_issue_type["duplicate_chunk_id"] += 1
            status = "issues"

        # Strategy mismatch: check all points for mixed strategies within the document
        if qdrant_points:
            strategies_in_doc: set[str] = set()
            for pt in qdrant_points:
                strat = (pt.payload or {}).get("strategy", "recursive")
                strategies_in_doc.add(strat)
            if len(strategies_in_doc) > 1:
                issues.append(IntegrityIssue(
                    issue_type="strategy_mismatch",
                    severity="medium",
                    detail=f"Multiple strategies in Qdrant for this document: {sorted(strategies_in_doc)}",
                ))
                by_issue_type["strategy_mismatch"] += 1
                status = "issues"
            elif len(strategies_in_doc) == 1:
                qdrant_strategy = next(iter(strategies_in_doc))
                if qdrant_strategy != reg_strategy:
                    issues.append(IntegrityIssue(
                        issue_type="strategy_mismatch",
                        severity="medium",
                        detail=f"Registry strategy={reg_strategy}, Qdrant strategy={qdrant_strategy}",
                    ))
                    by_issue_type["strategy_mismatch"] += 1
                    status = "issues"

        # Determine repair action
        repair_action = None
        if status == "missing_from_qdrant":
            repair_action = f"reindex_document('{doc_id}', '{workspace_id}', chunking_strategy='{reg_strategy}')"
        elif issues:
            # Has issues that might be fixed by reindex
            repair_action = f"reindex_document('{doc_id}', '{workspace_id}', chunking_strategy='{reg_strategy}')"

        documents.append(DocumentIntegrityResult(
            document_id=doc_id,
            chunk_count_registry=reg_chunk_count,
            chunk_count_qdrant=qdrant_count if qdrant_points else None,
            chunking_strategy=reg_strategy,
            status=status,
            issues=issues,
            repair_action=repair_action,
        ))

    # ── Orphan documents in Qdrant (no registry entry) ───────────────────
    for orphan_doc_id in sorted(orphan_doc_ids):
        points = qdrant_points_by_doc[orphan_doc_id]
        count = len(points)
        strategy = (points[0].payload or {}).get("strategy", "unknown") if points else "unknown"
        issues = [IntegrityIssue(
            issue_type="orphan_in_qdrant",
            severity="medium",
            detail=f"{count} points in Qdrant but no entry in document registry",
        )]
        by_issue_type["orphan_in_qdrant"] += 1
        documents.append(DocumentIntegrityResult(
            document_id=orphan_doc_id,
            chunk_count_registry=0,
            chunk_count_qdrant=count,
            chunking_strategy=strategy,
            status="issues",
            issues=issues,
            repair_action=f"delete_document_chunks('{orphan_doc_id}')  # orphan in Qdrant, no registry entry",
        ))

    # ── Build recommendations ───────────────────────────────────────────────
    total_with_issues = sum(1 for d in documents if d.status != "ok")
    total_ok = len(documents) - total_with_issues

    if by_issue_type.get("missing_from_qdrant", 0) > 0:
        recommendations.append(
            f"{by_issue_type['missing_from_qdrant']} document(s) missing from Qdrant — "
            "use repair_document() or reindex_document() to restore"
        )
    if by_issue_type.get("orphan_in_qdrant", 0) > 0:
        recommendations.append(
            f"{by_issue_type['orphan_in_qdrant']} orphan point group(s) in Qdrant with no registry entry — "
            "consider delete_document_chunks() to clean up"
        )
    if by_issue_type.get("count_mismatch", 0) > 0:
        recommendations.append(
            f"{by_issue_type['count_mismatch']} document(s) with chunk_count mismatch — "
            "run repair_document() to re-sync disk and Qdrant"
        )
    if by_issue_type.get("invalid_embedding", 0) > 0:
        recommendations.append(
            f"{by_issue_type['invalid_embedding']} document(s) with invalid embeddings — "
            "run repair_document() with check_embeddings=True to regenerate from disk"
        )
    if by_issue_type.get("duplicate_chunk_id", 0) > 0:
        recommendations.append(
            f"{by_issue_type['duplicate_chunk_id']} document(s) with duplicate chunk_ids in Qdrant — "
            "reindex_document() will overwrite with correct IDs"
        )
    if not recommendations:
        recommendations.append("Corpus integrity is good. No issues found.")

    from datetime import datetime, timezone
    return CorpusIntegrityReport(
        workspace_id=workspace_id,
        total_documents=len(documents),
        total_with_issues=total_with_issues,
        total_ok=total_ok,
        by_issue_type=dict(by_issue_type),
        documents=documents,
        recommendations=recommendations,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def repair_document(
    document_id: str,
    workspace_id: str = "default",
) -> RepairResult:
    """
    Repair a single document by re-reading its chunks from disk and re-indexing in Qdrant.

    Uses the current chunking strategy from the registry (or 'recursive' if unknown).
    After repair, Qdrant and disk should be consistent for this document.

    Returns RepairResult with details of what was done.

    If the document has no raw JSON on disk, returns RepairResult with success=False.
    """
    from services.document_registry import get_document_metadata
    from services.ingestion_service import reindex_document
    from services.vector_service import get_client, QDRANT_COLLECTION
    from core.config import DOCUMENTS_DIR
    import json, math

    doc_dir = DOCUMENTS_DIR / workspace_id
    raw_path = doc_dir / f"{document_id}_raw.json"
    chunks_path = doc_dir / f"{document_id}_chunks.json"

    if not raw_path.exists():
        return RepairResult(
            document_id=document_id,
            workspace_id=workspace_id,
            success=False,
            message=f"Raw JSON not found at {raw_path}",
        )

    # Read current chunks from disk
    if not chunks_path.exists():
        return RepairResult(
            document_id=document_id,
            workspace_id=workspace_id,
            success=False,
            message=f"Chunks file not found at {chunks_path}",
        )

    try:
        with open(chunks_path, encoding="utf-8") as f:
            disk_chunks = json.load(f)
    except Exception as e:
        return RepairResult(
            document_id=document_id,
            workspace_id=workspace_id,
            success=False,
            message=f"Failed to read chunks file: {e}",
        )

    if not disk_chunks:
        return RepairResult(
            document_id=document_id,
            workspace_id=workspace_id,
            success=False,
            message="Chunks file is empty",
        )

    # Detect strategy from disk chunks
    strategy = disk_chunks[0].get("strategy", "recursive") if disk_chunks else "recursive"

    # Re-index via reindex_document with pre-loaded chunks
    try:
        chunk_count, embedding_status, latency_ms = reindex_document(
            document_id=document_id,
            workspace_id=workspace_id,
            chunking_strategy=strategy,
            chunks=disk_chunks,
        )
    except Exception as e:
        return RepairResult(
            document_id=document_id,
            workspace_id=workspace_id,
            success=False,
            message=f"reindex_document failed: {e}",
        )

    # Verify Qdrant now has the correct count
    try:
        client = get_client()
        points, _ = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter={
                "must": [
                    {"key": "document_id", "match": {"value": document_id}},
                    {"key": "workspace_id", "match": {"value": workspace_id}},
                ]
            },
            limit=1,
            with_payload=False,
        )
        # Count with filter
        count_result = client.count(
            collection_name=QDRANT_COLLECTION,
            count_filter={
                "must": [
                    {"key": "document_id", "match": {"value": document_id}},
                    {"key": "workspace_id", "match": {"value": workspace_id}},
                ]
            },
            exact=True,
        )
        qdrant_count = count_result.count
        qdrant_restored = (qdrant_count == len(disk_chunks))
    except Exception:
        qdrant_restored = False

    return RepairResult(
        document_id=document_id,
        workspace_id=workspace_id,
        success=qdrant_restored,
        chunks_reindexed=chunk_count,
        embeddings_valid=(embedding_status != "degraded_zero_fallback"),
        qdrant_restored=qdrant_restored,
        message=f"Repaired. chunks={chunk_count}, embedding_status={embedding_status}, qdrant_count={qdrant_count if qdrant_restored else 'unknown'}",
    )
