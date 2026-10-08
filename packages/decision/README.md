# `packages/decision`

`rick-decision` is the explicit synchronous policy boundary after retrieval
and evidence validation. It has no HTTP, provider, database, model, or API
caller dependency. `DecisionLayer.decide()` returns exactly one of:

`ANSWER`, `RETRIEVE_AGAIN`, `ASK_FOR_CLARIFICATION`, `ABSTAIN`, or `ESCALATE`.

The evaluation order is fixed and deterministic. Input or evidence integrity
failures and human review requirements escalate first. A risk level is
answerable only when it is present in the policy allowlist, whose default is
`LOW` only; unknown, medium, high, and critical risk therefore require review
unless an explicitly approved policy changes that allowlist. Ambiguous or
unknown intent asks for clarification. Missing or weak evidence can request
one bounded retrieval retry, then abstains. Missing or weak provider signals
abstain. Numeric signals are bounded indicators, not calibrated probabilities.
Strict runtime policies also require an observed `CitationSupportMetrics` PASS
with citation precision, recall, completeness, unsupported-claim rate and,
when `require_faithfulness` is enabled, an explicit reviewed faithfulness
signal; the legacy scalar is only a structural citation-registry signal.

```python
from rick_decision import (
    DecisionAction,
    DecisionInput,
    DecisionLayer,
    DomainRisk,
    IntentClarity,
    UserIntent,
)

decision = DecisionLayer().decide(
    DecisionInput(
        evidence_bundle=bundle,
        evidence_count=len(bundle.evidence),
        retrieval_quality=0.91,
        citation_support=0.90,
        provider_confidence_signal=0.88,
        domain_risk=DomainRisk.LOW,
        user_intent=UserIntent(intent_code="source_question", clarity=IntentClarity.CLEAR),
    )
)
assert decision.action is DecisionAction.ANSWER
```

When `cited_evidence_ids` is supplied, the layer resolves them against the
server-generated `EvidenceBundle.citation_map` and abstains on an unknown or
duplicate identifier. The integration seam is an existing retrieval or
Professor composition point that creates the bundle with `rick-evidence`,
supplies observed metrics when available, and invokes this package before
committing to a response. A bundle alone is never treated as claim-level
support by a strict gate.

## Server-owned request classification

The canonical API uses `NonClinicalRequestPolicy` before making this decision.
`rick-nonclinical-request-v1` recognizes a finite set of standalone English and
Portuguese product-help questions: document upload, collections, citations and
upload retry/status. It applies whole-question matching, with normalization for
case, whitespace, accents and a final question mark. It does not infer safety
from a retrieval score or accept a request-supplied risk label.

```python
from rick_decision import NonClinicalRequestPolicy, classify_request

classification = classify_request(
    NonClinicalRequestPolicy(), "How do I upload a document?"
)
assert classification.allows_answer
assert classification.policy_version == "rick-nonclinical-request-v1"
assert not classify_request(None, "How do I upload a document?").allows_answer
```

Clinical and injection indicators require review. Unknown or contextual requests
remain unreviewed; short recognized product topics ask for clarification, while
known unsupported creative requests abstain. Prior conversation content cannot
silently give a standalone allow rule broader clinical meaning. Version one
deliberately does not authorize multi-turn/domain reasoning.

Classification grants eligibility only. ANSWER additionally requires a canonical
source authority and the existing evidence thresholds. A weak eligible query gets
at most one additional retrieval using policy-owned topic terms, preserving the
original classification and ACL. A failed retry abstains. Structural citation
validation and live source re-resolution are separate from semantic support;
`NOT_EVALUATED` is never a claim of clinical or semantic approval.

The API's final publication callback rereads every prompt source and rejects
changed document/chunk identity, version, checksum, content, scope or publication
status, including archived collections. An optional server-supplied authorization
refresher can narrow grants at delivery; without it, metadata explicitly records
`request_scope_and_collection` rather than live user-grant validation. Cancellation,
incomplete provider termination and exhausted budgets never approve a final answer.

See [the Q24 design and integration contract](../../docs/architecture/domain-decision-policy-2026-09-24.md).
D04 domain acceptance, live-provider evaluation, atomic persistence authorization
and independent release review remain outside this technical policy.
