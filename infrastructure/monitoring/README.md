# Monitoring reference

`prometheus.rules.yml` is a reference alert set with bounded, non-sensitive
labels only. The API currently records a bounded, per-process snapshot through
`MetricsMiddleware` and exposes it at the authenticated
`GET /api/v1/admin/metrics` route. That snapshot is an inspection seam, not a
Prometheus exposition endpoint, and it is not aggregated across instances.

The reference rules still assume a future runtime export of readiness, worker
status, HTTP outcomes and retrieval latency metrics. Prometheus/Docker are
unavailable here, so rule syntax against a live collector, alert delivery,
retention, and runtime evidence remain `NOT_RUN`.
