# Readiness deadlines

`evaluate_checks` has a default one-second total wait budget. Integrators can
pass a finite positive `timeout_seconds` to that helper. Checks start sequentially
in registration order and share one monotonic deadline; a slow early check can
leave later checks unexecuted. Those checks report `check_timeout`. Saturated
admission reports `check_capacity`. Exceptions report `check_failed`, without
adapter exception classes, messages, tracebacks or provider payloads.

Required failures produce readiness HTTP 503. Custom successful evaluations
retain their reported optional policy; timeouts and exceptions use the caller's
`default_required` (true by default), since no result policy is available.
Selected runtime component wrappers enforce required policy after async results
resolve as well as for synchronous results. Admin health retains its existing
HTTP 200 diagnostic contract while reporting `not_ready` in its body.

Admission limits are process-wide, including across request loops: at most four
executing synchronous hooks in daemon threads and eight unfinished check tasks.
There is no waiting work queue. An expired or cancelled request cancels its check
task without awaiting cancellation acknowledgement. A cancellation-resistant
async hook continues to occupy one of the eight slots until it finishes; repeated
probes eventually fail admission instead of accumulating tasks. A blocked sync
hook occupies one of the four thread slots until it returns. Capacity is shared
across dependencies, so stuck adapters can make unrelated checks unavailable.

Sync hooks execute off the event loop, outside its default executor. These daemon
threads are never joined by readiness or interpreter shutdown; no thread is
forcibly terminated. Late coroutine results from abandoned sync factories are
closed. Async hooks and awaitables returned by sync factories are awaited on the
caller's event loop, preserving async client loop affinity. Synchronous factories
must be safe to invoke on a worker thread.

Adapters remain responsible for native socket/client deadlines, thread safety,
cooperative cancellation, and releasing their own resources. The response budget
bounds waiting, plus scheduler and result-serialization overhead; it cannot
preempt async code that blocks the loop or native code that holds the GIL.
Cancellation-resistant async hooks can still delay a host's own loop teardown
if that host waits for all tasks. Async adapters must cooperate with shutdown;
only synchronous blocked work has the daemon-thread shutdown guarantee. Work
spawned internally by an adapter is outside these admission limits.

Health and policy flags are strict booleans. Malformed ok values fail health;
malformed required values fail health and are treated as required. Valid explicit
optional policy remains optional even when health is malformed. No arbitrary
object truthiness is invoked. Invalid flags use fixed detail invalid_check_state;
an invalid default_required helper argument raises ValueError before any check
starts. See readiness-login-state.md for the scoped correction and outstanding
application-provider isolation limitation.
