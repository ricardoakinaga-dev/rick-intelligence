# Optional Redis lease adapter

`packages/locking/src/rick_locking/redis.py` implements the existing
`LeaseBackend` protocol for callers that need a real Redis-backed lease. It is
an optional adapter: the package does not import `redis`, build a URL client,
or connect at import time. A caller injects an already configured async
Redis-like client, for example a `redis.asyncio.Redis` instance, and owns its
connection lifecycle unless `close_client=True` is selected.

An application composition layer can make the optional dependency and timeout
choice explicit:

```python
from redis.asyncio import Redis
from rick_locking import RedisLeaseStore

redis = Redis.from_url(
    redis_url,
    socket_connect_timeout=1.0,
    socket_timeout=1.0,
)
store = RedisLeaseStore(redis, timeout=2.0, close_client=True)
```

The snippet is an integration shape only; this repository does not install or
execute it as part of the locking package tests.

## Atomic protocol

Acquisition sends the equivalent of:

```text
SET <key> <owner> NX PX <ttl_ms>
```

Renew and release each use one Redis Lua `EVAL`. The script first compares the
stored value with the exact owner argument; only a matching owner may call
`PEXPIRE` or `DEL`. A missing, expired, or different-owner lease returns
`False` and cannot modify a replacement owner's lease.

The high-level `RedisLeaseClient` supplies the same owner-bound
`LeaseHandle` behavior as the in-memory and HTTP clients. The low-level store
is useful when a caller already manages its owner token.

## Bounds and failures

The adapter reuses the locking package's shared validators:

- key: 1–512 characters;
- owner payload: 1–256 characters;
- TTL: 1–3,600,000 ms;
- correlation ID: 1–128 allowed identifier characters;
- adapter operation timeout: greater than 0 and at most 30 seconds (default 5
  seconds).

Keys and owner values reject non-string values, empty values, and characters
below U+0020 or equal to U+007F. Redis results are accepted only as the
bounded scalar values expected from these commands: `OK`/`True` or no result
for `SET NX`, and integer `1`/`0` for the Lua scripts. Correlation IDs are
local metadata and are not sent to Redis.

Each adapter operation is wrapped in the configured timeout. Timeout failures
map to `LeaseError(code="timeout")`; connection and known transient Redis
failures map to `"unavailable"`; other command or client failures map to
`"internal_error"`; task cancellation propagates. Public errors contain only
the stable locking code, operation, correlation ID, and safe message. Redis
exception text, URLs, keys, owner tokens, and response bodies are not copied
into errors.

The adapter does not add retries, health checks, fencing tokens, quorum
semantics, Sentinel/Cluster setup, metrics, or a Redis dependency to the
package manifest. The injected client should also be configured with explicit
Redis socket/connect timeouts; the adapter timeout is the outer per-operation
bound.

## Verification and integration status

`packages/locking/tests/test_redis.py` uses an injectable deterministic
Redis-like double. It covers compare-owner release/renew, expiry and
replacement, successful renewal, timeout/error classification, validation,
and token redaction. No live Redis server or distributed-health test was run
for this adapter.

The adapter is not wired into the root factory yet. Selecting it in an
application remains an explicit integration step: construct/configure the
async Redis client in the owning composition layer, pass it to
`RedisLeaseStore` or `RedisLeaseClient`, and decide who closes that client.
