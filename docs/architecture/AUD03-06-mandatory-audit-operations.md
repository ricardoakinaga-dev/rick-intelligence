# AUD03-06 — mandatory audit operation contract

Status: implemented candidate awaiting independent review, 2026-10-03. Scope and acceptance are
AUD03-06 in the frozen backlog and ADR-008's fail-closed prerequisite. This
document does not approve the implementation or change the quality bar.

Ownership: sessions/knowledge routes, identity_service/postgres_identity and
audit/sqlite_audit/postgres_audit; additive API audit helpers/tests and this
document. Identity/authorization packages, ingestion_service, worker and
existing migrations are read-only for this builder. Lead owns integration,
fresh independent review. The Lead authorized scoped disposable PostgreSQL
execution for this builder; its raw proofs are in evidence/audit06.

Invariant: a sensitive effect cannot precede successful admission into its
authoritative audit owner. A committed effect has either a committed completion
record or a durable operation explicitly requiring reconciliation. A standalone
requested event is insufficient. Delivery to the audit sink is separate from
the transaction committing the effect and completion outbox.

BASELINE: session revoke and most knowledge mutations emit after the effect;
reindex emits before the effect without a result. PostgreSQL admin identity
already commits mutations and admin.audit.completion outbox rows together.
Knowledge collection store has an inherited transaction connection seam.
Ingestion callbacks span jobs/files/vector stores and cannot be made ACID by
wrapping an unrelated PostgreSQL connection.

IMPLEMENTED: synchronous owner transactions for PostgreSQL session revoke,
collection metadata and grant updates. Reuse rick_outbox and the existing
admin.audit.completion projector. Each operation has an actor/tenant/workspace
bound idempotency key and request fingerprint. A separate api.audit.operation
row stores the operation's authoritative replay/result state; it is not fed to
the existing completion projector. Completion and owner mutation commit in the
same transaction. Same-key/same-input replay returns the original result;
changed input conflicts. Cross-scope replay is forbidden.

AUD11 integration interface: collection_transaction(store, *, tenant_id,
workspace_id, collection_id) acquires public store.collection_guard(scope)
before the owner memory lock/SQLite transaction/PostgreSQL transaction. The
normal service still calls public upsert_collection; its catalog fence is
reentrant on the same adapter/thread and remains active through audit commit.
PostgreSQL borrows the store's existing inherited-connection seam only after
the catalog guard is held. No package fence is bypassed or replaced. Lock
order is catalog guard -> owner DB transaction -> operation journal lock.

For callbacks crossing nontransactional stores, admission first commits a
bounded operation record with in_progress status, execution UUID and admitted
phase. A second journal transaction compares that exact admission under the
record lock and commits dispatched before invoking the callback. A workflow
execution guard is held from admission through outcome persistence. Completion
or failure is recorded afterward; if the completion write fails, the existing
operation remains inspectable and must never automatically repeat the callback.
Return a reconciliation reference instead of reporting an unaudited success.
Unknown outcomes require operator inspection, not speculative compensation or
replay. Exception outcomes cannot be called rolled_back without owner evidence.
This is a tracked workflow boundary, not a claim of distributed atomicity.
The preserved custom identity revoke/list_users/update_user interfaces use this
workflow when the provider does not expose the additive transaction hooks.
Only the concrete transaction-capable providers claim atomic owner commits.

Local memory operations retain process-local operation/replay state and are
explicitly not restart durable. SQLite stores operation/replay records in a
new additive local table beside audit_events using BEGIN IMMEDIATE, allowing
reopen and transaction-failure tests. PostgreSQL stores operation records in
the existing outbox schema. For SQLiteKnowledgeStore, the local metadata owner
holds api_audit_operations and api_audit_completions in its own database;
completion outbox and collection mutation commit together. A bounded delivery
attempt projects that completion to the configured audit sink after commit.
Projection can repeat after an interrupted delivery and is identified by the
operation correlation ID. Delivery failure does not erase the owner's durable
completion. This adds local helper-owned tables, not a PostgreSQL migration.
No PostgreSQL schema migration is planned: existing
event_type/aggregate_type/payload fields hold the new operation kind. If that
contract proves insufficient, send a migration/interface plan to the Lead
before touching any schema owned by the Lead.

Routes preserve successful response envelopes. An unresolved committed/unknown
outcome adds audit_operation_id/audit_status/reconciliation_required and uses
202; admission/storage failures before effects use provider_unavailable (503).
Idempotency-Key is optional; absent keys are unique per request. Operation
status is bound to actor and scope, with audit.read allowing an authorized
operator to inspect it. Operator reconciliation requires an explicit evidence
reference and never invokes the effect a second time.

