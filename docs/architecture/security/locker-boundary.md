# Redis Locker security boundary

**Decision:** Redis Locker is an internal-only deployment component. It is a
small HTTP adapter for owner-safe Redis lock operations; it is not an
application identity provider and it does not currently authenticate HTTP
callers.

This decision closes the `PH06-LOCKER` deployment-boundary requirement from the
[Phase 0.6 promotion plan](../../../.agent/plans/phase-0.6-promotion-closure.md).
It applies to the preserved component boundary at
[`modulo-redis-locker/`](../../../modulo-redis-locker/) and to every deployment
example that runs it.

## Observed implementation and evidence status

The following are facts about the current checkout:

- `server.js` exposes `GET /healthz`, `POST /lock`, `POST /unlock`, and
  `POST /renew`.
- Unlock and renewal compare the caller-supplied `lock_value` inside Redis
  scripts before changing the key. This is owner safety, not HTTP
  authentication or authorization.
- The preserved async HTTP adapter streams responses through a 64 KiB byte
  ceiling and accepts success JSON only when it is finite, syntactically valid,
  non-recursive and free of duplicate keys; ambiguous or non-finite bodies
  fail closed as a redacted internal error before a lease result is returned.
- `Dockerfile` declares `EXPOSE 3000`. That is image metadata; it does not
  publish a host port. A deployment still becomes public if it adds a Compose
  `ports` mapping, host networking, an ingress, or a reverse-proxy route.
- The current application listener may accept connections on the container's
  service interface. The deployment network, not a loopback bind, is the
  required isolation mechanism for container-to-container traffic.
- The current deployment examples are guarded by
  [`check_locker_boundary.py`](../../../scripts/phase06/check_locker_boundary.py),
  which is run locally and in root CI.

Production gateway configuration, network policy, and live deployment
verification are **UNKNOWN/NOT_RUN** in this checkout. This document is a
security decision and threat model; it is not evidence that a production
network is already configured correctly.

## Assets and actors

Assets to protect:

- active lock keys and owner values, whose corruption can duplicate or stall
  work;
- Redis connection details and any data reachable through the configured Redis
  instance;
- availability of Professor's serialized/contended work;
- health and operational signals, without leaking credentials or raw URLs.

Relevant actors:

- the Rick Professor application, as the intended caller;
- an internal health monitor/orchestrator, for `/healthz` only;
- another workload or compromised process on the application network;
- an external or unauthenticated client, which must not reach Locker directly;
- a deployment/platform operator, who owns the private network and gateway
  configuration.

## Trust and network boundary

```text
untrusted client
      │
      ▼
authenticated application gateway / public Professor API
      │  application identity and authorization
      ▼
private application network (no host publication for Locker)
      ├── rick-professor ──HTTP──> redis-locker:3000
      │                              │
      │                              └──Redis──> redis:6379
      └── other explicitly allowed internal dependencies
```

The preserved Compose example uses a named Docker network with
`internal: true`. Locker is attached only to that private network and uses
`expose: 3000` as an intra-network documentation hint; it has no `ports`
mapping. The Professor-to-Locker URL uses the private service name
`http://redis-locker:3000`, never a host address.

The boundary is therefore:

1. the public gateway/Professor boundary authenticates and authorizes the
   application caller;
2. the private network limits which processes can route to Locker;
3. Locker validates request shape and enforces owner comparison for unlock and
   renewal;
4. Redis remains behind the same private service boundary and must not be
   exposed with the Locker endpoint.

## Threat model and controls

| Threat | Impact | Current/required control | Residual status |
| --- | --- | --- | --- |
| A public client reaches `/lock`, `/unlock`, or `/renew` | Lock acquisition abuse, denial of work, or release attempts | No host port, ingress, reverse-proxy route, host network, or `0.0.0.0` binding in examples; CI lint is fail-closed | Depends on deployment fidelity; live production evidence unavailable |
| A reachable caller guesses or reuses an owner value | Unauthorized release/renewal of that lock | Redis-side compare-delete/compare-expire scripts require the current owner value | Any caller that can reach the unauthenticated HTTP service remains trusted by the network |
| A compromised peer joins the private network | Direct lock manipulation or availability attack | Isolate the network; allow only Professor and health/orchestration paths; do not treat `lock_value` as identity | High-value residual risk until network policy/gateway is independently verified |
| Redis is reachable from an untrusted network | Read/write of lock state and possible credential exposure | Keep Redis on the private service network; use deployment-managed Redis credentials and TLS/auth policy where supported | Deployment-specific configuration is UNKNOWN here |
| A reverse proxy or port mapping is added during deployment | The unauthenticated service becomes internet-reachable | Static checker rejects `ports`, host/shared network modes, proxy labels, and `0.0.0.0`; required CI check | Cannot detect an out-of-band production change after deployment |
| Malformed or oversized request/response body | Errors, resource pressure, or unexpected Redis commands/results | Zod request schemas reject missing/invalid lock fields; the client bounds response bytes and rejects malformed, non-finite or duplicate-key success JSON; retain bounded body/parser policy at the gateway | Body-size/rate policy is deployment follow-up |
| Locker or Redis is unavailable | Professor work is rejected or retries/stalls | Healthcheck, bounded application behavior, TTLs, and owner-safe cleanup tests | Multi-process recovery and production SLO evidence are not run |

