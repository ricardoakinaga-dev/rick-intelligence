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

The provider HTTP, SSE and structured-tool paths decode JSON through a finite,
duplicate-free boundary. Non-finite constants and duplicate object keys fail
closed before chat/embedding response projection, streaming delta extraction,
model-error classification or tool-argument validation. This is local provider
contract evidence; a live endpoint, approved corpus and runtime budget remain
separate promotion requirements.
