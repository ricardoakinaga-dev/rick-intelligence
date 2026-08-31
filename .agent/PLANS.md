# Execution Plans

This workspace coordinates three existing repositories. The active plan is the
single source for the narrative, milestones, discoveries, decisions, recovery,
and outcome of the current cross-boundary migration slice. The current active
plan is `.agent/plans/phase-1.1-monorepo-skeleton.md`; the Phase 0.6 closure
plan and gate remain historical blocked context and are not rewritten. The
JSON state, backlog, and
append-only ledgers under `.agent/` own their respective machine-readable
concerns; do not duplicate or silently contradict them.

Before resuming, read `cvg-master-rag-v2/AGENTS.md`, this file, the active plan,
`.agent/state.json`, `.agent/backlog.json`, `.agent/execution-log.jsonl`, and
`.agent/verification.jsonl`. Preserve the three child Git repositories and
their existing history. Any future source mutation must have a disjoint scope,
an explicit task, and fresh verification.
