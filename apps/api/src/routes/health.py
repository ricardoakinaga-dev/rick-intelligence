"""Health endpoints: minimal public live/ready + detailed admin health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.lifecycle import DependencyState, evaluate_readiness
from dependencies.identity import require_permission
from dependencies.services import get_providers

router = APIRouter(tags=["System"])


@router.get("/health/live")
def live():
    return {"status": "live"}


@router.get("/health/ready")
def ready():
    providers = get_providers()
    states: list[DependencyState] = [check() for check in providers.health_checks.values()] or [
        DependencyState(name="kernel", ok=True, required=True)
    ]
    status, code = evaluate_readiness(states)
    # Truthful semantics: never 200+ok while a mandatory dependency is broken.
    body = {"status": status, "checks": [{"name": s.name, "ok": s.ok, "required": s.required} for s in states]}
    return JSONResponse(status_code=code, content=body)


@router.get("/api/v1/admin/health")
def admin_health(session=Depends(require_permission("observability.read"))):
    providers = get_providers()
    states: list[DependencyState] = [check() for check in providers.health_checks.values()] or [
        DependencyState(name="kernel", ok=True, required=True)
    ]
    status, _ = evaluate_readiness(states)
    return {"status": status, "checks": [{"name": s.name, "ok": s.ok, "required": s.required, "detail": s.detail} for s in states]}
