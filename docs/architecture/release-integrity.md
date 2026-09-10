# Release integrity gate

`state-of-art-quality.yml` is the small offline gate for release evidence. It
does not start Docker, call a provider, or contact a live service. It installs
only the pinned Ed25519 verifier dependency from
[`scripts/state_of_art/requirements.txt`](../../scripts/state_of_art/requirements.txt).
The implementation is dependency-light
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
      "tree_sha": "<same tree SHA>",
      "artifact_hash": "<same artifact_set_sha256>",
      "command": ["git", "diff", "--check"],
      "procedure": "run the gate procedure against the exact checkout",
      "environment": "ci",
      "timestamp": "2026-09-09T12:00:00+00:00",
      "exit_status": 0,
      "result": "PASS",
      "status": "PASS",
      "limitations": [],
      "reviewer": {
        "reviewer_id": "automated-release-integrity",
        "kind": "automated",
        "name": "release-integrity-generator",
        "independent": false
      },
      "evidence_path": [
        {"path": "README.md", "sha256": "<same file hash>", "description": "state truth"}
      ],
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
Referenced paths must be regular files reached without traversing symlink
components, so a later path swap cannot change the bytes behind a reference.
`HEAD`, tree, checkout fingerprint, artifact hash or any referenced byte
mismatch is classified as `FAIL` (stale/wrong artifact evidence). Missing
evidence or a mandatory `NOT_RUN` is classified as `NOT_RUN`; both are
blocking. A mandatory `FAIL`, `STALE`, `BLOCKED_EXTERNAL` or `INVALID` is also
blocking. No status is upgraded by a reviewer label, timestamp or previous
run.

Freshness requires both the exact checkout identity and a current observation
window. A recent file from another checkout is stale, while an older file with
a matching `HEAD` can still be rejected once its `generated_at` or gate
timestamp exceeds the 24-hour evidence window. The generator records the
execution timestamp, not the commit timestamp, so a long-lived branch cannot
accidentally emit already-stale release evidence.

## Promotion packet sealing

`make triple-aaa-verify` is an observation runner, not a signer. It never
self-seals a candidate and never treats `--seal-reference` by itself as
authority. A promotion attempt must provide `--sealed-packet <path>` pointing
to an externally retained packet created with
`scripts/state_of_art/packet_seal.py`, plus `--trust-store <path>` (or
`RICK_PROMOTION_TRUST_STORE`) containing the approved Ed25519 public keys. The
packet must contain the exact lane observations and clean candidate
`commit_sha`, `tree_sha` and checkout fingerprint, plus:

```json
{
  "sealed": true,
  "critical_high_findings": 0,
  "final_decision": "GO",
  "decision_authority": {
    "reviewer_id": "independent-release-authority",
    "authorized": true,
    "independent": true
  }
}
```

An external authority creates the seal with an Ed25519 private key and a
stable `key_id`; the trust store maps that id to the corresponding base64 raw
public key. The digest and signature cover the packet body, candidate,
observations, decision authority, immutable reference and all seal metadata.
The verifier recomputes the digest, checks the signature against the explicit
trust store, rejects mutation, binds it to the current run and checkout, and
requires the seal signer to match the authorized independent reviewer. Missing,
malformed, self-promoted, untrusted or mismatched packets remain
non-promotable. The immutable artifact reference must still be retained by an
authorized artifact system.

## Shared disposable-runtime preflight

The Phase 3 runtime adapters also require one common lab attestation before a
service-specific `PASS` can become runtime evidence. `make up` starts only the
owned local Compose project, invalidates any previous attestation, and then
records `.runtime/phase-3/preflight.json` only after all eleven canonical
services (`postgres`, `redis`, `qdrant`, `object-store`, `jaeger`,
`otel-collector`, `metrics`, `api`, `worker`, `worker-b` and `web`) are reported
by `docker compose ps` as running and healthy. It additionally probes the
loopback API readiness endpoint and the loopback Web login endpoint.

The preflight binds a generated `run_id`, exact commit/tree/checkout
fingerprint, clean worktree, deterministic Compose project, redacted rendered
configuration hash, the exact Compose-file hash, service readiness records,
endpoint status, disposable scope and a bounded expiry window. Rendered
Compose output is hashed in memory after redaction and is never persisted as
evidence. The API and Web probes are fixed to the canonical loopback paths
and ports and do not follow redirects. The preflight must exist before a gate
starts and have the same bytes after it finishes; a gate cannot create or
replace its own attestation. `make down` invalidates the attestation before
teardown, so an old healthy lab cannot be reused accidentally.

Every Phase 3 adapter carries the preflight path/hash/run metadata in its
envelope and refuses to emit `PASS` or `production_safe=true` when the
attestation is missing, stale, changed, dirty, wrong-project, incomplete or
not bound to the current checkout. The release-integrity and Phase 3 matrix
validators repeat this check, including the artifact hash, Compose-file hash,
canonical target and same-run identity across all successful envelopes, rather
than trusting the adapter's self-report. A blocked or failed gate remains
blocked or failed; the preflight never upgrades it.

All Phase 3 evidence, release-envelope, packet and offline-evaluation readers
share a strict JSON boundary: UTF-8 is decoded explicitly, input is capped at
1 MiB before projection, non-finite constants are rejected, and duplicate
object keys fail closed. This prevents an evidence producer from changing a
status, candidate binding or gate field by relying on the last duplicate key;
the boundary is local integrity protection and does not create runtime or
independent-review evidence.

## Checkout fingerprint

The JSON output contains `HEAD`, worktree status, a status fingerprint, and a
checkout fingerprint. The checkout digest covers the commit/tree identity,
branch, Git index, tracked diff, and the paths/content digests of untracked
non-ignored files. Raw paths, diffs, command output, credentials, and document
content are not emitted into the gate output. The generated manifest is
ignored and excluded from the untracked fingerprint so the binding is
deterministic rather than self-referential.

The top-level `classification`, `status`, `commands`, `criteria`, and
`fingerprint` fields are stable JSON data. `procedure` is mandatory so an
evidence record cannot claim a result without naming what was executed. The
process exits `0` only for overall `PASS`, `2` for `BLOCKED_EXTERNAL`, and `1`
for a failure or missing/invalid packet.

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
