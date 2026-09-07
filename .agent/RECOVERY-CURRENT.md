# Pre-recovery finding — 2026-09-05 21:32 UTC onward

Canonical `.agent` recovery has since passed structural and preservation checks;
see `docs/architecture/controller-recovery.md` and the current state/backlog.
The diagnostic below is retained as the original finding, not a current claim
that all 264 failures remain. Sidecar reconciliation and peer review are pending.

This is a recovery diagnostic, not a replacement validated controller or gate.
The active user objective remains the complete State of Art / AAA program and
its frozen fourteen-criterion bar. Historical phase gates and the three child
repositories must remain preserved.

## Authoritative observed state

The installed engineering-framework checker was rerun after the latest local
work: `RESULT FAIL (pass=5 warn=0 fail=264)`. `.agent/state.json` is schema v1,
lacks active_action_id, points to a missing backlog task, and its active plan
does not meet the required living ExecPlan structure. Historical gate/ledger
formats also differ from v2. Current `.gauntlet-state-of-art/state.json` uses
noncanonical field shapes and stale evidence, and the orchestration task graph
contains stale completion/readiness claims. None is evidence of current release
approval. `make validate` checks import boundaries only and does not supersede
this failed controller validation.

The mutable code/test artifacts and dated reports establish local progress:

- `.gauntlet-state-of-art/reports/round-4-concurrency-verdict.md`: scoped
  same-instance review PASS, 41 tests, clean fingerprint. No cross-process claim.
- `reports/login-navigation-correction.md` under that same run: login allowlist
  and truthful status; production build/typecheck/lint pass; full web regression
  30 passed, six viewport-specific skips.
- `reports/readiness-deadline-integration.md`: combined API/packages/worker
  350 passed, 96 warnings; independent review pending.
- `reports/client-disconnect-diagnostic.md`: actual app immediate-disconnect
  failure reproduced 20/20; not fixed.

No external operation or destructive rollback is pending. External runtime,
multi-instance recovery, telemetry export, approved corpus, restore/soak and
production evidence remain NOT_RUN. Full visual approval remains unachieved.

## Required next action

Recover the canonical controller and active ExecPlan before opening another
material implementation lane. Preserve immutable historical ledgers and gates
with content hashes; explicitly migrate historical reference resolution instead
of rewriting historical decisions or dropping required checks. Reconstruct only
the current near-horizon backlog from actual artifacts, bind one active action
across state/backlog/plan/log, and require the installed v2 validator to pass.
Do not fabricate prior status transitions to make historical DONE claims valid.

Next executable action: inspect the complete runtime-state and ExecPlan engine
contracts and the existing historical gate references, then implement the
smallest compatibility-preserving archive/recovery transaction. This diagnostic
does not claim that transaction is already complete. No active subagent remains;
Harvey's readiness lane is integrated and locally tested.
