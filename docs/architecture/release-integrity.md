# Release integrity gate

`state-of-art-quality.yml` is the small offline gate for release evidence. It
does not install packages, start Docker, call a provider, or contact a live
service. The implementation is the stdlib-only
[`release_integrity.py`](../../scripts/state_of_art/release_integrity.py)
script, the typed model in
[`release_manifest.py`](../../scripts/state_of_art/release_manifest.py), the
deterministic generator in
[`generate_release_evidence.py`](../../scripts/state_of_art/generate_release_evidence.py)
and their focused `unittest` suites.

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

The workflow generates `docs/progress/release-evidence.json` from the exact
checkout before invoking the gate. The path is intentionally ignored by Git:
generated evidence must not be committed into the tree whose fingerprint it
describes, because that would create a self-referential hash. A missing file is
still `NOT_RUN`, and because it is mandatory the process exits non-zero. This
is intentional: a release cannot pass by silently omitting its evidence.

## Evidence freshness

Evidence is current only when its JSON object contains both:

- a complete commit/tree binding and the 64-character checkout fingerprint for
  the same checkout; and
- content hashes for every artifact and evidence path referenced by a gate.

The strict v2 manifest shape is:

```json
{
  "schema_version": "state-of-art-release-evidence.v2",
  "manifest_id": "release-<commit-prefix>",
  "generated_at": "2026-09-09T12:00:00+00:00",
  "status": "PASS",
  "commit_binding": {
    "commit_sha": "<40 lowercase hexadecimal characters>",
    "tree_sha": "<40 lowercase hexadecimal characters>",
    "checkout_fingerprint": "<64 lowercase hexadecimal characters>",
    "artifact_set_sha256": "<64 lowercase hexadecimal characters>",
    "clean_worktree": true
  },
  "artifacts": [
    {
      "path": "README.md",
      "role": "release-source",
      "sha256": "<64 lowercase hexadecimal characters>"
    }
  ],
  "gates": [
    {
      "gate_id": "release-integrity",
      "commit_sha": "<same commit SHA>",
      "artifact_hash": "<same artifact_set_sha256>",
      "command": ["git", "diff", "--check"],
      "environment": "ci",
      "timestamp": "2026-09-09T12:00:00+00:00",
      "result": "PASS",
      "limitations": [],
      "reviewer": {
        "reviewer_id": "automated-release-integrity",
        "kind": "automated",
        "name": "release-integrity-generator",
        "independent": false
      },
      "evidence_paths": [
        {"path": "README.md", "sha256": "<same file hash>", "description": "state truth"}
      ]
    }
  ],
  "reviewers": [
    {
      "reviewer_id": "automated-release-integrity",
      "kind": "automated",
      "name": "release-integrity-generator",
      "independent": false
    }
  ],
  "limitations": []
}
```

The implementation names these typed records explicitly:
`ReleaseEvidenceManifest`, `ArtifactFingerprint`, `GateResult`, `EvidenceRef`,
`ReviewerRef` and `CommitBinding`. Every gate is bound to the same commit and
artifact-set hash; every referenced artifact/evidence path is rehashed from
the checkout. The manifest itself cannot be an artifact or evidence reference.
`HEAD`, tree, checkout fingerprint, artifact hash or any referenced byte
mismatch is classified as `FAIL` (stale/wrong artifact evidence). Missing
evidence or a mandatory `NOT_RUN` is classified as `NOT_RUN`; both are
blocking. A mandatory `FAIL`, `STALE`, `BLOCKED_EXTERNAL` or `INVALID` is also
blocking. No status is upgraded by a reviewer label, timestamp or previous
run.

Freshness is identity-based, not wall-clock-based. A recent file from another
checkout is stale, while an older file with a matching `HEAD`, matching
fingerprint, and rerunnable command record is eligible for this gate.

## Checkout fingerprint

The JSON output contains `HEAD`, worktree status, a status fingerprint, and a
checkout fingerprint. The checkout digest covers the commit/tree identity,
branch, Git index, tracked diff, and the paths/content digests of untracked
non-ignored files. Raw paths, diffs, command output, credentials, and document
content are not emitted into the gate output. The generated manifest is
ignored and excluded from the untracked fingerprint so the binding is
deterministic rather than self-referential.

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
external dependency installation. Generation is not itself a pass condition;
it records `BLOCKED_EXTERNAL`/`NOT_RUN` honestly, and the verifier rejects any
mandatory non-`PASS` gate.
