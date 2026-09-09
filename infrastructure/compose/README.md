# `infrastructure/compose`

The root files docker-compose.dev.yml and docker-compose.staging.yml are the
canonical production-shaped topology for API, web, Worker A, Worker B, PostgreSQL, Redis,
Qdrant, private object storage, OpenTelemetry Collector, Prometheus metrics
and Jaeger tracing. This directory holds their environment templates,
collector/metrics configuration and the disposable dependency laboratory.

The root compose files require application image digests, a reviewed
module:factory composition, external credentials and explicit endpoints. They
do not create a fake local fallback when a production dependency is missing.
Render with `docker compose config --quiet` after loading the matching example
environment before starting. The guarded `make up` command repeats that render,
requires all canonical services (including `worker` and `worker-b`), starts only
the selected local project and waits for every healthcheck. A timeout is a
failure and stores bounded diagnostics under the ignored `.runtime/phase-3/compose`
directory. Use
RICK_COMPOSE_FILE=docker-compose.staging.yml with make up, make down or
make logs for staging. A render is a static configuration check; it is not
runtime evidence. Docker startup, health, migration, worker, recovery and
cross-tenant smoke gates remain NOT_RUN until a disposable daemon and
credentials are available. `RICK_OTEL_ENDPOINT` is mandatory in both modes;
the application services wait for a healthy collector, the collector exports
traces to Jaeger and metrics to Prometheus, and no application payload is
written to collector debug logs.

The reference worker image is a non-HTTP process. Its healthcheck invokes the
fail-closed worker launcher and requires an externally reviewed
`RICK_WORKER_COMPOSITION=module:factory`; it does not probe a port that the
worker does not serve. `worker` and `worker-b` use distinct injected
`RICK_WORKER_ID` values and the same durable dependency set so the lab can
exercise fencing against one queue.
