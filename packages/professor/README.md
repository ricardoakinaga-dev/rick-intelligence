# `packages/professor`

The root Professor lane is an async, dependency-injected orchestration package.
It accepts a validated `rick_contracts.professor.ProfessorRequest`, serializes
its validated `RetrievalContext` for an injected retrieval callable, and passes
only bounded, workspace/collection-scoped evidence to an injected typed chat
provider returning `ChatCompletionResult`.

```python
from rick_professor import ProfessorOrchestrator

response = await ProfessorOrchestrator(
    retrieval=engine.retrieve,
    chat_provider=provider,
).run(request)
```

The gate is deterministic: no valid scoped evidence returns `NO_EVIDENCE`,
scoped evidence below the configured confidence threshold returns
`WEAK_EVIDENCE`, and approved evidence is the only path that invokes chat.
Evidence and generated answers are hard-bounded. Provider output may cite only
retrieved evidence with exact `[cite:<evidence_id>]` markers; an unknown marker
returns `CITATION_INVALID` and no citations. Provider or retrieval failures are
translated to the safe `GENERATION_FAILED` response without exposing causes.

An optional injected owner-checked lease manager covers retrieval and
generation and is released in a `finally` seam, including cancellation. When
the manager exposes `renew`, the orchestrator runs a cancellable heartbeat at
one third of the configured TTL; a lost renewal cancels in-flight generation
and returns a safe `lease_lost` failure stage before owner-bound cleanup.

Limitations: this package does not perform HTTP, authentication, authorization,
retrieval, persistence, streaming, or live OpenAI/Qdrant/Redis calls. The
caller must provide an already validated request and trusted dependency
implementations. It does not prove factual correctness beyond retrieval scope,
confidence gating, and citation provenance.
