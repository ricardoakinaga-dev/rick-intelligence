# `infrastructure/compose`

The root files docker-compose.dev.yml and docker-compose.staging.yml are the
canonical production-shaped topology for API, web, worker, PostgreSQL, Redis,
Qdrant and private object storage. This directory holds their environment
templates and the disposable dependency laboratory.

The root compose files require application image digests, a reviewed
module:factory composition, external credentials and explicit endpoints. They
do not create a fake local fallback when a production dependency is missing.
Render with docker compose config --quiet before starting. Use
RICK_COMPOSE_FILE=docker-compose.staging.yml with make up, make down or
make logs for staging. A render is a static configuration check; it is not
runtime evidence. Docker startup, health, migration, worker, recovery and
cross-tenant smoke gates remain NOT_RUN until a disposable daemon and
credentials are available.

The reference worker image is a non-HTTP process. Its healthcheck invokes the
fail-closed worker launcher and requires an externally reviewed
`RICK_WORKER_COMPOSITION=module:factory`; it does not probe a port that the
worker does not serve.
