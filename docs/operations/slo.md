# Initial SLO and SLI contract

These targets are policy starting points, not observed production results.
Local fixture benchmarks, staging measurements and production SLOs must be
reported in separate artifacts.

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

The current package provides bounded local counters/histograms and explicit
SLO evaluation. Distributed export, collector delivery, alert routing, soak
measurements and live SLO evidence remain `NOT_RUN`.
