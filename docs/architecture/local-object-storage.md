# Local object storage adapter

Status: `LOCAL ONLY / EXPLICIT DURABILITY PRIMITIVE`.

`packages/storage` now provides `rick_storage.LocalObjectStore`, a small typed
filesystem adapter for local development, hermetic tests, and an explicitly
local restart-durability boundary. It is deliberately not wired into
`apps/api`, `apps/web`, workers, or control-plane state in this change.

## Contract

The public port is `ObjectStore` and the local implementation accepts an
`ObjectScope(tenant_id, workspace_id, source_id)` for every operation:

| Operation | Result | Behavior |
| --- | --- | --- |
| `put(scope, key, data)` | `ObjectMetadata` | bounded bytes/file-like input, SHA-256 and byte size, atomic replacement |
| `get(scope, key, max_bytes=...)` / `read(...)` | `bytes` | bounded read, file-size and checksum verification |
| `head(scope, key)` | `ObjectMetadata` | metadata without loading the payload |
| `list(scope, prefix=..., limit=...)` | tuple of metadata | scope-only, deterministic key order, bounded result |
| `delete(scope, key)` | `bool` | deletes one object; absent objects return `False` |

`ObjectMetadata.checksum` is `sha256:<64 lowercase hex characters>`;
`ObjectMetadata.sha256` exposes the bare digest. The data envelope stores the
scope, logical key, size, and checksum together with the payload, so a reopen
does not depend on process memory or a sidecar index.

## Filesystem and security controls

The configured root and all adapter-created directories are tightened to
`0700`; object and temporary files are `0600`. The root must not be a symlink
or the filesystem root. Scope components reject empty values, path separators,
control characters, `.`/`..`, drive-colon syntax, and platform-troublesome
trailing dots/spaces. Object keys are relative logical keys: separators are
allowed for namespacing, but absolute paths, backslashes, empty segments,
`.`/`..`, control characters, and drive-colon syntax are rejected.

Keys are hashed for the physical filename rather than joined directly into the
filesystem path. Scope and key validation remains mandatory defense in depth;
the adapter also checks containment, rejects symlinked scope/object entries,
uses `O_NOFOLLOW` where the platform provides it, and never serializes backend
paths or exception text in its public errors.

## Durability behavior

`put` writes one self-describing envelope to a `0600` temporary file in the
scope directory, flushes and `fsync`s it, then commits with `os.replace`.
Directory sync is attempted where the local platform supports it. A failed
write therefore leaves the previous complete object in place; readers see a
complete old or new envelope, not a partially written payload. Reopening a new
adapter against the same root deterministically discovers the stored objects.

The adapter has bounded object writes, bounded reads, and bounded list results.
It can skip orphaned `.tmp-*` files left by an interrupted local process; an
unexpected or malformed committed envelope fails closed with a typed corruption
or integrity error.

## Production boundary

Production mode is intentionally unavailable: `mode` accepts only `local` or
`test`, and `RICK_ENV=production` is rejected. No application integration is
added here to accidentally make this primitive the default deployment store.

This is not S3, an S3 compatibility layer, or evidence of production object
storage. It has no remote API, credentials, presigned URLs, replication,
versioning/retention policy, server-side encryption, object lock, cross-process
lease/transaction protocol, distributed consistency, backup/restore drill,
quota accounting, range reads, media scanning, or centralized audit trail.
The configured root and its backup/recovery policy remain deployment-owned.
Concurrent local processes can still race on last-writer-wins replacement, and
directory `fsync` support depends on the underlying filesystem. A future
production adapter must be introduced behind the typed port with its own
security, migration, recovery, and external-service evidence.

## Verification

Focused tests under `packages/storage/tests/` cover traversal rejection,
atomic failed-write preservation, reopen, checksum/size metadata, write/read
limits, scope isolation, deterministic listing/deletion, permissions where
portable, corruption detection, and production-mode rejection. The package is
also checked with Python compilation.
