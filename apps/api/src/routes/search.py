"""Canonical bounded search over the ACL-scoped root retrieval service."""

from __future__ import annotations

from collections.abc import Mapping
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from core.errors import ApiError
from dependencies.identity import require_authenticated
from dependencies.services import get_providers
from services.authorization_service import build_retrieval_context, has_permission

if TYPE_CHECKING:
    from services.retrieval_service import RetrievalApplicationService

router = APIRouter(tags=["Knowledge"])

_MAX_QUERY_CHARS = 2_000
_MAX_SCOPE_ID_CHARS = 128
_PUBLIC_EVIDENCE_FIELDS = (
    "document_id",
    "chunk_id",
    "title",
    "source",
    "text",
    "score",
    "rank",
    "page_start",
    "page_end",
    "section",
    "checksum",
    "collection_id",
    "workspace_id",
)


class SearchRequest(BaseModel):
    """The intentionally small and bounded public search request."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=_MAX_QUERY_CHARS)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=_MAX_SCOPE_ID_CHARS)
    collection_id: str | None = Field(default=None, min_length=1, max_length=_MAX_SCOPE_ID_CHARS)
    top_k: StrictInt = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain text")
        return value


def _value(item: object, field: str, default: object = None) -> object:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _retrieval_service(request: Request) -> "RetrievalApplicationService":
    """Return configured root retrieval or expose its safe public failure."""
    try:
        from services.retrieval_service import root_retrieval_enabled
    except ImportError:
        raise ApiError("retrieval_failed") from None

    if not root_retrieval_enabled():
        raise ApiError("retrieval_failed")
    retrieval = getattr(get_providers(request), "retrieval", None)
    if retrieval is None or not callable(getattr(retrieval, "retrieve", None)):
        raise ApiError("retrieval_failed")
    return retrieval  # type: ignore[return-value]


def _public_evidence(item: object) -> dict:
    """Serialize only the evidence fields approved for the public boundary."""
    return {field: _value(item, field) for field in _PUBLIC_EVIDENCE_FIELDS}


def _evidence_in_scope(item: object, context: Mapping[str, object]) -> bool:
    """Require internal evidence scope before any public projection."""
    tenant_id = _value(item, "tenant_id")
    workspace_id = _value(item, "workspace_id")
    collection_id = _value(item, "collection_id")
    expected_tenant = context.get("tenant_id")
    expected_workspace = context.get("workspace_id")
    allowed = context.get("allowed_collection_ids")
    if not all(isinstance(value, str) and value.strip() for value in (
        tenant_id, workspace_id, collection_id, expected_tenant, expected_workspace,
    )):
        return False
    if not isinstance(allowed, (list, tuple, set, frozenset)):
        return False
    return (
        tenant_id == expected_tenant
        and workspace_id == expected_workspace
        and ("*" in allowed or collection_id in allowed)
    )


def _public_metadata(result: object, context: dict) -> dict:
    """Keep result metadata useful without forwarding internal scope fields."""
    return {
        "backend": _value(result, "backend", ""),
        "candidate_count": _value(result, "candidate_count", 0),
        "selected_count": _value(result, "selected_count", 0),
        "fallback_used": bool(_value(result, "fallback_used", False)),
        "workspace_id": context["workspace_id"],
    }


def _record_retrieval_telemetry(request: Request, *, started: float, outcome: str) -> None:
    """Record local retrieval timing without coupling the endpoint to telemetry."""

    telemetry = getattr(request.app.state, "telemetry", None)
    recorder = getattr(telemetry, "record_retrieval", None)
    if callable(recorder):
        try:
            recorder(duration_ms=max(0.0, (time.perf_counter() - started) * 1_000), outcome=outcome)
        except Exception:
            # Metrics are advisory and must not alter the canonical API error.
            pass


def _record_retrieval_failure(request: Request) -> None:
    telemetry = getattr(request.app.state, "telemetry", None)
    recorder = getattr(telemetry, "record_provider_failure", None)
    if callable(recorder):
        try:
            recorder(provider="retrieval", reason="unavailable")
        except Exception:
            pass


@router.post("/api/v1/search")
def search(payload: SearchRequest, request: Request, session=Depends(require_authenticated)):
    if not has_permission(session, "sources.read"):
        raise ApiError("forbidden")

    settings = get_providers(request).settings
    if len(payload.query) > settings.max_query_chars:
        raise ApiError("validation_error")

    workspace_id = payload.workspace_id or getattr(session, "workspace_id", None)
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ApiError("forbidden")
    context = build_retrieval_context(
        session,
        workspace_id=workspace_id,
        collection_id=payload.collection_id,
    )
    retrieval = _retrieval_service(request)
    started = time.perf_counter()
    try:
        result = retrieval.retrieve(query=payload.query, context=context, top_k=payload.top_k)
    except Exception:
        _record_retrieval_telemetry(request, started=started, outcome="error")
        _record_retrieval_failure(request)
        # Retrieval implementations may contain provider/store details. The
        # canonical error envelope is the only public failure surface.
        raise ApiError("retrieval_failed") from None
    _record_retrieval_telemetry(request, started=started, outcome="success")

    evidence = _value(result, "evidence", ()) or ()
    if isinstance(evidence, (str, bytes, bytearray)) or not isinstance(evidence, (list, tuple)):
        raise ApiError("retrieval_failed")
    if any(not _evidence_in_scope(item, context) for item in evidence):
        # Fail closed on a malformed or mixed-scope adapter result. Do not
        # return a partial set that could make a compromised adapter useful.
        raise ApiError("retrieval_failed")
    items = [_public_evidence(item) for item in evidence]
    return {
        "query": _value(result, "query", payload.query),
        "items": items,
        "total": len(items),
        "metadata": _public_metadata(result, context),
    }
