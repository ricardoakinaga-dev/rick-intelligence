"""Controlled case records: human registration, review, and feedback only.

The D04 gate is explicit and disabled by default.  No route in this module
invokes an agent, model, retrieval service, diagnosis flow, or prescription
flow.  Evidence values are references supplied by a human caller; this
module never fetches or interprets their contents.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse

from core.errors import ApiError
from dependencies.identity import require_permission
from dependencies.services import get_providers
from rick_contracts.cases import (
    AgentModelCatalogResponse,
    CaseCreateRequest,
    CaseDetailResponse,
    CaseFeedbackRequest,
    CaseFeedback,
    CaseListResponse,
    CaseRecord,
    CaseReview,
    CaseReviewRequest,
    CaseUpdateRequest,
)
from services.audit import emit_required


router = APIRouter(tags=["Clinical"])
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")


def _request_id(request: Request) -> str | None:
    for header_name in ("Idempotency-Key", "X-Request-ID"):
        header_value = request.headers.get(header_name)
        if header_value:
            candidate = header_value.strip()
            if _REQUEST_ID.fullmatch(candidate):
                return candidate
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _feature_response(request: Request, *, status_code: int, code: str, message: str, details: dict) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": _request_id(request) or "unknown",
                "details": details,
            }
        },
    )


def _guard(request: Request) -> object | JSONResponse:
    providers = get_providers(request)
    settings = providers.settings
    if not settings.clinical_cases_feature_enabled:
        return _feature_response(
            request,
            status_code=409,
            code="conflict",
            message=(
                "Clinical case records are disabled. Enable both "
                "RICK_CLINICAL_CASES_ENABLED and RICK_CLINICAL_CASES_D04_ENABLED "
                "for the explicitly controlled record/review/feedback scope."
            ),
            details={
                "feature": "clinical_cases",
                "status": "disabled",
                "d04_enabled": bool(settings.clinical_cases_d04_enabled),
            },
        )
    store = getattr(providers, "case_store", None)
    if store is None:
        return _feature_response(
            request,
            status_code=503,
            code="provider_unavailable",
            message="Clinical case storage is not configured for this enabled scope.",
            details={"feature": "clinical_cases", "status": "store_unavailable"},
        )
    return store


def _store(request: Request):
    value = _guard(request)
    if isinstance(value, JSONResponse):
        return value
    return value


def _audit_ready(sink: object) -> None:
    if sink is None:
        raise ApiError("provider_unavailable")
    health = getattr(sink, "health_check", None)
    if callable(health):
        try:
            if health() is not True:
                raise ApiError("provider_unavailable")
        except ApiError:
            raise
        except Exception:
            raise ApiError("provider_unavailable") from None


def _audit(request: Request, session: object, *, action: str, case_id: str | None, status: str) -> None:
    providers = get_providers(request)
    _audit_ready(providers.audit_sink)
    emit_required(providers.audit_sink, {
        "action": action,
        "actor_user_id": getattr(session, "user_id", None),
        "target_type": "clinical_case",
        # A create operation has no durable case id until after the store call;
        # the idempotency/request key is its auditable intent target.
        "target_id": case_id or _request_id(request) or "pending",
        "tenant_id": getattr(session, "tenant_id", None),
        "workspace_id": getattr(session, "workspace_id", None),
        "request_id": _request_id(request),
        "status": status,
    })


def _call(method, **kwargs):
    try:
        return method(**kwargs)
    except ValueError:
        raise ApiError("validation_error") from None
    except ApiError:
        raise
    except Exception:
        raise ApiError("provider_unavailable") from None


def _has_permission(session: object, permission: str) -> bool:
    from services.authorization_service import has_permission

    return has_permission(session, permission)


@router.get("/api/v1/cases/catalog/agents", response_model=AgentModelCatalogResponse)
def list_agent_model_catalog(request: Request, session=Depends(require_permission("cases.read"))):
    store = _store(request)
    if isinstance(store, JSONResponse):
        return store
    method = getattr(store, "authorized_agent_models", None)
    items = _call(method) if callable(method) else []
    return {
        "catalog_status": "configured" if items else "not_configured",
        "items": items,
    }


@router.post("/api/v1/cases", status_code=201, response_model=CaseRecord)
def create_case(payload: CaseCreateRequest, request: Request,
                session=Depends(require_permission("cases.manage"))):
    store = _store(request)
    if isinstance(store, JSONResponse):
        return store
    _audit(request, session, action="clinical_case.created", case_id=None, status="requested")
    item = _call(
        store.create_case,
        session=session,
        title=payload.title,
        summary=payload.summary,
        record=payload.record,
        hypotheses=payload.hypotheses,
        evidence=payload.evidence,
        tags=payload.tags,
        request_id=_request_id(request),
    )
    return item


@router.get("/api/v1/cases", response_model=CaseListResponse)
def list_cases(
    request: Request,
    session=Depends(require_permission("cases.read")),
    scope: Literal["mine", "workspace"] = Query(default="mine"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
):
    store = _store(request)
    if isinstance(store, JSONResponse):
        return store
    owner_only = scope == "mine"
    if not owner_only and not _has_permission(session, "cases.review"):
        raise ApiError("forbidden")
    result = _call(store.list_cases, session=session, limit=limit, offset=offset, owner_only=owner_only)
    return result


@router.get("/api/v1/cases/{case_id}", response_model=CaseDetailResponse)
def get_case(
    request: Request,
    case_id: str = Path(min_length=1, max_length=128),
    session=Depends(require_permission("cases.read")),
):
    store = _store(request)
    if isinstance(store, JSONResponse):
        return store
    allow_workspace = _has_permission(session, "cases.review")
    item = _call(store.get_case, session=session, case_id=case_id, allow_workspace=allow_workspace)
    if item is None:
        raise ApiError("not_found")
    reviews = _call(store.list_reviews, session=session, case_id=case_id, allow_workspace=allow_workspace)
    feedback = _call(store.list_feedback, session=session, case_id=case_id, allow_workspace=allow_workspace)
    return {"case": item, "reviews": reviews, "feedback": feedback}


@router.patch("/api/v1/cases/{case_id}", response_model=CaseRecord)
def update_case(
    payload: CaseUpdateRequest,
    request: Request,
    case_id: str = Path(min_length=1, max_length=128),
    session=Depends(require_permission("cases.manage")),
):
    store = _store(request)
    if isinstance(store, JSONResponse):
        return store
    values = payload.model_dump(exclude_unset=True)
    if _call(store.get_case, session=session, case_id=case_id, allow_workspace=False) is None:
        raise ApiError("not_found")
    _audit(request, session, action="clinical_case.updated", case_id=case_id, status="requested")
    item = _call(
        store.update_case,
        session=session,
        case_id=case_id,
        title=values.get("title"),
        summary=values.get("summary"),
        record=values.get("record"),
        hypotheses=values.get("hypotheses"),
        evidence=values.get("evidence"),
        tags=values.get("tags"),
        tags_provided="tags" in values,
        hypotheses_provided="hypotheses" in values,
        evidence_provided="evidence" in values,
        request_id=_request_id(request),
    )
    if item is None:
        raise ApiError("not_found")
    return item


@router.post("/api/v1/cases/{case_id}/reviews", response_model=CaseReview, status_code=201)
def review_case(
    payload: CaseReviewRequest,
    request: Request,
    case_id: str = Path(min_length=1, max_length=128),
    session=Depends(require_permission("cases.review")),
):
    store = _store(request)
    if isinstance(store, JSONResponse):
        return store
    if _call(store.get_case, session=session, case_id=case_id, allow_workspace=True) is None:
        raise ApiError("not_found")
    _audit(request, session, action="clinical_case.reviewed", case_id=case_id, status="requested")
    item = _call(
        store.add_review,
        session=session,
        case_id=case_id,
        decision=payload.decision,
        review_note=payload.review_note,
        request_id=_request_id(request),
    )
    if item is None:
        raise ApiError("not_found")
    return item


@router.post("/api/v1/cases/{case_id}/feedback", response_model=CaseFeedback, status_code=201)
def feedback_case(
    payload: CaseFeedbackRequest,
    request: Request,
    case_id: str = Path(min_length=1, max_length=128),
    session=Depends(require_permission("cases.feedback")),
):
    store = _store(request)
    if isinstance(store, JSONResponse):
        return store
    if _call(store.get_case, session=session, case_id=case_id, allow_workspace=True) is None:
        raise ApiError("not_found")
    _audit(request, session, action="clinical_case.feedback_recorded", case_id=case_id, status="requested")
    item = _call(
        store.add_feedback,
        session=session,
        case_id=case_id,
        kind=payload.kind,
        feedback_note=payload.feedback_note,
        request_id=_request_id(request),
    )
    if item is None:
        raise ApiError("not_found")
    return item


__all__ = ["router"]
