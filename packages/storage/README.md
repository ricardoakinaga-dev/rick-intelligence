# `packages/storage`

This package owns the scope-aware `ObjectStore` port and two adapters:
`LocalObjectStore` for local development and hermetic tests, and
`S3ObjectStore` for S3-compatible durable object storage. The adapters are
injected into applications; this package does not read credentials from the
environment or choose an HTTP client.

`rick_storage.LocalObjectStore` remains an explicit local durability
primitive:

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

For an S3-compatible service, inject a synchronous transport and credentials:

```python
from rick_storage import AwsCredentials, ObjectScope, S3ObjectStore

scope = ObjectScope("tenant-a", "workspace-a", "source-a")
store = S3ObjectStore(
    "https://objects.example.com",
    "rick-private",
    "us-east-1",
    credentials,
    http_transport,
    key_prefix="rick",
    require_https=True,
)
metadata = store.put(scope, "original/report.pdf", pdf_bytes)
payload = store.get(scope, "original/report.pdf")
store.close()
```

`S3ObjectStore` uses only standard-library SigV4 signing. Every request maps to
the private key namespace
`{key_prefix}/tenants/{tenant}/workspaces/{workspace}/sources/{source}/objects/{key}`;
scope components and logical keys are validated at the adapter boundary, and
list results outside the requested namespace are discarded before metadata is
returned. The bucket and endpoint are validated during construction.

Uploads are materialized only up to `max_object_bytes` and send SHA-256 and
size as `x-amz-meta-rick-checksum` and `x-amz-meta-rick-size`. Reads enforce
`max_read_bytes`, response XML enforces `max_response_bytes`, and object
responses with checksum metadata are verified. `head` requires usable size
and SHA-256 metadata so a caller cannot mistake an unverified remote object for
the typed metadata contract. Lists use bounded ListObjectsV2 pages and HEAD
each returned key to obtain that metadata.

The transport contract is `SyncHttpTransport`: `request(method, url,
headers=..., body=...)` returns a `SyncHttpResponse` with an integer status,
string headers, bounded `read(size)`, and `close()`. A production transport
should use TLS, preserve the signed headers, and close its pooled resources;
`require_https=True` makes the TLS requirement explicit at adapter
construction. Tests can provide an in-memory transport without network calls.

Remote statuses, malformed responses, transport failures, checksum failures,
limits, and closed-adapter use raise safe typed `ObjectStoreError` subclasses;
backend URLs, keys, exception text, and secret material are not included in
their messages or credential representations.

See [`docs/architecture/local-object-storage.md`](../../docs/architecture/local-object-storage.md)
for the local adapter's contract and limitations. The S3 adapter itself does
not provide application wiring, migrations, object retention/version policy,
backup/restore, media scanning, or centralized audit behavior.
