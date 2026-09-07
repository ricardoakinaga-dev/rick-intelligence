# Durable audit adapter

Status: `LOCAL ADAPTER / NOT PRODUCTION-COMPLETE`.

`apps/api/src/services/sqlite_audit.py` provides a standard-library SQLite
adapter for local restart durability. `SQLiteAuditSink` accepts a file path and
a positive `max_events`/`retention` count, sanitizes JSON-compatible event
dictionaries, appends them transactionally, and exposes bounded reads through
`list_events(limit=..., order="asc"|"desc")`. The `events` property preserves
the existing sink-facing view in oldest-first order.

The default process-local `InMemoryAuditSink` applies the same observability
redaction seam before retaining an event and caps its list at 10,000 entries.
That protects the local fallback from raw prompts, document/content fields,
credentials, tokens and query-bearing URLs; it does not turn process memory
into restartable or centralized audit storage.

The file-backed adapter:

- creates or tightens the immediate parent directory to `0700` and the
  database file to `0600`;
- enables SQLite WAL and `synchronous=FULL`;
- records schema version `1` in `PRAGMA user_version`;
- uses `BEGIN IMMEDIATE` for the insert and retention delete as one atomic
  transaction;
- retains only the newest configured number of events, including when a
  reopened instance uses a lower retention value; and
- rejects malformed/cyclic/non-JSON events without raising into the caller,
  while projecting every record through an explicit field allowlist and
  redacting credential-shaped keys such as passwords, tokens, authorization
  headers, cookies, and secrets. Non-HTTP hierarchical URLs are reconstructed
  without userinfo, query, or fragment data; the no-action path is limited to
  bounded adapter diagnostics (`sequence`, `writer`, `payload`, `second`).

The adapter is local durability plumbing, not a production audit architecture.
The root factory can select it with `RICK_AUDIT_SQLITE_PATH` and the admin
route reads through its bounded `list()` contract; `RICK_ENV=production`
rejects that local path. A production deployment still needs an approved
external audit store, its availability and fail-closed policy for
security-critical mutations, backup/restore and multi-instance recovery
evidence, and an explicit rollout decision. WAL and basic concurrent-writer
tests prove the local SQLite boundary only; they do not prove production
topology, tamper evidence, centralized retention, or external store recovery.
