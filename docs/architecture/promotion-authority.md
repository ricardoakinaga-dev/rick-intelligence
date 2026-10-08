# Promotion authority — external gates

Status: `REFERENCE`. This document makes explicit, for each fail-closed external
lane in [`triple_aaa_verify.py`](../../scripts/state_of_art/triple_aaa_verify.py),
what evidence and which human authority are required to move it from
`BLOCKED_EXTERNAL` to `PASS`. It does **not** define a command that fabricates
that evidence. Any lane with `command=None` is a human authority boundary by
design; adding an automated producer that returns success would be a
promotion-gaming regression.

Each lane below is keyed to the same `lane_id` used by `triple_aaa_verify.py`.

---

## lab-readiness

- **Authority:** a runtime operator with access to an approved disposable
  Docker daemon (isolated from user services, with known teardown ownership).
- **Evidence accepted:** a same-run `docker compose up` of the canonical
  Compose file that reaches every mandatory service `healthy`/`ready`
  (migration, object-store/bootstrap, Qdrant collection, API, worker A/B),
  with bounded redacted logs and a teardown snapshot proving zero leftover
  disposable resources.
- **Not accepted:** `make compose-static` success, host-service adoption, or a
  readiness claim from a daemon that cannot prove disposable ownership.

## independent-reviews

- **Authority:** reviewer(s) distinct from the implementer, with fresh
  context, bound to the exact candidate (commit/tree/fingerprint).
- **Evidence accepted:** per-scope review verdicts that hash the reviewed
  packet and access no path outside its allowlist; a reviewer cannot
  self-approve their own implementation.
- **Not accepted:** an automated critic result, a review of a different
  snapshot, or a self-review recorded as independent.

## production-runtime

- **Authority:** an operator/infrastructure authority that provides the
  production-shaped runtime (TLS, secret manager, immutable images) and the
  approved disposable PostgreSQL/Redis/Qdrant/object-store/provider graph.
- **Evidence accepted:** live migration, fencing, crash-matrix, tenant
  isolation and golden-path observations bound to the same candidate.
- **Not accepted:** hermetic tests, local loopback services, or any projection
  without the approved external deployment authority.

## sealed-packet

- **Authority:** the release engineer who seals the packet with the configured
  signing secret, only after every other mandatory lane passes.
- **Evidence accepted:** a valid `packet_seal.py` signature over the current
  evidence inventory with the correct body schema and byte-exact archived
  prompt/matrix references.
- **Not accepted:** a seal produced before the current evidence exists, or a
  seal over a missing/stale/tampered packet.

## final-go-no-go

- **Authority:** the human release authority named by D07.
- **Evidence accepted:** an explicit, dated, traceable Go decision over the
  sealed packet and the 26-dimension scorecard at or above the required bar,
  with zero unresolved Critical/High risks.
- **Not accepted:** a Go inferred from exit code zero, a note that "nothing
  failed", or an automated classification.

---

## Why these lanes must stay `command=None`

`lab-readiness`, `independent-reviews`, `production-runtime`, `sealed-packet`
and `final-go-no-go` are authority boundaries. Wiring a local command to each
would (a) let a process approve itself, (b) let a test stand in for a human
decision, or (c) let a hermetic run stand in for a production runtime — all of
which the promotion engine deliberately rejects. This document therefore
**explicits** the process instead of **connecting** an executor, which is the
fail-closed resolution of finding A24-09. A future, separately-authorized
producer may connect a lane only if it consumes real evidence from the named
authority and still fails closed on absence, staleness, tampering or wrong
candidate.

See [`release-readiness.md`](../operations/release-readiness.md) for the
operator runbook and [`phase-3-triple-aaa-closure.md`](../plans/phase-3-triple-aaa-closure.md)
for the promotion sequence.
