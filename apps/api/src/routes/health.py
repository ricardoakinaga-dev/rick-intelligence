"""Health endpoints: dependency-free liveness and safe readiness diagnostics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.lifecycle import collect_readiness_states, evaluate_readiness, safe_dependency_state
from dependencies.identity import require_permission
from dependencies.services import get_providers

router = APIRouter(tags=["System"])


@router.get("/health/live")
def live():
    return {"status": "live"}


@router.get("/health/ready")
async def ready(request: Request):
    providers = get_providers(request)
    states = await collect_readiness_states(providers)
    status, code = evaluate_readiness(states)
    # Truthful semantics: never 200+ok while a mandatory dependency is broken.
    body = {
        "status": status,
        "checks": [
            {"name": safe_dependency_state(s).name,
             "ok": safe_dependency_state(s).ok,
             "required": safe_dependency_state(s).required}
            for s in states
        ],
    }
    return JSONResponse(status_code=code, content=body)


@router.get("/api/v1/admin/health")
async def admin_health(request: Request, session=Depends(require_permission("observability.read"))):
    providers = get_providers(request)
    states = await collect_readiness_states(providers)
    status, _ = evaluate_readiness(states)
    safe_states = [safe_dependency_state(s) for s in states]
    return {
        "status": status,
        "checks": [
            {"name": s.name, "ok": s.ok, "required": s.required, "detail": s.detail}
            for s in safe_states
        ],
    }


@router.get("/api/v1/admin/metrics")
async def admin_metrics(request: Request, session=Depends(require_permission("observability.read"))):
    telemetry = getattr(request.app.state, "telemetry", None)
    if telemetry is None or not callable(getattr(telemetry, "snapshot", None)):
        return {"implementation": "unavailable", "export": {"status": "NOT_CONFIGURED", "destination": None}}
    return telemetry.snapshot()
