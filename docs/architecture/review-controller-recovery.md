# Review controller recovery

The canonical controller recovery received a scoped I1 peer PASS; it is not a
full product approval. The subsequent sidecar task preserves eleven prior files
under `.review-control-history/`, retaining original phase16 run state, lock bytes,
and unvalidated AAA pointers. SHA256 and inventory checks verify this history.
The stale lock's recorded process was absent; the old Gauntlet directory was
moved under an exclusive lock, not overwritten or marked completed.

The active run is `.gauntlet/state.json`, initialized by the normative state
manager as `state-of-art-aaa-recovered-20260905`. It retains the user's full
request in `goal.txt` and starts with zero imported acceptance rounds. Original
scoped reports remain accessible but do not become new full-criterion approval.

`.gauntlet-state-of-art/bar.canonical.json` adds missing canonical provenance and
schema fields to the original frozen bar. All fourteen IDs, targets, required
flags, severity/priority and evidence methods are checked against the original
bar bytes and hash. Required disconnect/observability and visual gaps remain
FAIL; absence of full-criterion proof remains NOT_RUN. No target was lowered.

`.orchestrate/state.json` and `.orchestrate-state-of-art/state.json` are generated
views of `.agent/backlog.json` and its state revision. They own no independent
task status and make no live-worker claim. The old AAA Gauntlet state files now
point to the canonical run. Run `review_control_views.py --write` after changing
canonical task state, then run it without flags to check for stale views.

`make validate` now includes canonical controller/archive checks, derived-view
and frozen-target verification, and normative review-state structural validation.
Identity/freshness is separately checked with Gauntlet resume or validate
`--check-drift`; structural success is not quality acceptance. After a legitimate
artifact change, use the state manager's explicit rebaseline with a concrete
reason, which marks prior evidence stale rather than silently accepting drift.

Run state is bound to an absolute workspace. A different checkout must initialize
its own separately identified run; copying a previous run does not prove identity
or freshness. The real-CLI positive fixture initially failed this identity check;
it now preserves the imported copy and initializes an empty-evidence fixture run
instead of relaxing the validator. The root workspace itself continued to pass.

Tests cover archive corruption, stale derived views, weakened required flags even
when both recovered bar copies change, and a shortened goal with a consistent but
wrong hash. Product runtime code was not changed in this recovery task. Sidecar
peer review and remaining product/visual/external criteria are still required.

Initial local verification: sixteen recovery/skeleton/view tests passed,
make validate passed, and the vendored Gauntlet helper then matched installed bytes.
Current Gauntlet validation initially passed with --check-drift immediately after
initialization; later legitimate source/control additions require explicit
rebaseline before sealed review. No imported round is marked accepted.
After adding typed evidence links, fixtures were expanded to include the referenced
documentation. A redundant directory creation then raised FileExistsError in one
fixture; removing that redundant setup repaired the fixture without changing the
runtime validators. This failed attempt is retained here rather than erased by a retry.

The first fresh I1 reviewer rejected final-approval replay: evidence from a prior
run with old timestamps could pass when the artifact digest matched. The lead
reproduced it through the actual finish CLI in a disposable fixture. The new
six-test suite initially failed (one actual replay acceptance and missing context
parameters), then passed after a local hardening extension to the vendored copy.
The installed helper is unchanged; provenance and the intentional local delta
are documented in scripts/control_plane/vendor/README.md.

Final packets now carry run_id at the top level, every PASS criterion and
integrated result, and final critic. Observation started_at/ended_at must be zoned,
ordered, no earlier than creation/latest explicit rebaseline, and no later than
acceptance. The final critic must start after its evidence finishes. Final-state
validation recomputes these checks even when an attacker also rebuilds the event
hash chain. Metadata cannot authenticate a fabricated measurement or actor: raw
artifact inspection and host-observed independent acceptance remain required.

The 22-test local observation preceded its new ledger artifact reference. The
second peer subsequently found two incomplete fixture baselines (20/22 passed).
Fixture setup now copies the exact existing files referenced by the verification
ledger, rejecting missing or symlinked sources, instead of another incomplete
hard-coded list. Full verification must follow metadata updates as well as code.
The complete suite was rerun after metadata updates. A third fresh I1 review
accepted the bounded recovery, including194 negative packets at actual finish
and persisted validation, current positive cases and existing safeguards. The
lead confirmed the whole-artifact sentinel. See review-controls-peer-3.md for
scope and limitations; this is not product or full AAA approval. No fixture
approval was written into the real run, and no product criterion was promoted.
