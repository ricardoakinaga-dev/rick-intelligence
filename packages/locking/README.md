# `packages/locking`

Root-owned asynchronous boundaries for owner-safe leases and distributed
coordination. The package contains three deliberately separate modes:

- `RedisLeaseStore` / `RedisLeaseClient` for owner-safe distributed leases;
- `RedisRateLimiter` for atomic tenant-scoped fixed-window decisions;
- `InMemoryLeaseStore`, `InMemoryLeaseClient`, and `InMemoryRateLimiter` for
  explicit test/development execution only.

## Production composition

Install the real Redis extra in the service image:

```text
pip install 'rick-locking[redis]'
```

Build settings from deployment-owned environment values. Production requires a
`rediss://` URL, authentication, certificate verification, a bounded pool,
and finite operation/retry/circuit limits. Credentials and the URL are absent
from `repr` and package errors.

```python
from rick_locking import (
    RedisSettings,
    create_redis_lease_client,
    require_redis_ready,
)

settings = RedisSettings.from_env()
namespace = settings.namespace_for(
    "tenant-a",
    workspace_id="workspace-a",
    collection_id="collection-a",
)
lease = create_redis_lease_client(settings, namespace)
await require_redis_ready(lease)
```

`create_redis_client()` constructs `redis.asyncio.Redis` around a
`BlockingConnectionPool` with `max_connections`, pool wait timeout, socket
connect/read timeouts, keepalive, health checks, TLS options, and ACL
credentials. It does not connect during import or silently fall back to a
local implementation. The readiness call is an explicit startup gate.

`RedisNamespace` hashes tenant, workspace, collection, and logical key
components into bounded keys. Different tenant scopes use distinct scoped
fingerprints, and all keys from one namespace share a Redis Cluster hash tag
so multi-key Lua scripts remain atomic. A global namespace exists only through
the explicit `RedisNamespace.global_scope()` constructor.

## Lease and resilience contract

Acquisition uses `SET key owner NX PX ttl`. Renewal and release use Lua scripts
that compare the exact owner before changing the key. Expired, contended, and
wrong-owner operations return `False`; operational failures raise a redacted
`LeaseError`.

`RedisRetryPolicy` is finite and the total operation timeout is a hard
deadline. Acquisition and renewal may replay their owner-safe commands within
that budget. Release is intentionally one attempt because a lost delete
response is ambiguous after expiry. `RedisCircuitBreaker` is shared by the
adapter, opens after bounded transient failures, and permits one half-open
probe after cooldown. No vendor retry layer is enabled, avoiding stacked retry
amplification.

## Distributed rate limiting

`RedisRateLimiter.allow()` executes one atomic Lua script over a bucket and a
short-lived request marker. A supplied `request_id` makes an uncertain replay
idempotent; the marker prevents a second `INCR` for that request. Counter
mutations are single-attempt by design, so a transport failure returns
`False` and never risks silently granting or double-counting a request.
Different tenants use different namespaces. Backend errors and malformed
responses fail closed.

```python
from rick_locking import RedisRateLimiter

limiter = RedisRateLimiter(redis_client, namespace=namespace)
allowed = await limiter.allow(
    "chat",
    limit=30,
    window_seconds=60,
    request_id="request-123",
)
```

`validate_production_capability()` rejects missing, local, unmarked, or
malformed capabilities. `require_redis_ready()` then requires a successful
live Redis health check. The package does not wire that gate into `apps/api`;
the application composition root must inject the Redis lease/rate-limit
objects and call the gate before accepting production traffic.

The Phase 3 multi-replica gate at
`scripts/phase11/redis_multi_replica_runtime_gate.py` starts two independent
API-shaped processes, each with its own Redis client, against one explicitly
owned URL. It proves that both replicas consume the same atomic tenant bucket,
that request replay is idempotent, and that a second tenant receives a
separate bucket. Missing configuration or the optional Redis driver returns
`BLOCKED_EXTERNAL`; the gate never substitutes `InMemoryRateLimiter`.

## Local mode and verification

In-memory adapters accept only `mode="test"`, `"development"`, `"dev"`, or
`"local"`, and reject a production `RICK_ENV`. They expose
`production_safe=False`, so the production validation surface cannot accept
them by accident.

The package tests use deterministic Redis-like doubles and cover owner
fencing, bounds, timeout/cancellation behavior, retry budgets, circuit
transitions, TLS/auth/pool configuration rejection, namespace isolation,
atomic bucket replay, fail-closed readiness, and local-mode rejection. No live
Redis service is required by the focused suite; deployment must still run a
disposable Redis TLS/auth/readiness and multi-replica test before promotion.
