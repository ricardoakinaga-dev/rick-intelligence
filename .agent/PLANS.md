# Execution Plans

This workspace coordinates three existing repositories. The active plan is the
single source for the narrative, milestones, discoveries, decisions, recovery,
and outcome of the current cross-boundary migration slice. The current active
plan is `.agent/plans/rec-implementation.md`; prior phase plans and gates
remain historical context and are not rewritten. Pre-v2 gates and ledgers are
preserved byte-for-byte under `.agent/legacy-v1/`; its manifest maps original
paths to their archived locations. The
JSON state, backlog, and
append-only ledgers under `.agent/` own their respective machine-readable
concerns; do not duplicate or silently contradict them.

Before resuming, read `cvg-master-rag-v2/AGENTS.md`, this file, the active plan,
`.agent/state.json`, `.agent/backlog.json`, `.agent/execution-log.jsonl`, and
`.agent/verification.jsonl`. Preserve the three child Git repositories and
their existing history. Any future source mutation must have a disjoint scope,
an explicit task, and fresh verification.
