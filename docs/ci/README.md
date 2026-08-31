# Phase 0.6 CI contract

The root workflow is
[`phase-0.6.yml`](../../.github/workflows/phase-0.6.yml). It preserves the
three component boundaries and separates quick pull-request checks from checks
that need disposable Qdrant/Redis services or a browser.

## Pinned execution contract

| Tool or service | Declaration |
| --- | --- |
| Runner | `ubuntu-24.04` |
| Python | `3.12.3` |
| Node.js | `22.19.0` |
| Qdrant | `qdrant/qdrant:v1.7.4` |
| Redis | `redis:7.0.15-alpine` |
| Gitleaks | `ghcr.io/gitleaks/gitleaks:v8.30.1` |
| Python audit tool | `pip-audit==2.9.0` |
| Python install mode | `python -m pip install --no-cache-dir -r cvg-master-rag-v2/src/requirements.txt` |
| Node install mode | `npm ci --ignore-scripts --no-audit --no-fund` from the component lockfile |

The versions match the preserved Phase 0.5 characterization. A version change
requires updating the workflow and this table together with fresh evidence.
The workflow does not inject a provider credential and does not claim that its
deterministic provider doubles are live-provider evidence.

## Lanes and check names

The following job `name` values are the exact GitHub check names:

| Lane | Check name | Role |
| --- | --- | --- |
| fast | `fast / secret scan` | Existing CVG scanner plus pinned Gitleaks over the checkout |
| fast | `fast / control-plane` | Plan/ledger/Git pointer validation and whitespace check |
| fast | `fast / Locker deployment boundary` | Private-network deployment lint and Python syntax checks |
| fast | `fast / CVG contract-security` | Phase 0.5/0.6 contract, RBAC, session, and security tests |
| fast | `fast / Professor tests-build` | Professor unit/contract tests, emitted provider-artifact validation and TypeScript build |
| fast | `fast / Locker tests` | Locker unit tests and JavaScript syntax check |
| fast | `fast / frontend lint-build` | Frontend ESLint and production build |
| fast | `fast / dependency audit` | `pip-audit` and `npm audit` for all preserved manifests |
| integration | `integration / CVG Python-Qdrant contract fixture` | Real disposable Qdrant/Redis plus non-leakage test and deterministic contract fixture |
| integration | `integration / Locker Redis boundary` | Real disposable Redis, Locker process, and black-box lock contract |
| integration | `integration / frontend smoke` | Real browser smoke with a live disposable Qdrant backend |
| historical | `legacy / historical baseline (waived if unavailable)` | Runs the full legacy suite only when the authorized classification artifact exists; otherwise reports an explicit waiver |
| evidence | `evidence / live provider (unavailable)` | Records that no approved endpoint/credential is available; makes no provider request |

The fast and integration rows are the required branch-protection set for
ordinary code changes. Branch protection cannot be configured from this bounded
workspace task, so configure these exact names manually on the protected `main`
branch. Do not use a shortened job ID or a different display name.

The historical and live-provider checks remain visible but are not promotion
evidence when unavailable. Their current state is intentional:

- `docs/baselines/phase-0.6-legacy-test-classification.md` is present and
  classifies the frozen 19 failures and 6 errors. The lane therefore runs the
  full suite without `continue-on-error`; current missing-corpus entries remain
  a visible failing result until an owner-authorized permanent waiver or the
  approved fixtures are supplied. It does not use xfail or skips to turn the
  known `364 passed, 19 failed, 14 skipped, 6 errors` baseline into a pass.
  If a future checkout genuinely lacks the artifact, the lane reports
  `NOT AVAILABLE (explicit waiver)` and keeps the task open. Presence of the
  artifact is not itself a waiver.
- No live provider endpoint or credential is authorized in this workflow. The
  live-provider job writes `NOT RUN` and the deterministic fixture is labelled
  as plumbing-only. A future live lane must use a separately approved,
  secret-safe harness before becoming required.

An actual failure in the available historical lane fails the job. The
branch-protection set should be updated only after the corresponding promotion
authority accepts the current evidence.

## Local checks

Dependency-free deployment and control checks can be run from the workspace
root:

```bash
python3 scripts/phase06/check_locker_boundary.py
python3 docs/ci/check_control_plane.py
```

The second command reports a pre-existing dirty worktree without rejecting it,
which keeps it usable while independent component work is in progress. CI uses
`--require-clean --require-remote` and also requires `HEAD == origin/main` on a
push to `main`.

The integration lanes require a runner with Docker-backed GitHub Actions
services. The current local environment has no Docker executable, so local
absence of those services is reported as unavailable rather than simulated.
