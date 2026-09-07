# Root Professor, provider and lease boundaries

Phase 1.5 establishes the first end-to-end root path without modifying the
preserved CVG, Professor or Locker trees:

```text
authenticated HTTP caller
  -> server-side authorization context
  -> RetrievalApplicationService
  -> evidence gate in packages/professor
  -> typed provider boundary
  -> canonical ChatResponse / compatibility adapter
```

The lease boundary wraps the Professor operation:

```text
owner-bound acquire
  -> retrieval and (when evidence is approved) generation
  -> periodic renewal while work is active
  -> exactly-one owner-bound release
```

## Contracts

`packages/contracts` owns the versioned DTOs. Provider results carry a
correlation ID, bounded content and optional strictly typed usage counters.
Embedding results require finite values and an exact configured dimension.
Lease results contain exactly one operation outcome (`acquired`, `renewed` or
`released`) and no owner token in serialized errors. Professor responses reuse
the canonical `EvidenceDto` provenance shape instead of creating a second
citation schema.

All new provider, lease and Professor models forbid unknown fields. Public
errors contain only a stable code, operation, correlation ID, attempt count and
status where applicable. They do not contain response bodies, URLs, credentials,
raw prompts, exception causes or hidden reasoning.

## Provider boundary

`packages/providers` is the only root package that knows the OpenAI-compatible
HTTP endpoints. It provides:

- one async client for chat completions and embeddings;
- bounded streaming response consumption (`1 MiB` maximum);
- exact requested/returned model matching;
- finite exact-dimension embedding validation;
- bounded exponential retry for timeout, unavailable, rate-limit and 5xx
  classes only;
- one correlation ID across attempts and cancellation propagation;
- an explicit deterministic provider for test/dev only.

The deterministic provider is selected by the factory only in a test/dev/local
environment. Production settings reject it. Hermetic `httpx.MockTransport`
tests prove the failure taxonomy; they are not live-provider or quality
evidence.

## Lease boundary

`packages/locking` provides an owner-generating `LeaseClient`, an atomic
in-memory backend, and a bounded HTTP adapter for the preserved Locker
protocol. A `LeaseHandle` captures its owner and will renew or release only
that exact owner. Expiry, wrong-owner operations and contention return safe
negative outcomes; transport, timeout, malformed response and cancellation
fail with typed `LeaseError` values.

The Professor API adapter uses low-level owner-aware calls because the
orchestrator creates the operation owner. When the injected lease exposes
renewal, a cancellable heartbeat runs at one third of the configured TTL. A
failed renewal cancels generation, returns a safe `lease_lost` stage and still
attempts owner-bound release. Test doubles without renewal remain supported for
small pure unit tests.

No live Redis or Locker deployment is asserted by this phase. Production
rollout requires a private, authenticated service boundary and process-level
tests against the pinned Redis version before enabling it.

## Professor evidence policy

The Professor receives a validated `RetrievalContext`, not caller-provided
authority. Retrieval evidence is rechecked for:

- matching workspace;
- an allowed collection (unless the already-authorized context explicitly
  carries a bounded wildcard);
- safe document, chunk and evidence IDs;
- nonempty bounded text;
- bounded citation provenance and scores.

No evidence and weak evidence stop before provider invocation. Approved
evidence is copied into a bounded prompt using explicit `SOURCE <id>` markers.
Only markers that match the selected evidence become public citations. Unknown,
forged or malformed citation markers produce `CITATION_INVALID` and no cited
answer.

## API rollout and rollback

`apps/api` selects one backend for both `/api/v1/chat` and
`/v1/chat/completions`:

| Setting | Use | Rollback/guard |
| --- | --- | --- |
| `RICK_API_CHAT_BACKEND=stub` | hermetic kernel and local plumbing | never accepted as accidental production fallback |
| `RICK_API_CHAT_BACKEND=professor` | root retrieval + evidence-gated provider path | requires a provider and a lease service in production |
| `RICK_API_USE_LEGACY=1` | explicit preserved adapter rollback | legacy behavior remains separately characterized |

The compatibility API key is constant-time checked and server-bound to one
finite workspace and collection set. Request fields can narrow that scope but
cannot widen it; wildcard compatibility collections are rejected by settings
validation.

## Current boundary and deferred work

The local path seeds one deterministic document only when the environment is
not production. The following are intentionally outside the Phase 1.5 claim:

- live OpenAI-compatible provider calls and credentials;
- live Qdrant or Redis/Locker verification;
- durable document state and restart-safe worker jobs;
- real upload-to-index publication;
- a canonical web application and browser E2E against `apps/api`;
- production deployment, gateway authentication and SLO evidence.

These become separate gates. A green hermetic suite proves the root contracts
and wiring, not those operational capabilities.
