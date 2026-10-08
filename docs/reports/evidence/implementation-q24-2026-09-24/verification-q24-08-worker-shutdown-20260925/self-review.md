# Integrator self-review — local worker telemetry shutdown

This is a separate self-review pass, not independent approval.

The actual script entrypoint wraps reusable main() in a process-owned finally
block. That block observes the already-imported observability package and does
not import optional dependencies during exit. Worker cleanup precedes the drain
on successful startup paths, so diagnostics emitted during cleanup are included.
Startup failure preserves its existing SystemExit(78); this slice drains startup
diagnostics but does not add worker cleanup to that pre-existing failure path.

The drain receives exactly 2.0 seconds. Queue draining and worker joins share the
existing package deadline. A permanently blocked daemon callback can remain
active until process termination; no durable delivery is claimed. Fixed stderr
messages preserve worker outcomes and do not print collector exception text.
The new contract regression checks return codes 0 and 1 and SystemExit(78)
against successful, incomplete and exception-raising drains. An isolated
in-memory mutation to 3.0 seconds is rejected in all nine combinations.

Imported main() retains shared-process ownership: its subprocess regression
successfully emits after main() returns. Package shutdown of a never-used lane
does not create threads. This no-op assumes producers are stopped; it is not a
global prohibition on future lazy initialization. The architecture note states
that boundary and leaves the API fallback/process-owner behavior unchanged.

Observed evidence: all seven original process scenarios failed without the
hook; the first focused run passed 34 tests; the final Docker/package run passed
46; the worker/API health/telemetry regression passed 129 with one upstream
TestClient deprecation warning. Counts describe their command scopes and are
not added to prior overlapping suite totals.

No blocking defect found against local C1–C6. The original independent review's
LOW timing-slack finding is addressed by the exact argument/outcome regression.
Final independent review is recorded separately. Container stop grace, live
collectors, distributed flow, API process-owner shutdown, capacity and promotion
remain outside this evidence. No installation, migration, deployment or paid
provider was contacted by this slice.
