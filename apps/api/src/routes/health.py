"""Health endpoints: dependency-free liveness and safe readiness diagnostics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from core.lifecycle import collect_readiness_states, evaluate_readiness, safe_dependency_state
from dependencies.identity import require_permission
from dependencies.services import get_providers

router = APIRouter(tags=["System"])

_READINESS_PROVIDER_COMPONENTS = {
    "chat": "chat",
    "embedding": "embedding",
    "object-store": "object_store",
    "object_store": "object_store",
    "provider": "provider",
    "qdrant": "vector_store",
    "queue": "queue",
    "redis": "redis",
    "rate_limiter": "redis",
    "retrieval": "retrieval",
    "storage": "storage",
    "vector-store": "vector_store",
    "vector_store": "vector_store",
}


def _record_readiness(request: Request, status: str, states: list[object]) -> None:
    """Record bounded readiness and known provider check failures safely."""

    telemetry = getattr(request.app.state, "telemetry", None)
    record_readiness = getattr(telemetry, "record_readiness", None)
    if callable(record_readiness):
        try:
            record_readiness(status=status, check_count=len(states))
        except Exception:
            # Observability must never change the health response.
            pass

    record_provider_failure = getattr(telemetry, "record_provider_failure", None)
    if not callable(record_provider_failure):
        return
    for state in states:
        name = getattr(state, "name", None)
        if getattr(state, "ok", False) is not False or not isinstance(name, str):
            continue
        provider = _READINESS_PROVIDER_COMPONENTS.get(name)
        if provider is None:
            continue
        try:
            record_provider_failure(provider=provider, reason="unavailable")
        except Exception:
            pass


@router.get("/health/live")
def live():
    return {"status": "live"}


@router.get("/health/ready")
async def ready(request: Request):
    providers = get_providers(request)
    states = await collect_readiness_states(providers)
    status, code = evaluate_readiness(states)
    safe_states = [safe_dependency_state(s) for s in states]
    _record_readiness(request, status, safe_states)
    # Truthful semantics: never 200+ok while a mandatory dependency is broken.
    body = {
        "status": status,
        "checks": [
            {"name": s.name, "ok": s.ok, "required": s.required}
            for s in safe_states
        ],
    }
    return JSONResponse(status_code=code, content=body)


@router.get("/api/v1/admin/health")
async def admin_health(request: Request, session=Depends(require_permission("observability.read"))):
    providers = get_providers(request)
    states = await collect_readiness_states(providers)
    status, _ = evaluate_readiness(states)
    safe_states = [safe_dependency_state(s) for s in states]
    _record_readiness(request, status, safe_states)
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


@router.get("/api/v1/admin/metrics/prometheus", response_class=PlainTextResponse)
async def admin_metrics_prometheus(request: Request, session=Depends(require_permission("observability.read"))):
    telemetry = getattr(request.app.state, "telemetry", None)
    exporter = getattr(telemetry, "prometheus_text", None)
    if not callable(exporter):
        return PlainTextResponse("# telemetry unavailable\n", status_code=503)
    return PlainTextResponse(exporter(), media_type="text/plain; version=0.0.4")


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request):
    """Expose only bounded process metrics for an internal Prometheus scrape.

    The exposition contains counters, readiness state and bounded latency
    summaries; it never includes request payloads, identities or credentials.
    Authentication remains on the administrative JSON and Prometheus routes,
    while the private Compose network restricts this scrape target.
    """

    telemetry = getattr(request.app.state, "telemetry", None)
    exporter = getattr(telemetry, "prometheus_text", None)
    if not callable(exporter):
        return PlainTextResponse("# telemetry unavailable\n", status_code=503)
    return PlainTextResponse(exporter(), media_type="text/plain; version=0.0.4")
