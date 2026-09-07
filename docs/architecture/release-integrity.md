# Release integrity gate

`state-of-art-quality.yml` is the small offline gate for release evidence. It
does not install packages, start Docker, call a provider, or contact a live
service. The implementation is the stdlib-only
[`release_integrity.py`](../../scripts/state_of_art/release_integrity.py)
script and its focused `unittest` suite.

## Required decision

The gate runs these explicit commands and records each result in JSON:

```text
git diff --check
make validate
```

It also takes a worktree snapshot before and after the commands. The worktree
sentinel fails if the gate mutates the checkout. The workflow passes
`--require-clean`, so a release checkout that starts dirty also fails. Local
diagnosis may omit that flag when an already-dirty shared workspace must be
observed without being mistaken for a gate mutation.

The workflow requires `docs/progress/release-evidence.json`. A missing file is
`NOT_RUN`, and because it is mandatory the process exits non-zero. This is
intentional: a release cannot pass by silently omitting its evidence.

## Evidence freshness

Evidence is current only when its JSON object contains both:

- a complete 40-character `HEAD` (or the lower-case `head` alias); and
- the 64-character checkout fingerprint for the same checkout.

The recommended manifest shape is:

```json
{
  "schema_version": "release-evidence.v1",
  "HEAD": "<40 lowercase hexadecimal characters>",
  "fingerprint": {
    "checkout": "sha256:<64 lowercase hexadecimal characters>"
  },
  "status": "PASS",
  "checks": [
    {
      "id": "check-id",
      "required": true,
      "classification": "PASS",
      "command": ["python3", "-m", "unittest"]
    }
  ]
}
```

`HEAD` or fingerprint mismatch is classified as `FAIL` (stale evidence).
Missing evidence or a mandatory `NOT_RUN` is classified as `NOT_RUN`; both
are blocking. A mandatory `FAIL`, `STALE`, `BLOCKED`, `INVALID`, or `UNKNOWN`
is also blocking. Optional entries may be `NOT_RUN`, but optional failure and
stale results are never promoted to PASS.

Freshness is identity-based, not wall-clock-based. A recent file from another
checkout is stale, while an older file with a matching `HEAD`, matching
fingerprint, and rerunnable command record is eligible for this gate.

## Checkout fingerprint

The JSON output contains `HEAD`, worktree status, a status fingerprint, and a
checkout fingerprint. The checkout digest covers the commit/tree identity,
branch, Git index, tracked diff, and the paths/content digests of untracked
non-ignored files. Raw paths, diffs, command output, credentials, and document
content are not emitted into the artifact.

The top-level `classification`, `status`, `commands`, `criteria`, and
`fingerprint` fields are stable JSON data. The process exits `0` only for
overall `PASS`; both `FAIL` and blocking `NOT_RUN` exit non-zero.

## Production limitation

The output always includes:

```json
{
  "live_production": {
    "classification": "NOT_RUN",
    "required": false,
    "claim": false
  }
}
```

This gate therefore makes no live-production, Docker, provider, database,
latency, availability, or deployment claim. A future release process must
provide separately authorized current evidence for those criteria and mark
them mandatory before they can participate in a promotion decision.

The workflow uses top-level default-deny permissions (`permissions: {}`), a
job-level `contents: read` only for checkout, a ten-minute timeout, and no
external dependency installation.
