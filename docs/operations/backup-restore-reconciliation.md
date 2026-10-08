# Backup and restore reconciliation contract

Status: `LOCAL CONTRACT / OWNED LOCAL JOINT DRILL PASS / PRODUCTION EXECUTION NOT_RUN`.

`infrastructure/scripts/backup_restore.py` handles a safe file-level rehearsal:
it copies already-exported components into an atomic backup directory, verifies
paths and SHA-256 checksums, restores only to a new or empty target, and keeps
purge in dry-run mode by default. It does not connect to Postgres, Redis,
Qdrant, object storage, or the API.

An authorized exporter can add this shape to each component in the backup
manifest and to the observed restore report:

```json
{
  "semantic": {
    "record_count": 42,
    "scope": {
      "tenant_ids": ["tenant-a"],
      "workspace_ids": ["workspace-a"],
      "collection_ids": ["reference"]
    },
    "acl_sha256": "<64 lowercase hex characters>",
    "relation_checksums": {
      "conversation_messages": "<64 lowercase hex characters>"
    }
  }
}
```

The values are claims from the exporter and must be derived from the restored
service, never copied from the backup manifest. Reconciliation compares the
file summary, declared logical metadata, required component names, and an
optional expected tenant/workspace/collection scope. If a backup declares
semantic metadata and the restore observation omits it, the result is
`MISMATCH`.

The external drill remains a separate gate. The operator must export and
restore Postgres conversations/audit data, object-store documents, vector
records, and any applicable Redis persistence under one release ID; run the
authorized adapters against the isolated restore; then pass the synthetic
wrong-tenant smoke matrix and record RPO/RTO. A local owned drill now provides this limited service execution: see
[restore18 evidence](../reports/evidence/production-2026-10-04/joint-restore18.json).
It restored a quiesced synthetic dataset using identical images, compared all
20 PostgreSQL tables/database grants and read objects/scoped vectors through
the real adapters, then verified internal login/search/tenant denial/revocation.
Production target, approved RPO/RTO budgets, representative workload and
independent review remain `NOT_RUN`; the local result does not close AUD03-32.

Example local reconciliation invocation:

```bash
python3 infrastructure/scripts/backup_restore.py reconcile \
  /path/to/backup/release-001 \
  /path/to/observed-restore.json \
  --required-component postgres \
  --required-component object_store \
  --required-component vectors \
  --required-component audit \
  --required-component conversations \
  --expected-scope /path/to/expected-scope.json
```

This command validates an already captured report; it does not perform a live
restore or imply that the external services were reachable.
