# Release and operations runbook

Status: `REFERENCE / NOT_RUN`.

The executable topology reference is
`infrastructure/compose/compose.reference.yml`. It requires immutable
API/worker/web image digests and secret-manager injection; it has no safe
default credentials. `infrastructure/scripts/validate-env.sh` checks variable
presence and production safety flags without printing values.

## Promotion gates

1. Validate the deployment environment in an isolated shell and review image
   digests, signatures, scans, and the release-integrity packet.
2. Run the migration checker, apply migrations under an operator lock, and
   capture checksums.
3. Prove Postgres, Redis, Qdrant, and object-store health before API
   readiness; verify degraded optional checks cannot become a ready claim.
4. Exercise upload → queue → lease → index → retrieval → delete/reindex with
   synthetic tenant fixtures, including wrong-tenant negatives.
5. Capture backup ID, component coverage, restore target, operator, checksum
   verification, and restore result. A backup file alone is not restore
   evidence.
6. Canary the API/web image, monitor error-rate/latency/dead-letter alerts,
   and retain a rollback image plus migration roll-forward plan.

## Backup/restore and rollback

Back up Postgres, Redis persistence where applicable, Qdrant snapshots, and the
object-store bucket under one release ID. Restore into an isolated target,
verify checksums/counts/ACL scope, then run the synthetic smoke matrix. Never
delete the prior release or volume before the restore check is accepted.

Rollback application images only when the migration is backward-compatible;
otherwise roll forward with the documented reconciliation. Rotate compromised
credentials through the secret manager and record the audit event without
logging secret values.

## Current environment evidence

Docker/Compose, external Postgres, Redis, Qdrant, object storage, production
secrets, telemetry collector, and live deployment were unavailable in this
run. Compose startup, migration execution, backup/restore, canary, rollback,
alert delivery, and production performance are therefore `NOT_RUN`, not
inferred from static files.
