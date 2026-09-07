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