The boundary deliberately does not claim that network reachability is
equivalent to user authorization. It is a compensating control for the current
component contract, not a substitute for authentication.

## Exposure policy

### Allowed

- private service-to-service HTTP from Professor to `redis-locker:3000`;
- internal health probing from an explicitly trusted orchestrator;
- ephemeral loopback-only test processes used by local characterization scripts;
- an authenticated gateway as a future controlled entry point, if it is the
  only route and it authenticates the calling application.

### Forbidden

- any Compose `ports` entry for the Locker service, including an explicit
  `0.0.0.0:<host-port>:3000` mapping;
- Docker `network_mode: host` or a shared service network namespace;
- a public DNS name, load-balancer listener, ingress, reverse-proxy label, or
  direct internet route to Locker;
- publishing Redis credentials, raw Redis URLs, owner values, or request
  bodies to logs, examples, or CI artifacts;
- presenting `lock_value` as a bearer token, user credential, or proof of
  application identity;
- adding a host port to “make debugging easier.” Use an authenticated tunnel
  or an in-network diagnostic container instead.

The source examples are:

- [`rick-professor/deploy/docker-compose.example.yml`](../../../rick-professor/deploy/docker-compose.example.yml)
- [`modulo-redis-locker/README.md`](../../../modulo-redis-locker/README.md)

## Application-auth expectations

The current Locker contract intentionally has no application-level HTTP
credential. Therefore:

- the gateway or private application network must be the enforcement point for
  caller authentication and authorization;
- the gateway must authenticate the Professor service identity, allow only the
  required Locker routes, apply request-size/rate/timeout limits, and prevent a
  user-facing route from bypassing Professor;
- `/healthz` may be probed by a trusted internal monitor but must not be
  published as a public liveness endpoint;
- errors and access logs must be neutral and must not include Redis URLs,
  credentials, or owner values;
- if an environment cannot provide a private network and an authenticated
  gateway, it cannot deploy this version of Locker safely.

Professor's user/session authorization remains its own boundary. A user being
authorized to use Professor does not authorize direct calls to Locker; direct
calls are not part of the public API.

## Future extraction guidance

If Locker is ever extracted as an independently addressable service, the
current network-only control must not be carried forward as if it were
authentication. Before publishing or granting cross-network access, require a
separate reviewed design and current evidence for:

1. mTLS or a rotated service token with an explicit caller identity and
   fail-closed validation;
2. route-level authorization for lock acquisition, renewal, release, and
   health; least-privilege service accounts; and replay/rotation handling;
3. TLS termination, private DNS/service discovery, network policy, rate and
   body limits, timeouts, metrics, audit events, and redacted diagnostics;
4. a versioned HTTP contract with consumer fixtures covering success,
   unavailable, malformed, wrong-owner, expiry, duplicate, timeout, and
   concurrent cases;
5. Redis credential isolation/rotation, backup and recovery expectations, and
   an operational rollback plan;
6. independent security review and a live deployment check proving that no
   alternate public route exists.

The extraction decision is **PROPOSED**, not authorized by this task. Phase 1
consolidation and production deployment validation remain out of scope.

## Revalidation triggers

Re-run the boundary lint and repeat security review when any of the following
changes:

- a Compose/Helm/Kubernetes/sidecar deployment is added or changed;
- a gateway, ingress, service mesh, DNS, or load-balancer route changes;
- the Locker listener, endpoint contract, or authentication model changes;
- Redis topology, credentials, or network policy changes;
- the service is moved outside the preserved private application network.

Local guard command:

```bash
python3 scripts/phase06/check_locker_boundary.py
```
