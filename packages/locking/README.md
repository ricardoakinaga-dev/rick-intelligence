# `packages/locking`

Root-owned asynchronous lease boundary for owner-safe `acquire`, `renew`, and
`release`. The package has no dependency on the preserved Locker or Professor
trees; its HTTP adapter speaks their compatible endpoint payloads.

## Public boundary

`LeaseClient` is the port implementation. It generates a cryptographically
random owner token for each successful acquisition and returns a
`LeaseHandle`, or `None` on contention:

```python
from rick_locking import InMemoryLeaseClient

client = InMemoryLeaseClient()
async with client.lease("professor:workspace", ttl_ms=30_000) as lease:
    if lease is not None:
        await do_work()
```

`LeaseHandle` captures the exact owner and its `renew()` and `release()` calls
cannot operate on another owner. Exiting the handle context always attempts a
release, including when the body is cancelled. Cleanup is shielded, bounded,
and awaited before the context exits. A handle can also start one cancellable
renewal heartbeat with `handle.start_heartbeat()` or
`async with handle.heartbeat():`.

`LeaseBackend` is the low-level async protocol. `InMemoryLeaseStore` provides
atomic same-key acquisition, monotonic expiry, exact-owner renewal/release,
and an injectable `ManualClock` for deterministic tests. `HttpLockerStore`
maps operations to `/lock`, `/renew`, and `/unlock` with these request fields:

```json
{"lock_key": "...", "lock_value": "...", "ttl_ms": 30000}
```

`LockerClient` wraps that backend with the same owner-generating handle API.
HTTP requests have a bounded timeout, bounded response size, no redirects,
and no retries that could outlive caller cancellation.

Operational failures raise `LeaseError` with only a shared contract code,
operation, correlation ID, and safe message. Backend exception causes, URLs,
keys, owner tokens, and response bodies are not placed in errors or logs.
Contention, expiry, wrong-owner operations, and repeated release return
`False` rather than deleting or renewing another owner.
