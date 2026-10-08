# Recoverable CI control inputs (AUD03-21)

On a new checkout, install the declared web parser dependency and restore the
versioned inputs before running the read-only validation:

```sh
make web-install
make control-inputs-restore
make validate
```

All three targets honor the root `PYTHON` override. The restore itself uses only
the Python standard library and the checked-in, unchanged controller helpers.
`make bootstrap` also depends on `control-inputs-restore`, then runs its existing
runtime/dependency setup. `make validate` depends on `control-inputs-check`:
validation never repairs a missing input. Workflows invoking the Python
control-plane checker directly must perform this restore first. This bounded
change does not edit workflows or the runner's direct CI orchestration.

## Versioned input contract

`v2/manifest.json` lists every member, original path, restored path, size and
SHA256; it also records the compressed `v2/inputs.tar.xz` digest. The archive
contains 1,293 real files (114,443,788 bytes uncompressed), including the complete
original legacy-controller and review-history archives and their unchanged
manifests. Explicit directory references include their real evidence, such as
Playwright results; no placeholder evidence is manufactured. Only the
allowlisted, explicitly inventoried paths are read by the snapshot creator.
No environment or credential files are included.

`original-inventory.json` preserves the supplied audit inventory exactly.
`requirements.json` extends it with 245 references exposed by the first clean
projection's real controller failure. These include historical ignored logs,
seven specific `.runtime/phase-3` envelopes, prior `artifacts/rec-m0-v3`/`v4`
browser evidence and the historical `docs/progress/release-evidence.json`.
They retain their original commit/time bindings and verdicts. Their restoration
does not make them current runtime or promotion evidence. Commit/freshness
validators still apply when those envelopes are consumed by runtime/release gates.

The bundle is a historical recovery input, while the tracked `.agent` controller
is the current canonical task state. The four original revision-380 controller
files are preserved as `snapshot/.agent/*` members, never written over current
canonical state. Their original status is `IN_PROGRESS`, verification `PARTIAL`.
The six original Gauntlet state/bar/history/artifact/progress/view files are
preserved as `snapshot/.gauntlet/*` members. Its `ACTIVE` status, stale evidence,
original absolute root and authenticated history remain untouched. Inspect them
with `tar -xOf docs/ci/control-inputs/v2/inputs.tar.xz snapshot/.agent/state.json`
(or another explicit member); they are not an approval of a new checkout.

## Portable state and conflict policy

The old Gauntlet run binds `/home/ricardo/rick-intelligence`. Copying it into a
new root would correctly fail the vendored validator. Recovery instead invokes
the authentic `gauntlet_state.py init` in the new checkout, using the exact
predecessor goal and canonical frozen bar. It creates a new run ID bound to the
actual root and Git HEAD: `ACTIVE`/`DECOMPOSE`, zero rounds, `MISSING` evidence,
no latest verification and no stop/verdict. The initializer's empty new history
and artifact ledgers represent zero events; historical ledgers remain in the
bundle. Default capabilities conservatively describe this single-process
bootstrap, without borrowing the prior host's agents. Time/token budgets remain
unbounded and the original retry policy and acceptance criteria are preserved.

Derived views are regenerated in memory from current canonical `.agent` state
using `expected_views`, and written only if absent. Preflight checks the full
archive, every member, original manifest checksums, existing targets and views
before restoring any file. Existing bytes that differ, symlinks, incomplete
Gauntlet directories, foreign roots/goals, corrupt/missing archive members or
missing bundle files cause failure. A valid existing local run is checked
without mutation or reinitialization. Restored files use exclusive creation.
The initializer requires an empty `.gauntlet`; an existing *identical derived*
`state.md` is temporarily removed and recreated, never replacing differing
state. No authoritative state file is rewritten.

Repeating restore on a matching checkout is idempotent. `--check` is read-only
and rejects missing restored files, including evidence, even if the archive can
recover them. Recovery writes are not an atomic multi-directory transaction:
an interrupted input copy may leave an incomplete new file which a rerun will
reject rather than overwrite. Inspect/remove only the identified incomplete
new file in a disposable checkout, then retry. If Gauntlet initialization is
interrupted, use its existing explicit transaction recovery command; this
bootstrap does not silently reset a partial run. No concurrent-writer isolation
is claimed; run bootstrap before agents or other state writers.

## Versioning, trust and verification

The reviewed Git revision is the trust anchor for the manifest and archive.
These are checksums for integrity, not signatures against an attacker who can
replace the whole repository. Changing frozen historical inputs requires a new
bundle version and review; never recompute original archive manifest checksums
to accept changed history. Snapshot a new version from an explicit inventory:

```sh
python3 docs/ci/snapshot_control_inputs.py --root "$PWD" \
  --inventory docs/ci/control-inputs/requirements.json \
  --output docs/ci/control-inputs/v3
```

The snapshot command refuses an existing output directory. Extending the
current canonical controller with new ignored evidence also requires an
explicit inventory/version update. The restore has no external download or
fallback to a previous host. Missing inputs remain failures.

Reproduce the positive and negative acceptance evidence in a new synthetic Git
projection (commits are made only inside that temporary projection):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 docs/ci/prove_control_restore.py \
  --evidence /tmp/ci-restore-proof \
  --python /path/to/declared/testenv/bin/python
PYTHONDONTWRITEBYTECODE=1 /path/to/declared/testenv/bin/python -m pytest \
  -q -p no:cacheprovider scripts/state_of_art/tests/test_ci_control_restore.py
```

The proof copies candidate Git-listed files except the current AUD03 campaign's
generated evidence outputs (which contain concurrently-created disposable test
repositories), refuses sensitive paths, asserts
ignored control directories are absent, installs dependencies with `npm ci`
inside the projection, and preserves baseline failure, restore, successful
validation, clean-worktree check, idempotence, corrupt/missing source and corrupt/
missing restored-input failures. It records exact copied-file hashes and
commands. Builder evidence lives under
`docs/reports/evidence/implementation-aud03-2026-10-03/ci-restore/`.
Independent critique is required after the builder handoff; builder tests and
structural validation do not grant promotion authority.
