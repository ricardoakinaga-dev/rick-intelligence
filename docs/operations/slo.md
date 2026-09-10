# SLO and SLI contract

These targets are policy starting points, not observed production results.
Local fixture benchmarks, staging measurements and production SLOs are
separate evidence classes and must never be merged into one availability or
latency claim.

## LOCAL OBSERVATION

Local tests and fixture benchmarks may report latency, throughput, counters and
error classifications for development diagnosis. They are bounded engineering
observations only. A local observation is never an availability, durability,
staging or production SLO result, and it cannot satisfy a promotion gate by
itself. The current repository has local counters/histograms and deterministic
checks, but no distributed collector observation in this package; distributed
export and soak measurements remain `NOT_RUN`.

## STAGING SLO

Staging is a disposable production-shaped rehearsal with synthetic tenants.
Its measurements are valid only for the exact staging release, topology,
traffic window and alert configuration. They cannot become production PASS by
copying values or by a dashboard default.

## PRODUCTION SLO

Production evidence requires an authorized live service, the declared
retention/traffic/alert policy, current telemetry and an accountable owner.
Until that packet exists, every production record is `no_data` and the release
remains below promotion.

## Environment separation

| Environment | Purpose | Promotion meaning |
| --- | --- | --- |
| `development` | Fast feedback, hermetic tests and local diagnostics | Never an availability, durability or production-latency claim |
| `staging` | Disposable production-shaped rehearsal with synthetic tenants | Evidence is valid only for the exact staging release and cannot become production PASS by itself |
| `production` | Authorized live service with the declared retention, traffic and alert policy | SLO evidence is valid only with current telemetry, owner and release binding |

Every SLO record must include `environment`, `release_id`, `candidate_sha`,
`tree_sha`, `window`, `sample_count`, `scope`, `collected_at`, `status` and
`evidence_path`. A `no_data` record remains `no_data`; it cannot be converted
to healthy by a dashboard default or by copying a staging measurement.

The same SLI name may therefore have three records, one per environment, but
there is no cross-environment aggregation in the promotion engine.

| Service level | SLI | Initial target | Window |
| --- | --- | ---: | --- |
| API availability | successful non-health requests | ≥99.9% | 30 days |
| chat success | grounded terminal outcomes without service failure | ≥99.0% | 30 days |
| retrieval latency | authorized retrieval p95 | ≤1.5 s | 30 days |
| ingestion completion | accepted jobs published or explicitly dead-lettered | ≥99.0% | 24 h |
| job durability | accepted jobs recovered or terminal after restart | 100% | per drill |
| citation support | answer claims with verified cited support | ≥99.0% on approved set | per eval |
| provider error rate | typed provider failures / provider calls | ≤5% | 10 min alert |

Every measurement carries release ID, environment, sample count, scope and
collection time. Missing samples are `no_data`, never healthy. Required
telemetry dimensions are bounded `service`, route family, status class,
operation and safe reason; tenant/user/content values are excluded.

The minimum record shape is:

```json
{
  "environment": "development|staging|production",
  "release_id": "same-run-release-id",
  "candidate_sha": "same-run-commit",
  "tree_sha": "same-run-tree",
  "window": "bounded-window",
  "sample_count": 0,
  "scope": "bounded-service-scope",
  "collected_at": "RFC3339",
  "status": "no_data|healthy|breach",
  "evidence_path": "candidate-scoped-artifact"
}
```

The current package provides bounded local counters/histograms and explicit
SLO evaluation. Distributed export, collector delivery, alert routing, soak
measurements and live SLO evidence remain `NOT_RUN`.
