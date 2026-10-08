# Q24-08 / Q17-23.A — worker telemetry shutdown evidence

## Scope and behavior

The worker's actual script entrypoint now attempts a bounded diagnostic drain
when main() exits. It includes pending cleanup events, preserves operational
outcomes if telemetry blocks or fails, and gives the shared delivery lane a
fixed two-second budget. Reusable main() leaves ownership with its embedding
process. Shutting down an unused package lane does not allocate workers.

No deployment, provider call or database mutation is part of this slice.

## Executed checks

| Procedure | Result | Evidence |
| --- | --- | --- |
| Original missing-hook process scenarios | 7 expected pre-fix failures | `process-red.log` |
| Final Docker tests and observability package | 46 passed; exit 0 | `final-docker-observability-host.log` |
| Worker, API health and telemetry/fallback regression | 129 passed; exit 0; one TestClient deprecation warning | `runtime-regression.log` |
| Exact-budget test against a 3.0-second in-memory mutation | All 9 outcome combinations rejected; verifier exit 0 | `verify_budget_contract.py`, `budget-mutation.log` |

Static and canonical validation results are recorded in their command logs and
the final manifest: lint, typecheck/compilation, final make validate and diff
check all exited 0. Controller revision 380 retains the original global action.
Two newly authored controller metadata fields were normalized after archiving
the rejected rows; `control-metadata-repair.json` documents this exception and
the unchanged pre-continuation ledger prefixes. The API runtime interpreter lacks YAML used only by Docker
static tests; those tests run with the previously used host interpreter. Both
interpreter choices and all unsuccessful attempts are preserved in
`attempt-history.md`.

## Review

The initial independent review, `review-sartre-initial.md`, applies only to its
recorded fingerprint and identified one LOW coverage finding. The final test
addresses it with an exact 2.0-second assertion across nine operational/drain
outcomes. `self-review.md` records the integrator's separate review.

The final independent reviewer, Gibbs, returned PASS for C1–C6 with no findings
and independently verified all six candidate file hashes. See
`review-gibbs-final.md` and the pre/post-review fingerprint files. Canonical
reconciliation and its final command results are recorded separately in the
verification ledger, final controller logs and manifest.

## Limits and next boundary

This proves local worker process behavior with synthetic callbacks. It does
not prove external collector delivery, API process-owner shutdown, distributed
runtime, container stop-grace behavior, capacity, durable audit delivery or
production readiness. Permanently blocked daemon callbacks may still be
terminated with the process after the drain deadline.

Q17-23.A stays VERIFY and the global Q17-01.A stays IN_PROGRESS/PARTIAL. The
global next action remains the D02-authorized read-only inventory of actual
deployed migration histories/checksums. The next local observability boundary
is the API process owner's shutdown behavior; no shared per-app lifespan is
given ownership of the process-global lane here.
