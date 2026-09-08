# Monitoring reference

`prometheus.rules.yml` is a reference alert set with bounded, non-sensitive
labels only. The API currently records a bounded, per-process snapshot through
`MetricsMiddleware` and exposes it at the authenticated
`GET /api/v1/admin/metrics` route. A protected Prometheus text projection is
also available at `GET /api/v1/admin/metrics/prometheus`; both endpoints are
bounded, local inspection seams and are not aggregated across instances.

The reference rules still assume a collector that scrapes the projection and
receives readiness, worker status, HTTP outcomes and retrieval latency metrics.
Prometheus/Docker are unavailable here, so rule syntax against a live
collector, alert delivery, retention, and runtime evidence remain `NOT_RUN`.
