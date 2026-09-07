# `packages/storage`

This package owns typed storage seams and the local-only filesystem object
store. It does not wire storage into an application, migrate existing files,
or provide an S3-compatible surface.

`rick_storage.LocalObjectStore` is an explicit local durability primitive:

```python
from rick_storage import LocalObjectStore, ObjectScope

scope = ObjectScope("tenant-a", "workspace-a", "source-a")
store = LocalObjectStore("/var/lib/rick/object-store", max_read_bytes=50 * 1024 * 1024)
metadata = store.put(scope, "original/report.pdf", b"...")
payload = store.get(scope, "original/report.pdf")
```

Every object is scoped by tenant, workspace, and source. Keys are validated,
writes are staged and atomically replaced, object envelopes retain SHA-256 and
size metadata, and reads/lists are bounded. The adapter rejects
`mode="production"` and `RICK_ENV=production`; it is not a production object
store, S3 implementation, or distributed durability claim.

See [`docs/architecture/local-object-storage.md`](../../docs/architecture/local-object-storage.md)
for the contract, security boundary, verification, and known limitations.
