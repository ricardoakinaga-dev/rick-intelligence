# Canonical controller recovery

The pre-v2 controller failed the installed schema checker with 264 findings.
Recovery preserves its thirty files byte-for-byte in `.agent/legacy-v1/`, with
SHA256 and original-to-archived path mappings in `manifest.json`. This includes
fifteen historical gates, ten plans, state, backlog, both ledgers and PLANS.
No prior decision was changed or converted to a new PASS.

Current state/backlog use schema v2 and a new observed event chain. Historical
DONE claims stay in the archive rather than receiving invented VERIFY/COMPLETE
transitions. `.agent/plans/state-of-art-recovery.md` is the living plan. The
initial v2 event contained a wrong-task action pointer; its raw log is preserved
in `.agent/recovery-attempts/initial-v2-log.jsonl`, and the explicit recovery event
records that normalization. This correction did not change transition facts.

Historical `.agent/gates/X` locations map to `.agent/legacy-v1/gates/X`.
The Phase 0.6/1.1 CI readers and skeleton required-file locator were updated;
archived artifacts themselves retain their original text. New canonical gates
belong in `.agent/gates/`. The archive is not an active gate namespace.

`make validate` now composes boundary validation, archive verification, canonical
controller validation and existing Git policy. The project-local validator and
its contracts are byte-identical snapshots of the installed framework; the
installed and local versions both returned PASS. A dirty local checkout is
reported, not promoted to a clean release artifact.

Recovery tests cover identical retry, retry after a partial copy, exact-byte
restoration from archive in a disposable fixture, changed/corrupt history,
omitted manifest entries, symlink destination rejection and a known-bad active
action pointer. Ten recovery plus historical skeleton unit tests passed.

After adding typed evidence references, the disposable controller fixture first
failed because it did not copy this report. The fixture now includes the report;
the same ten tests and root validation passed again. The repository controller
itself continued to pass; the omitted test-fixture artifact was not suppressed.
The first import of FAIL/retest records used the same timestamp, which the
strict per-stream ordering check rejected. Those original records are preserved
in `.agent/recovery-attempts/same-second-verification-records.jsonl`; the retest
record was normalized to its later recording observation. No verdict was changed.

The standalone Phase 1.1 CLI was also attempted and failed against the current
built product: that historical command requires placeholders and scans later
source/generated trees. It is not reported as a current PASS. Its unit suite and
decisions remain intact; current source boundaries are checked by the later
phase boundary checker already used by the root.

This recovery is not product acceptance. The Gauntlet/orchestration sidecar state
still needs canonical reconciliation, readiness/login need fresh review, the
disconnect defect remains open, and visual/external/operations gates remain
unproven. The complete fourteen-criterion AAA bar is unchanged.

## Dispatch correction after peer rejection

Peer review reproduced a HIGH bypass: JSON null state/backlog fell into a legacy
branch and the CLI exited zero. Current dispatch now requires both objects and
exact integer schema v2 before invoking archive/canonical checks. Historical
functions are never a fallback for malformed or downgraded current data.

The real CLI runs in a disposable Git fixture and rejects null, scalar/array,
missing, old, unknown, boolean and floating schema cases plus archive corruption;
valid current control still passes. Eleven recovery/skeleton tests, make validate
and the installed normative checker passed after the correction. Fresh review
remains required; the first rejected judgment is preserved in
`.gauntlet-state-of-art/reports/controller-review-1.md`.

## Closure recording

The second peer review passed with a clean fingerprint. Formal closure initially
failed because even NOT_REQUIRED authority requires actor/evidence/scope fields,
and the bootstrap NOT_RUN belonged to a separate verification scope. Original
closure gate/log bytes are retained under `.agent/recovery-attempts/`; required
metadata and its binding fingerprint were normalized without changing the PASS
decision or scope. A new observation in the bootstrap scope records that its
previously missing procedure was subsequently executed and peer-verified.
This is not human authorization or full-product approval. Deterministic closure
validation is required before the sidecar task executes.
