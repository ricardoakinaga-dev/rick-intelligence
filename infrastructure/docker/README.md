# REC-33 — static image boundary

This directory contains the reviewed local shape for the three canonical
images:

- `api.Dockerfile` packages `apps/api` and the canonical Python packages and
  starts the FastAPI entrypoint on port `8000`;
- `worker.Dockerfile` packages `apps/worker` and the same Python boundary;
  its launcher fails closed until a deployment supplies an explicit
  `RICK_WORKER_COMPOSITION=module:factory` that creates a fully injected
  `WorkerRuntime` with one explicit tenant/workspace/collection scope;
- `web.Dockerfile` installs the locked `apps/web/package-lock.json`, builds
  Next.js, and starts the production server on port `3000`.

The Dockerfiles deliberately have no mutable base-image default. The operator
must supply each `*_IMAGE` build argument as an immutable registry reference
ending in `@sha256:<64 lowercase hex characters>`. This keeps base-image
resolution visible in the release packet and prevents an accidental
`latest`-style build.

`release-manifest.json` is the current static packet. Its state is
`PREPARED_NOT_RUN`: output digests, signatures, vulnerability results,
canary observations, and rollback rehearsal are absent by design. The
manifest checker validates the packet without calling Docker, a registry,
`trivy`, or `cosign`:

```bash
python3 infrastructure/docker/check_release.py --mode prepared
```

`--mode candidate` is the later evidence gate. It intentionally rejects the
current packet until an operator records the immutable output digests and the
external signature, scan, canary, and rollback evidence. A passing static
check is a consistency check; it is not build, scan, runtime, or deployment
acceptance.

All credentials, tokens, database URLs, provider keys, and object-store
secrets enter at runtime through the deployment secret manager. The
Dockerfiles do not copy `.env` files or secret directories and do not put
secret-shaped values in `ENV` or `ARG` instructions. API, worker, and web
processes run as numeric non-root users.

The existing reference Compose file still describes an HTTP health endpoint
for the worker. The worker image here exposes a process-level healthcheck
because the repository has no worker HTTP server; reconciling that Compose
contract remains an external deployment change outside this write scope.

See [`RUNBOOK.md`](RUNBOOK.md) for the operator-owned build, digest, scan,
signature, canary, and rollback procedure. The runbook is a static contract;
no step in it was executed in this workspace.
