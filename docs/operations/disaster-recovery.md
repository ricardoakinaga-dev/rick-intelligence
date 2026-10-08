# Disaster recovery plan

Status: `RUNBOOK READY / OWNED LOCAL JOINT DRILL PASS / PRODUCTION DRILL NOT_RUN`.

## Recovery objectives

The proposed initial targets, pending operator approval, are RPO ≤15 minutes for PostgreSQL/object metadata and
RTO ≤60 minutes for the canonical API/worker path. Qdrant is a rebuildable
read model but should have a verified snapshot no older than 24 hours. Redis
ephemeral coordination may be lost; durable jobs and authoritative metadata
must reconstruct leases and retries without treating Redis as the primary
database.

## Recovery order

1. freeze writes and record the incident/release ID;
2. restore PostgreSQL schema, documents, jobs, attempts, audit and history;
3. restore or verify immutable object storage and checksums;
4. restore Qdrant snapshot or rebuild from verified chunks and index version;
5. start Redis with the production namespace and verify health/auth/TLS;
6. start workers, recover expired leases and inspect dead-letter jobs;
7. start API only after all required readiness probes pass;
8. run wrong-tenant negatives, retrieval/citation smoke and ingestion replay;
9. record RPO/RTO, counts, checksums, operator and residual anomalies.

Rollback of application images is allowed only across a migration-compatible
boundary. A failed migration is repaired by a reviewed roll-forward or an
isolated restore; destructive volume deletion is never an emergency shortcut.

The existing `infrastructure/scripts/backup_restore.py` reconciles exported
file-level artifacts and semantic scope claims. It does not pretend to perform
a live service restore. A real drill must produce service-derived counts,
ACL checksums and recovery timings for every component.


The owned local [restore18 rehearsal](../reports/evidence/production-2026-10-04/joint-restore18.json)
restored an offline consistent export into fresh isolated volumes with identical
images and compared SQL, database grants, object content and scoped vectors.
It then verified internal login, search, tenant denial and logout revocation.
Snapshot age was 13.529s at restore start; creation-to-verified-flow took 19.255s.
These timings describe a small quiesced lab, not approved production RPO/RTO
under representative writes. Both disposable targets were removed and the
original test program resumed with its credentials/configuration unchanged.
