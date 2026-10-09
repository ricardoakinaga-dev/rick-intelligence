# Root toolchain contract

Status: `CURRENT`, observed 2026-08-31; reconciled for component
retirement on 2026-10-07 (AUD07-04).

The machine-readable source for the root pins is [`toolchain.json`](../../toolchain.json).
The `services` values govern the current development and staging Compose images;
changing them requires an explicit matching update and evidence.

| Layer | Pin | Evidence | Scope |
| --- | --- | --- | --- |
| Python | `3.12.3` | `docs/baselines/environment-2026-08-31.json`, `.github/workflows/quality.yml` | canonical API, worker and package tooling |
| Node.js | `22.19.0` | `docs/baselines/environment-2026-08-31.json`, `.github/workflows/quality.yml` | `apps/web` tooling |
| npm | `10.9.3` | `docs/baselines/environment-2026-08-31.json` | lockfile installation |
| Qdrant | `1.12.5` | `docker-compose.dev.yml`, `docker-compose.staging.yml` | disposable integration service |
| Redis | `7.4` | `docker-compose.dev.yml`, `docker-compose.staging.yml` | disposable integration service |
| Qdrant Python client | `1.7.3` | `requirements/phase13.lock` | compatibility with the pinned server |

## Retired Phase 0.6 CI images

The Phase 0.6 workflow (`.github/workflows/phase-0.6.yml`) and the three
components it guarded (`cvg-master-rag-v2`, `rick-professor`,
`modulo-redis-locker`) were retired by AUD07-02 and AUD07-04. Its historical
image pins (Qdrant `v1.7.4`, Redis `7.0.15-alpine`) are therefore no longer
declared in `toolchain.json`: there is no checked-in file left to compare them
against. They remain readable in git history. `make validate` runs
`scripts/phase11/check_toolchain.py`, which rejects a mismatched current Compose
image or a duplicated lab version. The checker reads files and does not start
containers.

## Current lab

The `canonical_lab_services` block in [`toolchain.json`](../../toolchain.json)
records the image references declared by `docker-compose.dev.yml` and
`docker-compose.staging.yml` for the disposable integration lab. Qdrant and
Redis values must agree with `services`.

All Node applications retain their own `package-lock.json`; the root does not
invent an npm workspace before package ownership and contracts exist. Python
dependencies are hash-locked in `requirements/test.lock` and
`requirements/runtime.lock`. Changing a pin requires updating `toolchain.json`,
the CI contract, and a fresh reproducibility record together.

## Installation policy

`make bootstrap` runs `scripts/phase05/bootstrap-runtime.sh`, which installs
`requirements/test.lock` with `--require-hashes` and verifies it with
`python -m pip check`, then runs
`npm ci --ignore-scripts --no-audit --no-fund` in `apps/web`. The command is
idempotent with respect to tracked source and lockfiles; it may update ignored
dependency/runtime directories. No production service is started and no secret
is read into a report.
