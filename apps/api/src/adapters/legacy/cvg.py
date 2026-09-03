"""Legacy CVG adapters — the ONLY modules allowed to touch cvg-master-rag-v2.

Each adapter has a typed interface, lazy legacy import (never at module import
time, so unit tests never require Qdrant/Redis), failure translation to
canonical ApiError codes, and a deprecation/migration owner note.
"""

from __future__ import annotations

import sys
from pathlib import Path

from core.errors import ApiError
from models import SessionSnapshot

_MIGRATION_OWNER = "PH13-LEGACY-ADAPTERS (Phase 1.4: knowledge/ingestion/retrieval extraction)"
_DEPRECATION_STATE = "DUAL: legacy authoritative until dual verification passes per route"


def _legacy_src() -> Path:
    # Single centralized path resolution for legacy interop (documented, not scattered).
    root = Path(__file__).resolve().parents[6]
    return root / "cvg-master-rag-v2" / "src"


def _ensure_legacy_path() -> None:
    src = str(_legacy_src())
    if src not in sys.path:
        sys.path.insert(0, src)


def translate_legacy_exception(exc: Exception) -> ApiError:
    """Map legacy exceptions to canonical codes without leaking internals."""
    from fastapi import HTTPException as FastHTTPException

    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, FastHTTPException):
        status = exc.status_code
        return ApiError({400: "validation_error", 401: "unauthorized", 403: "forbidden",
                         404: "not_found", 409: "conflict", 413: "request_too_large",
                         429: "rate_limited", 503: "provider_unavailable"}.get(status, "internal_error"))
    message = str(exc).lower()
    if "qdrant" in message or "vector" in message:
        return ApiError("vector_store_unavailable")
    if "redis" in message or "lock" in message:
        return ApiError("lock_unavailable")
    if "timeout" in message:
        return ApiError("provider_timeout")
    return ApiError("internal_error")


class LegacyCVGIdentityAdapter:
    """Typed interface: validate/login/logout against preserved CVG enterprise_service."""

    deprecation_state = _DEPRECATION_STATE
    migration_owner = _MIGRATION_OWNER

    def validate_token(self, token: str | None) -> SessionSnapshot:
        if not token:
            return SessionSnapshot()
        try:
            _ensure_legacy_path()
            from services.enterprise_service import get_session as legacy_get_session

            data = legacy_get_session(token)
            user = (data.get("user") or {})
            tenant = (data.get("active_tenant") or {})
            if not data.get("authenticated"):
                return SessionSnapshot()
            return SessionSnapshot(
                authenticated=True, session_state=data.get("session_state", "active"),
                user_id=user.get("user_id"), email=user.get("email"), role=user.get("role"),
                canonical_role=data.get("canonical_role") or user.get("canonical_role"),
                permissions=list(user.get("permissions") or data.get("permissions") or []),
                tenant_id=tenant.get("tenant_id"), workspace_id=tenant.get("workspace_id"),
                session_id=data.get("session_id"),
                allowed_collection_ids=list(data.get("allowed_collection_ids") or []),
            )
        except Exception as exc:
            raise translate_legacy_exception(exc)


class LegacyCVGDocumentAdapter:
    """Typed interface: document/collection reads via preserved CVG registry (ACL-filtered by caller)."""

    deprecation_state = _DEPRECATION_STATE
    migration_owner = _MIGRATION_OWNER

    def list_collections(self) -> list[dict]:
        try:
            _ensure_legacy_path()
            from services.document_registry import get_corpus_overview

            overview = get_corpus_overview()
            if isinstance(overview, dict):
                return overview.get("collections", []) or []
            return []
        except Exception as exc:
            raise translate_legacy_exception(exc)


class LegacyProfessorAdapter:
    """Typed interface: Professor chat backend. Real orchestration wiring deferred to Phase 1.4;
    this adapter currently returns a deterministic grounded stub through the canonical contract."""

    deprecation_state = _DEPRECATION_STATE
    migration_owner = _MIGRATION_OWNER

    async def generate(self, *, message: str, context: dict, conversation_id: str) -> dict:
        allowed = context.get("allowed_collection_ids", ["rag_phase0"])
        collection = allowed[0] if allowed and allowed[0] != "*" else "rag_phase0"
        return {
            "answer": f"[stub-grounded] {message[:500]}",
            "citations": [{"document_id": "stub-doc-1", "chunk_id": "stub-chunk-1",
                           "title": "Stub source", "collection_id": collection}],
            "metadata": {"backend": "legacy-professor-adapter-stub", "model": "rick-professor"},
        }
