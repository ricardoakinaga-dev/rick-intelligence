# Phase 1.1 Independent Review

## Review identity

- Reviewer: `Newton` (`01a05836-a4d6-7b53-9d1a-f9117ad2d184`)
- Mode: fresh, read-only review with `fork_context: false`
- Scope: Phase 1.1 root skeleton, migration-safety contracts, commands,
  boundaries, regression evidence, and documentation
- Files edited by reviewer: none
- Review status: Round 1 `INCOMPLETE`; a focused re-review is required after
  the remediation recorded below

## Round 1 — 2026-08-31

The reviewer independently inspected the candidate before the clean-checkout
remediation. Results were:

| Criterion | Result | Independent observation |
| --- | --- | --- |
| PH11-REPO | `FAIL` | The local validator required nested `.git` metadata for every child, but the Phase 1.1 workflow performs only the root checkout. A clean GitHub checkout therefore could not pass the validator even though the root Git tree contains the child snapshots. |
| PH11-TOOLCHAIN | `PASS` | Root pins, lockfile policy, and environment contract were present and coherent. |
| PH11-COMMANDS | `PASS` | Required Make targets and guarded runtime paths were inspected; the reviewer did not execute the component test lanes. |
| PH11-BOUNDARIES | `PASS` | Boundary JSON, placeholder structure, and the validator’s forbidden-pattern test were present. |
| PH11-REGRESSION | `BLOCKED` | The reviewer did not independently rerun the component suites and therefore did not re-endorse the existing regression ledger. |
| PH11-DOCS | `PASS` with minor gap | The phase and legacy scope were accurately described; the JSON `source_of_truth` field and Markdown explanation were inconsistent. |
| PH11-REVIEW | `PASS` | The review was read-only, criterion-based, and identified a concrete critical gap. |

### Largest gap

The critical gap was a clean-checkout identity mismatch: the validator
conflated locally available independent child Git metadata with the tracked
root snapshot. The workflow does not and should not reconstruct ignored nested
repositories. Until this was corrected, the root CI contract was not
reproducible from a clean checkout.

### Commands and observations performed by the reviewer

- `make validate` — passed in the current workspace;
- Phase 1.1 boundary unit tests — 2 passed;
- JSON/JSONL parsing and workflow YAML parsing — passed;
- `git diff --check` — passed;
- root HEAD/remote comparison — `HEAD == origin/main` at the observed root;
- read-only child repository status and identity inspection — performed;
- component test execution and guarded-command execution — not performed by
  the reviewer.

### Independent decision

`INCOMPLETE`: reject as a verified/promotion candidate until the clean-checkout
validator/workflow gap is fixed and the affected evidence is rerun. This
decision did not change the historical Phase 0.6 `BLOCKED / NOT_PROMOTED`
gate.

## Lead remediation

The lead added
[`preserved-components.json`](../architecture/preserved-components.json),
which makes the preservation modes explicit:

- a clean root checkout must contain the tracked child snapshot;
- a workspace with nested `.git` metadata additionally validates each
  independent child HEAD;
- absence of nested `.git` metadata is no longer treated as loss of the root
  snapshot identity.

The validator now checks the root tree with `git ls-tree` in snapshot-only
mode, retains independent HEAD validation when local metadata is present, and
prints both observations. The boundary contract’s JSON file is now the
normative source of truth, and the unit suite includes the clean-checkout
policy. The lead executed `make validate`, the boundary tests, and `make ci`
after the remediation. A temporary clean-checkout fixture with the nested
child `.git` metadata and ignored dependency directories omitted also passed
the validator in snapshot-only mode; the focused independent re-review remains
part of Round 2.

## Round 2 — 2026-08-31

The same independent reviewer rechecked the remediation without editing files.
Round 1's clean-checkout gap was closed: the validator now accepts a child
without nested `.git` only when `git ls-tree` finds its tracked root snapshot.
The reviewer also confirmed the three snapshots and the three local child
HEADs independently.

A new high-severity PH11-REPO coverage gap remained: when nested `.git`
metadata exists, the validator checked the child HEAD but skipped the required
root snapshot assertion. This contradicted the manifest policy and the
documentation, even though the current snapshots were present. The reviewer
also identified that the report's boundary-test count was stale at the time of
inspection.

