"""Local disposable composition for the PRD26 lab (not for production).

This module is a development harness: it reads local endpoints from the
validated settings and uses a static OIDC membership mapping. It is never
imported by the API/worker production paths. See the PRD26 evidence for the
loopback services and the explicit `RICK_API_COMPOSITION` invocation.
"""
from __future__ import annotations

import os

import redis
from jwt import PyJWKClient

from rick_identity import OIDCIdentityProvider, OIDCSettings, OIDCVerifier
from rick_authorization import canonical_role, permissions_for_role
from rick_locking import RedisLeaseClient, RedisNamespace, RedisRateLimiter
from services.external_composition import ExternalCompositionInputs
from services.object_store_transport import StdlibS3HttpTransport

ISSUER = "http://127.0.0.1:18080/realms/rick"
CLIENT_ID = "rick-api"


def _identity():
    jwks = PyJWKClient(ISSUER + "/protocol/openid-connect/certs")
    verifier = OIDCVerifier(
        OIDCSettings(issuer=ISSUER, audience=CLIENT_ID, algorithms=("RS256",)),
        key_resolver=lambda kid: jwks.get_signing_key(kid).key,
    )

    def membership(subject, claims, tenant):
        return {
            "subject": subject,
            "tenant_id": tenant,
            "workspace_id": claims["workspace_id"],
            "user_id": "user-reader",
            "role": "KNOWLEDGE_MANAGER",
            "status": "active",
            "membership_status": "active",
            "authorized_collection_ids": ["col-a"],
            "email": claims.get("email"),
        }

    return OIDCIdentityProvider(verifier, membership_resolver=membership, health_check=lambda: True)




def _authorization_revalidator(*, context):
    """Re-resolve active membership and collections from the local database."""
    import psycopg

    tenant = context.get("tenant_id")
    workspace = context.get("workspace_id")
    user = context.get("user_id")
    if not all(isinstance(value, str) and value for value in (tenant, workspace, user)):
        return None
    with psycopg.connect(os.environ["RICK_EXTERNAL_DATABASE_DSN"]) as connection:
        connection.row_factory = psycopg.rows.dict_row
        row = connection.execute(
            "SELECT role, authorized_collection_ids FROM rick_memberships "
            "WHERE tenant_id=%s AND user_id=%s AND workspace_id=%s AND status='active'",
            (tenant, user, workspace),
        ).fetchone()
    if row is None:
        return None
    role = canonical_role(row["role"])
    return {
        **dict(context),
        "permissions": sorted(permissions_for_role(role)),
        "allowed_collection_ids": list(row.get("authorized_collection_ids") or []),
    }

def build(settings):
    client = redis.asyncio.from_url(settings.redis_url, decode_responses=True)
    namespace = RedisNamespace.global_scope(environment=settings.environment)
    limiter = RedisRateLimiter(client, namespace=namespace)
    lease = RedisLeaseClient(client, namespace=namespace)

    def connection_factory():
        import psycopg

        return psycopg.connect(settings.external_database_dsn)

    return ExternalCompositionInputs(
        connection_factory=connection_factory,
        object_store_transport=StdlibS3HttpTransport(
            settings.object_store_endpoint, require_https=False
        ),
        identity=_identity(),
        created_by="user-reader",
        redis_client=client,
        rate_limiter=limiter,
        rate_limit_namespace=namespace,
        lease=lease,
        worker_temp_root=".runtime/tmp/worker",
        worker_scope=("tenant-a", "workspace-a", "col-a"),
        worker_health_check_required=False,
        authorization_revalidator=_authorization_revalidator,
    )
