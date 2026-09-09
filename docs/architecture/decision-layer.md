# Intelligence decision layer

The decision layer is the single policy point between retrieval/evidence and
answer generation. It returns one of:

```text
ANSWER
RETRIEVE_AGAIN
ASK_FOR_CLARIFICATION
ABSTAIN
ESCALATE
```

Inputs include retrieval quality, evidence count, citation support, provider
signals, domain risk and policy. The layer is deterministic for equal inputs,
has finite limits and carries a reason code safe for logs. Controllers should
route the decision; they should not duplicate the policy.

Clinical decision support is deliberately separated from general knowledge.
Risk classes are `LOW`, `MEDIUM`, `HIGH` and `CRITICAL`; higher risk requires
stronger evidence and a more conservative decision. No diagnosis or treatment
claim is created by this contract, and no unvalidated clinical corpus is
treated as a golden set.
