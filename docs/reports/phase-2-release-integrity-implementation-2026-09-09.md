# Phase 2.7.1 — Release integrity implementation review

**Date:** 2026-09-09
**Candidate base:** `75131a081a6880a8a8c6f4db9a676834fca74410` plus the current
working-tree implementation
**Decision:** `IMPLEMENTED / LOCAL_VERIFIED / PROMOTION BLOCKED`

## Delivered contract

The release workflow now has a typed, dependency-free v2 manifest with:

- `ReleaseEvidenceManifest`;
- `ArtifactFingerprint` and deterministic artifact-set hashing;
- `GateResult` with commit, artifact, command, environment, timestamp,
  limitations, reviewer and evidence references;
- `EvidenceRef`, `ReviewerRef` and `CommitBinding`;
- byte-level rehashing of every referenced artifact/evidence file;
- rejection of self-reference, wrong commit/tree/fingerprint, wrong artifact
  hash, missing evidence, stale/invalid result, `BLOCKED_EXTERNAL` and
  `NOT_RUN` mandatory gates.

The generated file is ignored by Git and is created by
`scripts/state_of_art/generate_release_evidence.py` immediately before the CI
gate. This keeps the evidence deterministic and avoids a self-referential
checkout hash. The generator records blocked or unavailable gates honestly;
it is not allowed to turn generation into a PASS.

The root workflow now runs the generator before
`release_integrity.py`. `make release-evidence` exposes the same local
operation. The `make dev` runner also maps its lifecycle action to Compose
`up` instead of issuing the invalid `docker compose dev` command.

## Verification packet

| Check | Result | Meaning |
| --- | --- | --- |
| `make validate` | `PASS` | Root boundaries and control-plane records remain structurally valid. |
| `python3 -m pytest -q -p no:cacheprovider scripts/state_of_art/tests/test_release_integrity.py scripts/state_of_art/tests/test_release_manifest.py` | `12 passed` | Legacy fail-closed behavior plus typed good/bad fixtures, hash drift, blocked gate and commit drift. |
| `python3 -m py_compile ...` | `PASS` | New generator, manifest model and gate compile under the repository Python contract. |
| `make release-evidence` | `PASS` command / manifest `FAIL` | Generation completed and recorded the dirty checkout and blocked gates without masking them. |
| `python3 scripts/state_of_art/release_integrity.py --evidence docs/progress/release-evidence.json` | `FAIL` / exit 1 | Correct fail-closed result: current checkout is dirty and required gates are not all `PASS`. |
| `make dev` | `FAIL` at required environment interpolation | The invalid Compose subcommand is gone; no service was started because required image/environment values and Docker access are unavailable. |
| `git diff --check` | `PASS` | No whitespace error in the current candidate. |

## Promotion boundary

This slice does not claim runtime, production, `STATE_OF_ART`, `AAA` or
`TRIPLE_AAA`. The generated manifest currently contains blocked external gates
for PostgreSQL, multi-worker, Redis, Qdrant, object storage, ingestion E2E,
observability, recovery, performance, web/visual and independent promotion
review. That is the required truthful result until those gates execute against
the exact candidate.

The next slice is **Phase 2.7.2 — Canonical Root Runtime Composition**:
complete the environment-backed Compose lifecycle, add the declared telemetry
collector/metrics boundary, and produce a disposable stack smoke packet without
weakening required configuration or using unsafe fallbacks.
