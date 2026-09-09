# External Evidence Blockers — Phase 2

**Candidate:** main at original HEAD 75131a0 plus an uncommitted local delta
**Classification:** STATE_OF_ART_CANDIDATE
**Rule:** a required BLOCKED_EXTERNAL or NOT_RUN gate prevents promotion.

| Capability | Required environment | Credentials / authority | Corpus / data | Risk if skipped | Next action |
| --- | --- | --- | --- | --- | --- |
| Clean release integrity | Clean committed checkout and CI runner | Commit/promotion authority | Exact artifact manifest | Stale or self-asserted release evidence | Commit candidate, regenerate typed v2 manifest, rerun fail-closed gate |
| PostgreSQL and queue fencing | Disposable PostgreSQL with six migrations | Non-production DSN and runtime operator | Tenant A/B jobs and crash fixtures | Duplicate publication, lost work or stale ACK | Run migration, EXPLAIN, two-worker, crash, DLQ/replay and retention harness |
| Redis coordination/rate limits | Disposable authenticated Redis, optionally TLS | Redis URL/certs and two API replicas | Tenant-scoped keys and concurrent requests | Lease split-brain or multi-replica bypass | Run Redis gate with failover/reconnect and shared rate-limit abuse |
| Private object storage | Disposable S3-compatible service | Scoped bucket credentials and TLS policy | Synthetic private documents and checksums | Content leakage, checksum drift or irrecoverable objects | Run PUT/HEAD/GET/DELETE, retention, auth and restore lifecycle |
| Qdrant projection | Disposable Qdrant with persistence | URL/API key/TLS policy | Versioned tenant-scoped points | ACL leakage, stale index or unsafe alias switch | Run collection/index/alias/rebuild/delete/restore gate |
| Durable ingestion E2E | Full API, worker, queue, object and vector stack | Runtime composition and provider credentials | Approved bounded document corpus | Publication state can diverge across failures | Execute upload-to-publish with crash boundaries and replay |
| Identity and tenancy | External identity or approved staging identity service | OIDC/JWKS/membership/session authority | Tenant A/B attack matrix | Cross-tenant observation through content/metadata/timing | Run full identity/session/object/job/vector/Evidence/Decision/audit matrix |
| Provider runtime | Disposable OpenAI-compatible HTTP provider or approved provider | Non-production provider key or local server authority | Grounded approved evaluation corpus | Provider failure, timeout or citation behavior unproven | Run capability, streaming, cancellation, retry and citation matrix |
| Distributed observability | OTel Collector, Jaeger, Prometheus and alert sink | Collector/alert routing authority | Synthetic trace/metric/audit traffic | Incidents invisible; SLO claims unverified | Validate propagation, redaction, aggregation, alerts and burn rates |
| Restore and DR | Isolated backup/restore environment | Backup, destroy and restore approval | Tenant A/B snapshots with checksums | RPO/RTO and isolation failure after disaster | Backup, destroy, restore, reconcile and measure RPO/RTO |
| Chaos and soak | Isolated fault-injection and load environment | Approval to kill/partition/slow services | Bounded load and fault matrix | Retry storms, leaks or corruption remain hidden | Run short soak, staging soak and dependency fault matrix |
| Performance | Production-shaped API/worker/web environment | Load-test and resource observation authority | Versioned 1/10/50/100 concurrency workload | SLO and capacity claims unsupported | Capture p50/p95/p99, throughput, errors, memory and cost |
| Frontend visual/accessibility | Browser runtime with API-backed staging | Design/accessibility reviewer authority | Current state matrix and user fixtures | Critical workflows or WCAG failures missed | Capture 375/768/1440 renders, screen reader, zoom, contrast and blind critique |
| Supply chain and promotion | CI runner, image registry and scanners | Signing, registry, canary and rollback authority | Exact image/dependency artifact set | Vulnerable or unverifiable artifacts promoted | Generate SBOM, run secret/dependency/container scans, sign and rehearse rollback |
| Independent final review | Fresh reviewer contexts and clean artifact | Go/no-go human risk acceptance | Current reports, raw logs and scorecard | Builder bias or unresolved High issue | Seal evidence packet and obtain independent architecture/security/ops/web approvals |

No credential, deployment authority, approved clinical corpus or destructive
runtime action was available or used during this local implementation.
