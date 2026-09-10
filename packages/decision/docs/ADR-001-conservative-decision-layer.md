# ADR-001: Explicit conservative DecisionLayer

## Status

Accepted for the bounded Decision lane.

## Context

Grounded response behavior must not be spread across controllers, providers,
or prompt templates. Retrieval quality, evidence count, citation support,
provider signals, user intent, policy, and domain risk have different failure
modes and need an auditable precedence order.

## Decision

`rick-decision` defines a versioned `DecisionInput`, `Decision`, and
`DecisionLayer` contract. The implementation is synchronous, deterministic,
side-effect free, and returns exactly five actions. Integrity and risk gates
precede answer-oriented thresholds. The default risk allowlist contains only
`LOW`; other levels require explicit policy approval and review. Evidence
shortfalls may consume a bounded retry budget, after which the result is
`ABSTAIN`. Citation registry failures and missing provider signals never
produce `ANSWER`.

The package consumes a server-issued `EvidenceBundle` and can revalidate its
scope against the request scope. When `require_citation_support_metrics` is
enabled, it also requires a PASS `CitationSupportMetrics` observation with
bounded precision, recall, completeness and unsupported-claim rate values. An
approved evaluator may also provide a bounded reviewed faithfulness value;
`require_faithfulness` makes that fifth signal mandatory and
`min_faithfulness` applies its threshold. An optional policy source pin binds
the observation to the approved evaluator.
Missing or inconclusive observations cannot produce `ANSWER`. The legacy
scalar remains for structural compatibility but is not claim-level support.
The package does not authorize users, retrieve data, generate text, classify a
regulated domain, or make medical claims.

## Consequences

Callers get one stable policy outcome and safe generic messages, with no
hidden I/O or clock dependence. They must supply an authorized scope upstream,
use the Evidence package for provenance, and explicitly configure any risk
level that may be answered. Production composition, provider calibration,
semantic entailment, and human escalation operations remain outside this
package.
