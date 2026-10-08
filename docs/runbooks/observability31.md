# OBS31 canonical observability

Status: **IMPLEMENTED, not approved**. This is reversible dev/staging
configuration. It does not approve a production SLA, delivery destination,
provider call, deployment or the original 39-criterion release bar.

The Collector is pinned to 0.123.0. Its scratch image has no shell health probe.
`collector-ready` reuses `RICK_API_IMAGE`, overrides its API entrypoint and uses
Python urllib to query `http://otel-collector:13133/` with a four-second timeout.
API, both workers and Prometheus wait for this sidecar to be healthy at startup.
Compose dependencies are startup gates; they do not stop running applications
when the Collector later fails. Exporter buffering is not guaranteed lossless.

Collector internal metrics use `service.telemetry.metrics.readers` with a pull
Prometheus exporter on 0.0.0.0:8888. The 8889 exporter carries received OTLP
metrics. The deprecated `address` field is ignored by default in this version;
see the [versioned Collector source](https://raw.githubusercontent.com/open-telemetry/opentelemetry-collector/v0.123.0/service/telemetry/config.go).

Keep the five public mounted YAML files at mode **0644**, including Collector,
Prometheus, both rule files and Alertmanager configuration. A host-owned 0600
file can pass a builder's read test while failing inside the Collector as uid
10001. The static checker validates these modes. This public-file policy does
not apply to the secret webhook URL file, which needs separate restricted
permissions readable by Alertmanager.

Prometheus loads both `infrastructure/compose/alerts.yml` and
`infrastructure/monitoring/prometheus.rules.yml`. DNS A discovery of `api`
scrapes each replica address with its own `instance` label. NoData preserves
`job,instance`; a healthy peer cannot hide a missing SLO metric. The `up` history
retains disappeared DNS targets for one hour, allowing the natural 10m NoData
and 5m unavailable holds to fire. After that hour a vanished target is forgotten;
indefinite detection requires an operator-owned expected-replica inventory.
Complete discovery loss also has an aggregate absent-target fallback. Stopping
a process while its address remains discovered produces ordinary `up == 0`.

Existing SLO breach (5m), NoData (10m), and all other thresholds are preserved.
API and Collector unavailable (5m) are **proposed local defaults**, not approved
production SLAs. Error-budget burn consumes only
`rick_api_http_business_{requests,errors}_total`. Those counters require the
separate API telemetry changes and an image built from their exact source.
Health/readiness/metrics traffic must supply no business samples.

Alertmanager is pinned to 0.28.1, runs as 65534:65534, has a read-only root and
a writable `alertmanager-data` named volume. Fresh volume initialization copies
the image-owned `/alertmanager` directory; existing volumes must already be
writable by that uid/gid. No root initialization helper is provided.

Set `RICK_ALERT_WEBHOOK_URL_FILE` to an absolute path to an operator-reviewed
file containing the receiver URL. Compose mounts that file at
`/run/secrets/rick-alert-webhook-url`; Alertmanager uses `url_file`, sends firing
and resolved notifications, and bounds request timeout and batch size. No URL
or token belongs in Compose, examples or this runbook. File-backed Compose
secrets are bind mounts: arrange host permissions so uid/gid 65534 can read the
file, and keep it outside version control. The example path only permits static
rendering; it is not a usable receiver. Missing environment input fails closed.
See the [Alertmanager 0.28 receiver schema](https://prometheus.io/docs/alerting/0.28/configuration/)
and [0.28.1 image ownership](https://raw.githubusercontent.com/prometheus/alertmanager/v0.28.1/Dockerfile).

Alertmanager attaches to the internal `private` network and dedicated
`alert-egress` bridge for delivery; workers attach to `private` and dedicated
`worker-egress` because internal-only networking prevents embedding/provider
access. API already uses `edge`. These bridges enable outbound connectivity;
they are not destination allowlists. No monitoring service publishes staging
ports, and Alertmanager publishes no ports in either environment. Local rehearsal
must use only an owned synthetic receiver; no external notification is approved.

Run static checks without starting containers:

```sh
/tmp/rick-production-20261004/venv/bin/python -B -m pytest -q -p no:cacheprovider infrastructure/docker/tests/test_release_static.py infrastructure/docker/tests/test_observability31_topology.py
/tmp/rick-production-20261004/venv/bin/python -B scripts/phase11/check_compose.py
```

The checker renders only the nonsecret example environment, checks required
services, hardening, resources, mounts and wiring, and ignores ambient deployment
variables. Static tests cannot establish binary configuration validity, volume
ownership at runtime, receipt of notifications, timed PromQL behavior, scaling
behind a host-bound API port, or outage recovery. Lead owns those real validations
in an isolated lab, using exact images, an owned local sink and unchanged holds.
