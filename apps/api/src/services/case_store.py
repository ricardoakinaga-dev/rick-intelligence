"""Local scoped store for human-authored clinical-case records.

The store is deliberately limited to record, human review, and human
feedback data.  Tenant, workspace, and owner are taken from the authenticated
session and never from an HTTP payload.  The SQLite adapter is local
durability plumbing; it is not a production clinical data-store claim.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from threading import RLock
import time
from typing import Any
import uuid

from rick_contracts.cases import (
    CASE_SCOPE_STATUS,
    AuthorizedAgentModel,
    CaseEvidence,
    CaseEvidenceInput,
    CaseFeedback,
    CaseHypothesis,
    CaseHypothesisInput,
    CaseRecord,
    CaseReview,
)


MAX_PAGE_SIZE = 100
MAX_OFFSET = 100_000


def _value(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _scope(session: object) -> tuple[str, str, str]:
    values = tuple(_value(session, name) for name in ("tenant_id", "workspace_id", "user_id"))
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("tenant, workspace, and user scope are required")
    return tuple(value.strip() for value in values)  # type: ignore[return-value]


def _page(limit: object, offset: object) -> tuple[int, int]:
    try:
        bounded_limit = min(MAX_PAGE_SIZE, max(1, int(limit)))
        bounded_offset = min(MAX_OFFSET, max(0, int(offset)))
    except (TypeError, ValueError, OverflowError):
        bounded_limit, bounded_offset = 50, 0
    return bounded_limit, bounded_offset


def _clean_id(value: object, name: str) -> str:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 128:
        raise ValueError(f"{name} is invalid")
    return candidate


def _clean_text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    candidate = value.strip()
    if not candidate or len(candidate) > maximum:
        raise ValueError(f"{name} is invalid")
    return candidate


def _clean_tags(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("tags are invalid")
    result: list[str] = []
    for raw in value[:16]:
        candidate = _clean_text(raw, "tag", 64)
        if candidate not in result:
            result.append(candidate)
    if len(value) > 16:
        raise ValueError("too many tags")
    return result


def _clean_summary(summary: object, record: object) -> str:
    candidate = summary if summary is not None else record
    return _clean_text(candidate, "summary", 20_000)


def _clean_record(record: object, summary: object) -> str:
    candidate = record if record is not None else summary
    return _clean_text(candidate, "record", 20_000)


def _clean_hypotheses(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > 32:
        raise ValueError("hypotheses are invalid")
    result: list[dict[str, Any]] = []
    for raw in value:
        item = raw if isinstance(raw, CaseHypothesisInput) else CaseHypothesisInput.model_validate(raw)
        result.append(
            CaseHypothesis.model_validate(
                {
                    "hypothesis_id": item.hypothesis_id or _new_id("hypothesis"),
                    "statement": item.statement,
                    "status": item.status,
                }
            ).model_dump(mode="python")
        )
    return result


def _clean_evidence(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > 64:
        raise ValueError("evidence is invalid")
    result: list[dict[str, Any]] = []
    for raw in value:
        item = raw if isinstance(raw, CaseEvidenceInput) else CaseEvidenceInput.model_validate(raw)
        result.append(
            CaseEvidence.model_validate(
                {
                    "evidence_id": item.evidence_id or _new_id("evidence"),
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "locator": item.locator,
                    "label": item.label,
                }
            ).model_dump(mode="python")
        )
    return result


def _catalog(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > 100:
        raise ValueError("agent model catalog is invalid")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in value:
        item = AuthorizedAgentModel.model_validate(raw)
        # Revoked entries may remain in deployment configuration for audit or
        # rollout history, but they must never be exposed as an authorized
        # runtime catalog option.
        if item.status != "authorized":
            continue
        key = (item.agent_id, item.model_id, item.catalog_version)
        if key in seen:
            continue
        seen.add(key)
        result.append(item.model_dump(mode="python"))
    return result


def _request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate[:128] or None


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


def _case_payload(
    *,
    case_id: str,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    title: str,
    summary: str,
    record: str,
    hypotheses: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    tags: list[str],
    status: str,
    created_by_user_id: str,
    created_at: float,
    updated_by_user_id: str,
    updated_at: float,
    last_request_id: str | None,
    review_count: int = 0,
    feedback_count: int = 0,
    last_review_at: float | None = None,
    last_feedback_at: float | None = None,
) -> dict[str, Any]:
    return CaseRecord.model_validate(
        {
            "case_id": case_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "title": title,
            "summary": summary,
            "record": record,
            "hypotheses": hypotheses,
            "evidence": evidence,
            "agent_model": None,
            "tags": tags,
            "status": status,
            "created_by_user_id": created_by_user_id,
            "created_at": created_at,
            "updated_by_user_id": updated_by_user_id,
            "updated_at": updated_at,
            "last_request_id": last_request_id,
            "review_count": review_count,
            "feedback_count": feedback_count,
            "last_review_at": last_review_at,
            "last_feedback_at": last_feedback_at,
            "clinical_scope_status": CASE_SCOPE_STATUS,
        }
    ).model_dump(mode="python")


def _review_payload(
    *,
    review_id: str,
    case_id: str,
    tenant_id: str,
    workspace_id: str,
    decision: str,
    review_note: str,
    reviewer_user_id: str,
    created_at: float,
    request_id: str | None,
) -> dict[str, Any]:
    return CaseReview.model_validate(
        {
            "review_id": review_id,
            "case_id": case_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "decision": decision,
            "review_note": review_note,
            "reviewer_user_id": reviewer_user_id,
            "created_at": created_at,
            "request_id": request_id,
        }
    ).model_dump(mode="python")


def _feedback_payload(
    *,
    feedback_id: str,
    case_id: str,
    tenant_id: str,
    workspace_id: str,
    kind: str,
    feedback_note: str,
    feedback_user_id: str,
    created_at: float,
    request_id: str | None,
) -> dict[str, Any]:
    return CaseFeedback.model_validate(
        {
            "feedback_id": feedback_id,
            "case_id": case_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "kind": kind,
            "feedback_note": feedback_note,
            "feedback_user_id": feedback_user_id,
            "created_at": created_at,
            "request_id": request_id,
        }
    ).model_dump(mode="python")


class InMemoryClinicalCaseStore:
    """Thread-safe bounded local store for unit and local development use."""

    def __init__(self, *, max_cases: int = 2_000, max_events_per_case: int = 100,
                 agent_model_catalog: object = None) -> None:
        if not 1 <= max_cases <= 100_000:
            raise ValueError("max_cases is out of range")
        if not 1 <= max_events_per_case <= 1_000:
            raise ValueError("max_events_per_case is out of range")
        self.max_cases = max_cases
        self.max_events_per_case = max_events_per_case
        self._agent_model_catalog = _catalog(agent_model_catalog)
        self._cases: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._reviews: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self._feedback: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self._lock = RLock()

    @staticmethod
    def _key(scope: tuple[str, str, str], case_id: str) -> tuple[str, str, str]:
        return scope[0], scope[1], case_id

    def _find(
        self,
        scope: tuple[str, str, str],
        case_id: str,
        *,
        allow_workspace: bool,
    ) -> tuple[tuple[str, str, str], dict[str, Any]] | None:
        key = self._key(scope, case_id)
        item = self._cases.get(key)
        if item is None:
            return None
        if not allow_workspace and item["owner_user_id"] != scope[2]:
            return None
        return key, item

    @staticmethod
    def _public(item: Mapping[str, Any]) -> dict[str, Any]:
        return dict(item)

    def create_case(
        self,
        *,
        session: object,
        title: str,
        summary: str | None = None,
        record: str | None = None,
        hypotheses: object = None,
        evidence: object = None,
        tags: object = None,
        request_id: object = None,
    ) -> dict[str, Any]:
        tenant_id, workspace_id, user_id = _scope(session)
        title = _clean_text(title, "title", 160)
        summary = _clean_summary(summary, record)
        record = _clean_record(record, summary)
        normalized_hypotheses = _clean_hypotheses(hypotheses)
        normalized_evidence = _clean_evidence(evidence)
        normalized_tags = _clean_tags(tags)
        request = _request_id(request_id)
        now = time.time()
        case_id = _new_id("case")
        item = _case_payload(
            case_id=case_id, tenant_id=tenant_id, workspace_id=workspace_id,
            owner_user_id=user_id, title=title, summary=summary, record=record,
            hypotheses=normalized_hypotheses, evidence=normalized_evidence, tags=normalized_tags,
            status="open", created_by_user_id=user_id, created_at=now,
            updated_by_user_id=user_id, updated_at=now,
            last_request_id=request,
        )
        with self._lock:
            if request is not None:
                for existing in self._cases.values():
                    if (
                        existing["tenant_id"] == tenant_id
                        and existing["workspace_id"] == workspace_id
                        and existing["owner_user_id"] == user_id
                        and existing.get("last_request_id") == request
                    ):
                        return self._public(existing)
            if len(self._cases) >= self.max_cases:
                oldest_key = min(self._cases, key=lambda key: float(self._cases[key]["updated_at"]))
                self._cases.pop(oldest_key, None)
                self._reviews.pop(oldest_key, None)
                self._feedback.pop(oldest_key, None)
            key = self._key((tenant_id, workspace_id, user_id), case_id)
            self._cases[key] = item
            self._reviews[key] = []
            self._feedback[key] = []
        return self._public(item)

    def list_cases(
        self,
        *,
        session: object,
        limit: object = 50,
        offset: object = 0,
        owner_only: bool = True,
    ) -> dict[str, Any]:
        bounded_limit, bounded_offset = _page(limit, offset)
        tenant_id, workspace_id, user_id = _scope(session)
        with self._lock:
            items = [
                self._public(item)
                for item in self._cases.values()
                if item["tenant_id"] == tenant_id
                and item["workspace_id"] == workspace_id
                and (not owner_only or item["owner_user_id"] == user_id)
            ]
        items.sort(key=lambda item: (-float(item["updated_at"]), str(item["case_id"])))
        total = len(items)
        page = items[bounded_offset:bounded_offset + bounded_limit]
        next_offset = bounded_offset + bounded_limit if bounded_offset + bounded_limit < total else None
        return {"items": page, "total": total, "next_offset": next_offset}

    def get_case(self, *, session: object, case_id: str, allow_workspace: bool = False) -> dict[str, Any] | None:
        scope = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        with self._lock:
            found = self._find(scope, case_id, allow_workspace=allow_workspace)
            return self._public(found[1]) if found else None

    def update_case(
        self,
        *,
        session: object,
        case_id: str,
        title: str | None = None,
        summary: str | None = None,
        record: str | None = None,
        hypotheses: object = None,
        evidence: object = None,
        tags: object = None,
        tags_provided: bool = False,
        hypotheses_provided: bool = False,
        evidence_provided: bool = False,
        request_id: object = None,
    ) -> dict[str, Any] | None:
        scope = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        request = _request_id(request_id)
        with self._lock:
            found = self._find(scope, case_id, allow_workspace=False)
            if found is None:
                return None
            _, item = found
            if request is not None and item.get("last_request_id") == request:
                return self._public(item)
            if title is not None:
                item["title"] = _clean_text(title, "title", 160)
            if summary is not None:
                item["summary"] = _clean_text(summary, "summary", 20_000)
            if record is not None:
                item["record"] = _clean_text(record, "record", 20_000)
            if hypotheses_provided:
                item["hypotheses"] = _clean_hypotheses(hypotheses)
            if evidence_provided:
                item["evidence"] = _clean_evidence(evidence)
            if tags_provided:
                item["tags"] = _clean_tags(tags)
            now = time.time()
            item["updated_by_user_id"] = scope[2]
            item["updated_at"] = now
            item["last_request_id"] = request
            return self._public(item)

    def add_review(
        self,
        *,
        session: object,
        case_id: str,
        decision: str,
        review_note: str,
        request_id: object = None,
    ) -> dict[str, Any] | None:
        tenant_id, workspace_id, user_id = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        decision = _clean_id(decision, "decision")
        review_note = _clean_text(review_note, "review_note", 8_000)
        request = _request_id(request_id)
        now = time.time()
        with self._lock:
            found = self._find((tenant_id, workspace_id, user_id), case_id, allow_workspace=True)
            if found is None:
                return None
            key, item = found
            if request is not None:
                for existing in self._reviews.get(key, []):
                    if existing.get("request_id") == request:
                        return dict(existing)
            review = _review_payload(
                review_id=_new_id("review"), case_id=case_id, tenant_id=tenant_id,
                workspace_id=workspace_id, decision=decision, review_note=review_note,
                reviewer_user_id=user_id, created_at=now, request_id=request,
            )
            events = self._reviews.setdefault(key, [])
            events.append(review)
            del events[:-self.max_events_per_case]
            item["status"] = "reviewed"
            item["updated_by_user_id"] = user_id
            item["updated_at"] = now
            item["last_request_id"] = request
            item["review_count"] = len(events)
            item["last_review_at"] = now
            return dict(review)

    def add_feedback(
        self,
        *,
        session: object,
        case_id: str,
        kind: str,
        feedback_note: str,
        request_id: object = None,
    ) -> dict[str, Any] | None:
        tenant_id, workspace_id, user_id = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        kind = _clean_id(kind, "kind")
        feedback_note = _clean_text(feedback_note, "feedback_note", 8_000)
        request = _request_id(request_id)
        now = time.time()
        with self._lock:
            found = self._find((tenant_id, workspace_id, user_id), case_id, allow_workspace=True)
            if found is None:
                return None
            key, item = found
            if request is not None:
                for existing in self._feedback.get(key, []):
                    if existing.get("request_id") == request:
                        return dict(existing)
            feedback = _feedback_payload(
                feedback_id=_new_id("feedback"), case_id=case_id, tenant_id=tenant_id,
                workspace_id=workspace_id, kind=kind, feedback_note=feedback_note,
                feedback_user_id=user_id, created_at=now, request_id=request,
            )
            events = self._feedback.setdefault(key, [])
            events.append(feedback)
            del events[:-self.max_events_per_case]
            item["updated_by_user_id"] = user_id
            item["updated_at"] = now
            item["last_request_id"] = request
            item["feedback_count"] = len(events)
            item["last_feedback_at"] = now
            return dict(feedback)

    def list_reviews(self, *, session: object, case_id: str, allow_workspace: bool = False) -> list[dict[str, Any]]:
        scope = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        with self._lock:
            found = self._find(scope, case_id, allow_workspace=allow_workspace)
            if found is None:
                return []
            return [dict(item) for item in self._reviews.get(found[0], [])]

    def list_feedback(self, *, session: object, case_id: str, allow_workspace: bool = False) -> list[dict[str, Any]]:
        scope = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        with self._lock:
            found = self._find(scope, case_id, allow_workspace=allow_workspace)
            if found is None:
                return []
            return [dict(item) for item in self._feedback.get(found[0], [])]

    def authorized_agent_models(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._agent_model_catalog]

    def close(self) -> None:
        return None


class SQLiteClinicalCaseStore:
    """Transactional SQLite implementation for local restart-safe tests."""

    SCHEMA_VERSION = 2

    def __init__(self, path: str | Path, *, agent_model_catalog: object = None) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            location = Path(self.path)
            location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if location.exists() and location.is_dir():
                raise ValueError("clinical case path must be a file")
        self._lock = RLock()
        self._closed = False
        self._agent_model_catalog = _catalog(agent_model_catalog)
        self._connection = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
        self._connection.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
        self._initialize()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("clinical case store is closed")

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._ensure_open()
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    @contextmanager
    def _read(self):
        with self._lock:
            self._ensure_open()
            yield self._connection

    def _initialize(self) -> None:
        with self._transaction():
            current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if current not in (0, 1, self.SCHEMA_VERSION):
                raise RuntimeError(f"unsupported clinical case schema version: {current}")
            if current == 0:
                self._connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS clinical_cases (
                        case_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        owner_user_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        summary_text TEXT NOT NULL,
                        record_text TEXT NOT NULL,
                        hypotheses_json TEXT NOT NULL,
                        evidence_json TEXT NOT NULL,
                        tags_json TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ('open', 'reviewed')),
                        created_by_user_id TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_by_user_id TEXT NOT NULL,
                        updated_at REAL NOT NULL,
                        last_request_id TEXT,
                        PRIMARY KEY (tenant_id, workspace_id, case_id)
                    );
                    CREATE INDEX IF NOT EXISTS clinical_cases_scope_idx
                      ON clinical_cases (tenant_id, workspace_id, owner_user_id, updated_at DESC);
                    CREATE TABLE IF NOT EXISTS clinical_case_reviews (
                        review_id TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        review_note TEXT NOT NULL,
                        reviewer_user_id TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        request_id TEXT,
                        PRIMARY KEY (tenant_id, workspace_id, review_id)
                    );
                    CREATE INDEX IF NOT EXISTS clinical_case_reviews_case_idx
                      ON clinical_case_reviews (tenant_id, workspace_id, case_id, created_at DESC);
                    CREATE TABLE IF NOT EXISTS clinical_case_feedback (
                        feedback_id TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        feedback_note TEXT NOT NULL,
                        feedback_user_id TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        request_id TEXT,
                        PRIMARY KEY (tenant_id, workspace_id, feedback_id)
                    );
                    CREATE INDEX IF NOT EXISTS clinical_case_feedback_case_idx
                      ON clinical_case_feedback (tenant_id, workspace_id, case_id, created_at DESC);
                    PRAGMA user_version = 2;
                    """
                )
                current = 2
            if current == 1:
                self._connection.executescript(
                    """
                    ALTER TABLE clinical_cases ADD COLUMN summary_text TEXT NOT NULL DEFAULT '';
                    ALTER TABLE clinical_cases ADD COLUMN hypotheses_json TEXT NOT NULL DEFAULT '[]';
                    ALTER TABLE clinical_cases ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '[]';
                    UPDATE clinical_cases SET summary_text=record_text WHERE summary_text='';
                    PRAGMA user_version = 2;
                    """
                )

    @staticmethod
    def _case_row_payload(row: sqlite3.Row, *, review_count: int, feedback_count: int,
                          last_review_at: float | None, last_feedback_at: float | None) -> dict[str, Any]:
        return _case_payload(
            case_id=row["case_id"], tenant_id=row["tenant_id"], workspace_id=row["workspace_id"],
            owner_user_id=row["owner_user_id"], title=row["title"], summary=row["summary_text"] or row["record_text"],
            record=row["record_text"],
            hypotheses=json.loads(row["hypotheses_json"] or "[]"),
            evidence=json.loads(row["evidence_json"] or "[]"),
            tags=json.loads(row["tags_json"] or "[]"), status=row["status"],
            created_by_user_id=row["created_by_user_id"], created_at=float(row["created_at"]),
            updated_by_user_id=row["updated_by_user_id"], updated_at=float(row["updated_at"]),
            last_request_id=row["last_request_id"], review_count=review_count,
            feedback_count=feedback_count, last_review_at=last_review_at,
            last_feedback_at=last_feedback_at,
        )

    def _fetch_case(
        self,
        connection: sqlite3.Connection,
        scope: tuple[str, str, str],
        case_id: str,
        *,
        allow_workspace: bool,
    ) -> dict[str, Any] | None:
        query = (
            "SELECT * FROM clinical_cases WHERE tenant_id=? AND workspace_id=? AND case_id=?"
            if allow_workspace
            else "SELECT * FROM clinical_cases WHERE tenant_id=? AND workspace_id=? AND owner_user_id=? AND case_id=?"
        )
        params = (scope[0], scope[1], case_id) if allow_workspace else (*scope, case_id)
        row = connection.execute(query, params).fetchone()
        if row is None:
            return None
        review_row = connection.execute(
            "SELECT COUNT(*) AS count, MAX(created_at) AS last_at FROM clinical_case_reviews "
            "WHERE tenant_id=? AND workspace_id=? AND case_id=?",
            (scope[0], scope[1], case_id),
        ).fetchone()
        feedback_row = connection.execute(
            "SELECT COUNT(*) AS count, MAX(created_at) AS last_at FROM clinical_case_feedback "
            "WHERE tenant_id=? AND workspace_id=? AND case_id=?",
            (scope[0], scope[1], case_id),
        ).fetchone()
        return self._case_row_payload(
            row,
            review_count=int(review_row["count"]),
            feedback_count=int(feedback_row["count"]),
            last_review_at=float(review_row["last_at"]) if review_row["last_at"] is not None else None,
            last_feedback_at=float(feedback_row["last_at"]) if feedback_row["last_at"] is not None else None,
        )

    def create_case(self, *, session: object, title: str, summary: str | None = None,
                    record: str | None = None, hypotheses: object = None, evidence: object = None,
                    tags: object = None, request_id: object = None) -> dict[str, Any]:
        tenant_id, workspace_id, user_id = _scope(session)
        title = _clean_text(title, "title", 160)
        summary = _clean_summary(summary, record)
        record = _clean_record(record, summary)
        normalized_hypotheses = _clean_hypotheses(hypotheses)
        normalized_evidence = _clean_evidence(evidence)
        normalized_tags = _clean_tags(tags)
        now = time.time()
        case_id = _new_id("case")
        request = _request_id(request_id)
        with self._transaction():
            if request is not None:
                existing = self._connection.execute(
                    "SELECT case_id FROM clinical_cases WHERE tenant_id=? AND workspace_id=? "
                    "AND owner_user_id=? AND last_request_id=?",
                    (tenant_id, workspace_id, user_id, request),
                ).fetchone()
                if existing is not None:
                    result = self._fetch_case(
                        self._connection, (tenant_id, workspace_id, user_id), existing["case_id"],
                        allow_workspace=False,
                    )
                    if result is not None:
                        return result
            self._connection.execute(
                """INSERT INTO clinical_cases
                   (case_id, tenant_id, workspace_id, owner_user_id, title, summary_text, record_text,
                    hypotheses_json, evidence_json, tags_json,
                    status, created_by_user_id, created_at, updated_by_user_id, updated_at, last_request_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)""",
                (case_id, tenant_id, workspace_id, user_id, title, summary, record,
                 json.dumps(normalized_hypotheses, ensure_ascii=False, separators=(",", ":")),
                 json.dumps(normalized_evidence, ensure_ascii=False, separators=(",", ":")),
                 json.dumps(normalized_tags, ensure_ascii=False, separators=(",", ":")),
                 user_id, now, user_id, now, request),
            )
            result = self._fetch_case(self._connection, (tenant_id, workspace_id, user_id), case_id,
                                      allow_workspace=False)
        if result is None:
            raise RuntimeError("clinical case creation failed")
        return result

    def list_cases(self, *, session: object, limit: object = 50, offset: object = 0,
                   owner_only: bool = True) -> dict[str, Any]:
        bounded_limit, bounded_offset = _page(limit, offset)
        tenant_id, workspace_id, user_id = _scope(session)
        where = "tenant_id=? AND workspace_id=?" + (" AND owner_user_id=?" if owner_only else "")
        params: tuple[Any, ...] = (tenant_id, workspace_id) + ((user_id,) if owner_only else ())
        with self._read() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM clinical_cases WHERE {where}", params).fetchone()[0])
            rows = connection.execute(
                f"SELECT * FROM clinical_cases WHERE {where} ORDER BY updated_at DESC, case_id LIMIT ? OFFSET ?",
                (*params, bounded_limit, bounded_offset),
            ).fetchall()
            items = [
                self._fetch_case(connection, (tenant_id, workspace_id, user_id), row["case_id"],
                                 allow_workspace=True)
                for row in rows
            ]
        page = [item for item in items if item is not None]
        next_offset = bounded_offset + bounded_limit if bounded_offset + bounded_limit < total else None
        return {"items": page, "total": total, "next_offset": next_offset}

    def get_case(self, *, session: object, case_id: str, allow_workspace: bool = False) -> dict[str, Any] | None:
        scope = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        with self._read() as connection:
            return self._fetch_case(connection, scope, case_id, allow_workspace=allow_workspace)

    def update_case(self, *, session: object, case_id: str, title: str | None = None,
                    summary: str | None = None, record: str | None = None,
                    hypotheses: object = None, evidence: object = None, tags: object = None,
                    tags_provided: bool = False, hypotheses_provided: bool = False,
                    evidence_provided: bool = False,
                    request_id: object = None) -> dict[str, Any] | None:
        tenant_id, workspace_id, user_id = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        updates: list[str] = []
        params: list[Any] = []
        if title is not None:
            updates.append("title=?")
            params.append(_clean_text(title, "title", 160))
        if summary is not None:
            updates.append("summary_text=?")
            params.append(_clean_text(summary, "summary", 20_000))
        if record is not None:
            updates.append("record_text=?")
            params.append(_clean_text(record, "record", 20_000))
        if hypotheses_provided:
            updates.append("hypotheses_json=?")
            params.append(json.dumps(_clean_hypotheses(hypotheses), ensure_ascii=False, separators=(",", ":")))
        if evidence_provided:
            updates.append("evidence_json=?")
            params.append(json.dumps(_clean_evidence(evidence), ensure_ascii=False, separators=(",", ":")))
        if tags_provided:
            updates.append("tags_json=?")
            params.append(json.dumps(_clean_tags(tags), ensure_ascii=False, separators=(",", ":")))
        if not updates:
            raise ValueError("at least one case field is required")
        now = time.time()
        request = _request_id(request_id)
        updates.extend(("updated_by_user_id=?", "updated_at=?", "last_request_id=?"))
        params.extend((user_id, now, request))
        with self._transaction():
            current = self._fetch_case(
                self._connection, (tenant_id, workspace_id, user_id), case_id,
                allow_workspace=False,
            )
            if current is not None and request is not None and current.get("last_request_id") == request:
                return current
            result = self._connection.execute(
                f"UPDATE clinical_cases SET {', '.join(updates)} "
                "WHERE tenant_id=? AND workspace_id=? AND owner_user_id=? AND case_id=?",
                (*params, tenant_id, workspace_id, user_id, case_id),
            )
            if result.rowcount != 1:
                return None
            return self._fetch_case(self._connection, (tenant_id, workspace_id, user_id), case_id,
                                    allow_workspace=False)

    def add_review(self, *, session: object, case_id: str, decision: str, review_note: str,
                   request_id: object = None) -> dict[str, Any] | None:
        tenant_id, workspace_id, user_id = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        decision = _clean_id(decision, "decision")
        review_note = _clean_text(review_note, "review_note", 8_000)
        now = time.time()
        review_id = _new_id("review")
        request = _request_id(request_id)
        with self._transaction():
            case = self._fetch_case(self._connection, (tenant_id, workspace_id, user_id), case_id,
                                    allow_workspace=True)
            if case is None:
                return None
            if request is not None:
                existing = self._connection.execute(
                    "SELECT * FROM clinical_case_reviews WHERE tenant_id=? AND workspace_id=? "
                    "AND case_id=? AND request_id=? LIMIT 1",
                    (tenant_id, workspace_id, case_id, request),
                ).fetchone()
                if existing is not None:
                    return _review_payload(
                        review_id=existing["review_id"], case_id=existing["case_id"],
                        tenant_id=existing["tenant_id"], workspace_id=existing["workspace_id"],
                        decision=existing["decision"], review_note=existing["review_note"],
                        reviewer_user_id=existing["reviewer_user_id"],
                        created_at=float(existing["created_at"]), request_id=existing["request_id"],
                    )
            self._connection.execute(
                """INSERT INTO clinical_case_reviews
                   (review_id, case_id, tenant_id, workspace_id, decision, review_note,
                    reviewer_user_id, created_at, request_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (review_id, case_id, tenant_id, workspace_id, decision, review_note,
                 user_id, now, request),
            )
            self._connection.execute(
                """UPDATE clinical_cases SET status='reviewed', updated_by_user_id=?,
                   updated_at=?, last_request_id=?
                   WHERE tenant_id=? AND workspace_id=? AND case_id=?""",
                (user_id, now, request, tenant_id, workspace_id, case_id),
            )
        return _review_payload(
            review_id=review_id, case_id=case_id, tenant_id=tenant_id,
            workspace_id=workspace_id, decision=decision, review_note=review_note,
            reviewer_user_id=user_id, created_at=now, request_id=request,
        )

    def add_feedback(self, *, session: object, case_id: str, kind: str, feedback_note: str,
                     request_id: object = None) -> dict[str, Any] | None:
        tenant_id, workspace_id, user_id = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        kind = _clean_id(kind, "kind")
        feedback_note = _clean_text(feedback_note, "feedback_note", 8_000)
        now = time.time()
        feedback_id = _new_id("feedback")
        request = _request_id(request_id)
        with self._transaction():
            case = self._fetch_case(self._connection, (tenant_id, workspace_id, user_id), case_id,
                                    allow_workspace=True)
            if case is None:
                return None
            if request is not None:
                existing = self._connection.execute(
                    "SELECT * FROM clinical_case_feedback WHERE tenant_id=? AND workspace_id=? "
                    "AND case_id=? AND request_id=? LIMIT 1",
                    (tenant_id, workspace_id, case_id, request),
                ).fetchone()
                if existing is not None:
                    return _feedback_payload(
                        feedback_id=existing["feedback_id"], case_id=existing["case_id"],
                        tenant_id=existing["tenant_id"], workspace_id=existing["workspace_id"],
                        kind=existing["kind"], feedback_note=existing["feedback_note"],
                        feedback_user_id=existing["feedback_user_id"],
                        created_at=float(existing["created_at"]), request_id=existing["request_id"],
                    )
            self._connection.execute(
                """INSERT INTO clinical_case_feedback
                   (feedback_id, case_id, tenant_id, workspace_id, kind, feedback_note,
                    feedback_user_id, created_at, request_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (feedback_id, case_id, tenant_id, workspace_id, kind, feedback_note,
                 user_id, now, request),
            )
            self._connection.execute(
                """UPDATE clinical_cases SET updated_by_user_id=?, updated_at=?, last_request_id=?
                   WHERE tenant_id=? AND workspace_id=? AND case_id=?""",
                (user_id, now, request, tenant_id, workspace_id, case_id),
            )
        return _feedback_payload(
            feedback_id=feedback_id, case_id=case_id, tenant_id=tenant_id,
            workspace_id=workspace_id, kind=kind, feedback_note=feedback_note,
            feedback_user_id=user_id, created_at=now, request_id=request,
        )

    def _list_events(self, *, session: object, case_id: str, kind: str,
                     allow_workspace: bool) -> list[dict[str, Any]]:
        scope = _scope(session)
        case_id = _clean_id(case_id, "case_id")
        with self._read() as connection:
            if self._fetch_case(connection, scope, case_id, allow_workspace=allow_workspace) is None:
                return []
            if kind == "review":
                rows = connection.execute(
                    "SELECT * FROM clinical_case_reviews WHERE tenant_id=? AND workspace_id=? AND case_id=? "
                    "ORDER BY created_at ASC, review_id ASC", (scope[0], scope[1], case_id),
                ).fetchall()
                return [
                    _review_payload(
                        review_id=row["review_id"], case_id=row["case_id"], tenant_id=row["tenant_id"],
                        workspace_id=row["workspace_id"], decision=row["decision"],
                        review_note=row["review_note"], reviewer_user_id=row["reviewer_user_id"],
                        created_at=float(row["created_at"]), request_id=row["request_id"],
                    ) for row in rows
                ]
            rows = connection.execute(
                "SELECT * FROM clinical_case_feedback WHERE tenant_id=? AND workspace_id=? AND case_id=? "
                "ORDER BY created_at ASC, feedback_id ASC", (scope[0], scope[1], case_id),
            ).fetchall()
            return [
                _feedback_payload(
                    feedback_id=row["feedback_id"], case_id=row["case_id"], tenant_id=row["tenant_id"],
                    workspace_id=row["workspace_id"], kind=row["kind"],
                    feedback_note=row["feedback_note"], feedback_user_id=row["feedback_user_id"],
                    created_at=float(row["created_at"]), request_id=row["request_id"],
                ) for row in rows
            ]

    def list_reviews(self, *, session: object, case_id: str, allow_workspace: bool = False) -> list[dict[str, Any]]:
        return self._list_events(session=session, case_id=case_id, kind="review", allow_workspace=allow_workspace)

    def list_feedback(self, *, session: object, case_id: str, allow_workspace: bool = False) -> list[dict[str, Any]]:
        return self._list_events(session=session, case_id=case_id, kind="feedback", allow_workspace=allow_workspace)

    def authorized_agent_models(self) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_open()
            return [dict(item) for item in self._agent_model_catalog]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True


__all__ = ["InMemoryClinicalCaseStore", "SQLiteClinicalCaseStore"]