GET /api/v1/audit/operations lists scoped pending records (limit 1–100), even
when the client lost the original response or omitted Idempotency-Key.
GET /api/v1/audit/operations/{id} returns the owner result/error and distinct
delivery state: projection_pending, published or dead_lettered for the
PostgreSQL completion row; SQLite owner outbox reports projection separately.
POST /api/v1/audit/operations/{id}/reconcile requires audit.read AND users.manage,
resolution effect_confirmed/no_effect and a bounded evidence_ref. Identical
proof replay is idempotent; changed proof or a known completed result conflicts.
Resolution records evidence and emits its own durable outcome. Execution and
reconciliation contend for the same nonblocking guard: a live executor causes
409 for either resolution, while request replay reads its record and returns
202 without redispatch. Memory uses a per-ledger non-reentrant mutex; file
SQLite uses a per-operation flock beside the canonical database path across
separate handles/processes. Lock files remain present to avoid inode replacement
breaking exclusion. SQLite requires the same host/filesystem lock domain.
PostgreSQL uses a dedicated session advisory connection, independently of short
journal transactions, with acquisition/health/release queries bounded to two
seconds. Its connection factory must provide dedicated sessions and configure
connection establishment timeouts; the SQL timeout cannot bound that factory.
Workflow lock order is execution guard -> journal transaction. Collection
owner operations retain catalog guard -> owner transaction -> journal lock;
atomic owner transactions do not hold a workflow session guard.

A free lock never proves absence of an external effect. no_effect can close
only durable pre-dispatch admitted records under the journal lock. This terminal
transition cancels admission: a stale executor must compare the same execution
UUID/phase/status before dispatch, so it cannot subsequently invoke the callback.
Guard health is checked before and after dispatch admission. All dispatched,
returned, uncertain and legacy unknown records reject no_effect. An orphan
in_progress/dispatched operation accepts effect_confirmed only while holding
the execution guard and proving its callback executor is absent. Memory and
SQLite use their existing execution guard domain. PostgreSQL also checks the
admitting process token against the local active-executor registry: a lost
advisory session alone cannot prove its callback stopped. Foreign, restarted
and legacy PostgreSQL execution owners remain fenced when this proof is absent.
Returned reconciliation_required outcomes still require the execution guard.
The operator evidence identifies the owner observation, without proving
external provider exactly-once behavior. Concurrent identical operator proofs
produce one durable outcome; later identical replay returns it unchanged.

Callback success records completed/returned; failed completion persistence
records reconciliation_required/returned with its result when storage permits.
Callback errors/cancellation record reconciliation_required/uncertain. Failure
before invocation can record failed/not_started; atomic owner cancellation
rolls back the owner and propagates cancellation. Guards release on all exits.
Process crash after dispatch, persistent journal failure, or remote work that
outlives client/connection loss can remain unresolved. Such records block
redispatch and cannot be converted to no_effect by a blind operator assertion.
Resolving their uncertainty automatically requires a fence/proof at the external
effect owner, outside this API-only scope. No lease expiry or timeout invents
that proof. Crash before dispatch allows an operator to cancel admitted state.

For asynchronous upload/retry, completed means the application callback accepted
the job and returned its public envelope, not that the worker has published it.
The job ID binds the accepted result to the ingestion service's authoritative
job outcome. The helper neither changes that service nor audits each worker
step. If result projection fails but the journal remains writable, the public
result is preserved as reconciliation_required; if storage remains down, the
original admission remains the recovery anchor. No callback is replayed in
either case.

Audit metadata contains identifiers and safe bounded outcome codes. Operation
fingerprints hash request inputs; raw bearer credentials and upload content are
not stored in the journal. Replay results are limited to the public route
envelopes, scoped to the actor. Pending operation rows cannot be evicted by
telemetry retention.

Required evidence: failure-first A09 revoke/delete; admission and completion
failures; exception outcomes; replay without duplicate mutation; input/scope
conflicts; real memory/SQLite persistence and transaction rollback; PostgreSQL
adapter connection/outbox rollback fixtures. Scoped live PostgreSQL checks use
canonical 0001–0008 in private random schemas. Rework2 adds independently held
execution/reconciliation races, SQLite spawned process crash, PostgreSQL session
loss with a still-live callback, late remote effects, cancellation, database
timeout and duplicate proof regressions. Raw failure-first and final commands/logs
plus source/dependency fingerprints are in
evidence/implementation-aud03-2026-10-03/audit06/rework2. The original independent
review, reproduced negative probes and earlier builder logs remain unchanged.
Existing API positives remain required. These are builder proofs, not promotion
approval; the Lead obtains a fresh independent review after integration.