| Criterion | Result | Independent observation |
| --- | --- | --- |
| PH11-REPO | `FAIL` | Clean mode was fixed, but local nested-Git mode did not enforce the root snapshot. |
| PH11-TOOLCHAIN | `PASS` | Pins and installation policy remained coherent. |
| PH11-COMMANDS | `PASS` | `make help`, `make validate`, and runner validation passed. |
| PH11-BOUNDARIES | `PASS` | Normative JSON contract, zero future source files, and boundary tests passed. |
| PH11-REGRESSION | `BLOCKED` | Component suites were intentionally not rerun by this focused review. |
| PH11-DOCS | `PASS` with minor stale evidence | Scope was accurate; the test-count wording needed the current count. |
| PH11-REVIEW | `PASS` | The fresh review identified a second concrete material gap. |

### Round 2 commands and observations

- `make validate` — exit 0;
- `python3 -m unittest scripts/phase11/test_check_skeleton.py` — exit 0;
- `make help` and `python3 scripts/phase11/runner.py validate` — exit 0;
- YAML parsing of both workflows and JSON/JSONL parsing — passed;
- root `git status`, `git diff --check`, protected-path inspection, and local
  child status/HEAD inspection — completed;
- no component suites, services, or runtime extraction — performed.

### Round 2 decision

`INCOMPLETE`: fix the validator so the root snapshot is required in both
nested-Git and snapshot-only modes, update the affected count/evidence, and
obtain another focused independent re-review. Phase 1.2 remains unauthorized.

## Lead remediation after Round 2

The validator now performs the `git ls-tree` root snapshot assertion for every
preserved component before branching into nested-HEAD or snapshot-only mode.
The unit suite adds a mocked assertion that the snapshot rule is independent
of nested metadata. The current local validator, 4-test boundary suite,
`make ci`, and a fresh snapshot-only fixture all pass. Round 3 independent
confirmation is pending.

## Round 3 — 2026-08-31

The same fresh read-only reviewer rechecked the dual-mode correction. Round 1's
clean-checkout defect and Round 2's nested-Git/root-snapshot coverage defect
were both judged closed. The reviewer confirmed that the validator checks
`git ls-tree` for every component, then optionally validates nested child HEADs;
the local run reported all three child HEADs and the snapshot-only simulation
reported all three components under `PROTECTED_CHILD_SNAPSHOT_ONLY`.

| Criterion | Result | Independent observation |
| --- | --- | --- |
| PH11-REPO | `PASS` | Both nested-Git and snapshot-only preservation paths were confirmed. |
| PH11-TOOLCHAIN | `PASS` | Toolchain, environment, JSON, and documentation contracts remained coherent. |
| PH11-COMMANDS | `PASS` | `make help`, `make validate`, and runner validation passed. |
| PH11-BOUNDARIES | `PASS` | Four boundary tests passed and no future source files were scanned. |
| PH11-REGRESSION | `PASS` with limitation | Existing focused/CI evidence remained current; the reviewer did not rerun component suites. |
| PH11-DOCS | `PASS` | The report's current boundary-test count is 4; the separate 3-test entry is explicitly historical. |
| PH11-REVIEW | `PASS` | Fresh read-only Round 3 review completed. |

### Round 3 commands and observations

- `make validate` — exit 0 with all three local child HEADs;
- `python3 -m unittest scripts/phase11/test_check_skeleton.py` — exit 0;
- snapshot-only validator simulation — exit 0;
- `make help` and `python3 scripts/phase11/runner.py validate` — exit 0;
- YAML, JSON/JSONL, `git ls-tree`, `git diff --check`, protected-path, and
  independent child status/HEAD inspections — passed;
- no component suites, services, or runtime extraction — performed by the
  reviewer.

### Round 3 decision

`PASS`: no remaining material Phase 1.1 gap was identified. The historical
Phase 0.6 corpus blocker remains separate, and Phase 1.2/runtime extraction
remains unauthorized.

## Append-only revalidation of earlier review streams — 2026-08-31

The first two rounds remain preserved as `PARTIAL` observations. After the
Round 3 fixes and confirmation, the exact Round 1 and Round 2 review scopes
were revalidated as current `PASS` observations so the append-only ledger can
close those historical streams without erasing their findings. This
revalidation adds no new implementation change and does not alter the final
Phase 1.1 gate or the historical Phase 0.6 decision.
