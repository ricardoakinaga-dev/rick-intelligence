# ADR-001 — Redis production capability

**Status:** Accepted for the package-local Phase 2.4 slice; application
integration and live promotion evidence remain pending.

## Problem and desired outcome

The package already had a deterministic, injected Redis-like lease adapter,
but it did not own real-client construction, connection bounds, tenant-safe
keying, finite retry/circuit policy, distributed rate limiting, or a startup
gate. Production must share coordination across replicas and must reject a
process-local fallback.

## Current evidence and constraints

- `LeaseBackend` is asynchronous and owner-bound.
- In-memory stores are useful for hermetic tests but cannot coordinate replicas.
- The package must remain import-safe when the optional Redis extra is absent.
- The application composition root owns credentials, service wiring, and the
  decision to close the client.
- Tenant/workspace/collection scope is available at composition time, while
  the existing lease protocol accepts only a logical key. A namespace is
  therefore bound to one store/limiter instance rather than inferred from an
  untrusted key.

## Invariants

1. A lease mutation can affect only the exact owner in its bounded namespace.
2. Different tenant scopes use distinct cryptographic fingerprints for the
   same logical operation.
3. Every network operation has a finite total deadline and bounded attempts.
4. A Redis outage cannot become a local fallback or an allowed rate-limited
   request.
5. Production readiness requires a package-approved Redis composition and a
   successful live health probe.

## Decision

`RedisSettings` validates scheme, TLS, authentication, certificate files,
pool size, socket/pool/operation timeouts, retry budget, and circuit bounds.
`create_redis_client()` lazily imports `redis.asyncio` and constructs a
`BlockingConnectionPool`; the package's retry policy is the only retry layer.

`RedisNamespace` hashes scope and logical identifiers into bounded keys and
places all keys in one Redis Cluster hash tag. `RedisLeaseStore` retains the
existing `SET NX PX` and compare-owner Lua primitives. Its finite policy can
replay acquisition and renewal, but release is at-most-once because the
response after a destructive command can be ambiguous. `RedisRateLimiter`
uses an atomic bucket/marker Lua script; counter mutations are single-attempt
and fail closed.

`InMemory*` adapters remain explicit local/test implementations with
`production_safe=False`. `validate_production_capability()` and
`require_redis_ready()` are the package-local fail-closed startup surface.

## Rejected alternatives

- **Unbounded `redis.Redis.from_url()` defaults:** leaves pool exhaustion and
  socket behavior deployment-dependent.
- **Vendor retries plus package retries:** creates stacked retry amplification
  during an outage.
- **Retry every mutation:** a release response can be lost after the delete,
  and a raw rate-counter retry can double-count. The selected policies keep
  those operations bounded and explicit.
- **Raw tenant/key concatenation:** permits delimiter ambiguity, leaks scope
  identifiers, and does not preserve a Redis Cluster hash slot.
- **Automatic in-memory fallback:** bypasses the multi-replica security and
  coordination boundary.

## Verification and limitations

The package-local suite verifies configuration rejection, fake-pool options,
namespace separation, retry/circuit behavior, owner fencing, atomic rate
decisions, and fail-closed readiness. It does not prove a live Redis server,
TLS certificate chain, ACL permissions, Sentinel/Cluster failover, network
partition behavior, multi-replica burst load, or application route wiring.
Those are explicit integration gates for the composition owner.
