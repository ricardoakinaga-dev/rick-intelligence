# Provider resilience boundary

`rick_providers.ResilientProvider` is an explicit wrapper for callers that
need local prompt/embedding budgets and a finite circuit breaker around the
typed async provider contract. It retains no prompt, response, URL, secret, or
exception cause. Transient provider failures increment a bounded counter; once
the threshold is reached, calls fail closed as a safe `unavailable` provider
error until the cooldown expires.

The wrapper does not claim a distributed breaker or external telemetry. A
production deployment must supply shared metrics/alerting and choose whether
to wrap the live adapter at its composition root. The underlying HTTP client
still owns timeout, retry, response-size and redaction policy.

Admission is fail-closed (A16). `production_safe` is `True` only when the wrapped
port exposes a live `health_check` probe or declares `production_safe = True`
itself — an owned, named decision; a test port is never production-safe. A port
with neither is reported `production_safe = False`. `health_check()` follows the
same rule: it delegates to the port's probe and returns `False` when there is no
probe, instead of falling back to `readiness_check()` — circuit state is a local
signal, not reachability. `readiness_check()` keeps its cheap, no-I/O meaning for
callers that explicitly want it. The official OpenAI-compatible and Anthropic
adapters carry their own `/models` probe, so the canonical composition stays
green; the composition-level admission test covers the registered `provider`
readiness check, not only the wrapper.

The provider HTTP, SSE and structured-tool paths decode JSON through a finite,
duplicate-free boundary. Non-finite constants and duplicate object keys fail
closed before chat/embedding response projection, streaming delta extraction,
model-error classification or tool-argument validation. This is local provider
contract evidence; a live endpoint, approved corpus and runtime budget remain
separate promotion requirements.

The Phase 11 provider runtime gate uses the same strict decoder for JSON-mode
content, complete function-tool arguments, reassembled streaming JSON and
reassembled streaming tool arguments. Duplicate keys, non-finite values,
invalid UTF-8 and inputs above the shared byte ceiling fail closed before the
gate can record a contract pass. This strengthens local gate integrity only;
it does not establish live provider, corpus or budget authority.
