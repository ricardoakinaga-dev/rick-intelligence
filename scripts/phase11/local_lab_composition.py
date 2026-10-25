"""Local disposable composition for the PRD26 lab (not for production).

This module is a development harness: it reads local endpoints from the
validated settings and uses a static OIDC membership mapping. It is never
imported by the API/worker production paths. See the PRD26 evidence for the
loopback services and the explicit `RICK_API_COMPOSITION` invocation.
"""
from __future__ import annotations

import redis
from jwt import PyJWKClient

from rick_identity import OIDCIdentityProvider, OIDCSettings, OIDCVerifier
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
            "role": "VETERINARIAN",
            "status": "active",
            "membership_status": "active",
            "authorized_collection_ids": ["col-a"],
            "email": claims.get("email"),
        }

    return OIDCIdentityProvider(verifier, membership_resolver=membership, health_check=lambda: True)


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
        created_by="prd26-local-lab",
        redis_client=client,
        rate_limiter=limiter,
        rate_limit_namespace=namespace,
        lease=lease,
        worker_temp_root=".runtime/tmp/worker",
        worker_scope=("tenant-a", "workspace-a", "collection-a"),
        worker_health_check_required=False,
    )
