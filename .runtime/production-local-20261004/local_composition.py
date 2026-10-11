"""Explicit isolated LOCAL test graph. Refuses production; no paid providers."""
from dataclasses import replace
import os
from deployment_composition import _build_inputs, DeploymentRuntime
from core.config import ApiSettings
from services.external_composition import build_external_providers
class NoEmailDelivery:
    def deliver_password_reset(self, **kwargs):
        return False

def _inputs(settings):
    if settings.environment != "local" or os.environ.get("RICK_IDENTITY_POLICY") != "postgres-local-v1":
        raise RuntimeError("this isolated composition is local only")
    inputs = _build_inputs(settings)
    # Identity policy is explicitly selected; this flag approves identity only,
    # never simulated providers or deployment. Current external guard expects it.
    inputs.identity.production_safe = True
    # In this local HTTP/Redis lab, probe live connectivity. The package
    # production_safe marker remains False: TLS production approval is separate.
    inputs.rate_limiter.readiness_check = inputs.rate_limiter.health_check
    inputs.lease.readiness_check = inputs.lease.health_check
    return replace(inputs, password_reset_delivery=NoEmailDelivery())

def build_api_inputs(settings):
    return replace(_inputs(settings), worker_health_check_required=False)

def build_worker():
    settings=ApiSettings.from_env(); inputs=_inputs(settings)
    providers=build_external_providers(settings, inputs)
    providers._composition_inputs=inputs
    from admin_audit_outbox import PostgresAdminAuditReconciler
    return DeploymentRuntime(providers, admin_audit_reconciler=PostgresAdminAuditReconciler(inputs.connection_factory))
