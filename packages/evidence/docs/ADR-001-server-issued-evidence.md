# ADR-001: Server-issued, scope-bound evidence

## Status

Accepted for the bounded Evidence lane.

## Context

The retrieval package already returns evidence-shaped dictionaries and the
Professor contracts serialize selected provenance. Those surfaces do not by
themselves prevent a downstream model from inventing an identifier, mixing
tenant scopes, or citing a changed excerpt under an old identifier.

## Decision

`rick-evidence` owns immutable `Evidence`, `EvidenceBundle`, and
`EvidenceValidator` contracts. The server creates identifiers by hashing the
complete provenance and excerpt payload. A bundle has exactly one tenant,
workspace, and collection scope and derives its citation map from the issued
evidence IDs. Citation resolution is registry-based and fails closed.

The package accepts an authorized scope from its caller but does not perform
authorization. Existing retrieval and Professor callers remain unchanged;
future composition can add an adapter that enriches retrieval output with the
authoritative document version before issuing evidence.

The lexical claim check is intentionally a screening signal. It makes no
claim about entailment, truth, probability, or any medical or other regulated
domain conclusion. Such claims require a separately approved policy and
review path.

## Consequences

Changed provenance produces a new server ID, forged citation IDs cannot
resolve, and mixed-scope bundles are rejected before reasoning. Callers must
provide a document version and checksum and must retain the internal scope
until authorization-aware projection. This package does not provide storage,
retention, authorization, semantic entailment, or production deployment.
