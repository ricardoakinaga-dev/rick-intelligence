# Deployment boundary

The canonical topology is API, Web, Worker A, Worker B, PostgreSQL, Redis, Qdrant and
S3-compatible object storage. Observability is attached by the deployment
platform through the documented telemetry boundary. The root compose files
docker-compose.dev.yml and docker-compose.staging.yml are guarded
production-shaped baselines; RICK_COMPOSE_FILE selects the staging file.
`make up` validates the selected topology and waits for health/readiness; it
does not treat a detached container start as runtime success. `make down` is
scoped to the selected Compose project and preserves named volumes.

Deployment inputs are injected at runtime. API/worker/web image references,
base images, migrations, credentials and provider endpoints must be explicit;
no image or secret is inferred from a local default. Containers run as the
non-root `rick` user, expose health checks and use the release manifest for
build, digest, scan, SBOM, signature, canary and rollback evidence.

Promotion sequence:

```text
lint/contracts → unit/security/eval → build/SBOM/scan/sign
→ migration compatibility → disposable integration
→ backup/restore → canary → SLO observation → promote
```

The current compose references and release manifest are prepared artifacts.
This checkout has no accessible Docker daemon, external credentials or live
services, so build, startup, migration, canary and rollback remain `NOT_RUN`.
