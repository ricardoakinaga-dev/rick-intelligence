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
feeds citation support from its validator, and invokes this package before
committing to a response. This lane intentionally does not modify those
callers or the API.
