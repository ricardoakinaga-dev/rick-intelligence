# CI contracts

The canonical root CI is
[`quality.yml`](../../.github/workflows/quality.yml), with release-integrity
checks in [`state-of-art-quality.yml`](../../.github/workflows/state-of-art-quality.yml).
Current toolchain declarations are documented in
[`docs/architecture/toolchain.md`](../architecture/toolchain.md).
For a new checkout, follow the versioned
[control-input recovery contract](control-inputs/README.md): install the declared
web dependencies, run `make control-inputs-restore`, then `make validate`.
Validation is read-only and missing or corrupt inputs remain failures.
Historical snapshots retain their original checksums and authority; restored
or mutated artifacts do not constitute approval or current promotion evidence.

## Historical Phase 0.6 / 1.1 contract

The sections below preserve the contract recorded during those phases. Their
tool versions, lane names, branch-protection proposal and environment observations
are historical; the canonical workflows and recovery contract above govern
the current candidate.

The historical root workflow was
`.github/workflows/phase-0.6.yml`. It preserved the three component boundaries
and separated quick pull-request checks from checks that need disposable
Qdrant/Redis services or a browser. AUD07-04 deleted that workflow together
with the components it guarded (AUD07-02); it remains reachable in git history
and is no longer listed among the required control inputs.

The historical additive foundation workflow is
[`phase-1.1.yml`](../../.github/workflows/phase-1.1.yml). It installs the
preserved lockfiles, runs the root `make ci` contract, and then rechecks the
control-plane pointers. That foundation contract did not start a root compose
stack or move runtime code. At that stage, `docs/ci/check_control_plane.py`
accepted the Phase 0.6 or Phase 1.1 plan and kept the Phase 0.6 final gate
present and `BLOCKED` while Phase 1.1 was active. The current checker requires
the v2 canonical controller and verifies its preserved history and review state;
the old plan branches are not a fallback for missing current controls.

## Historical pinned execution contract

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

The versions match the preserved Phase 0.5 characterization of the retired
Phase 0.6 workflow; they are recorded here as history, not as live
configuration. A version change to a live lane requires updating its workflow
and this table together with fresh evidence.
The workflow does not inject a provider credential and does not claim that its
deterministic provider doubles are live-provider evidence.

## Historical lanes and check names

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

The fast and integration rows were the required branch-protection set proposed
for ordinary code changes in that phase. Branch protection was not configured
by the bounded workspace task. Current required checks must be reconciled with
the canonical workflow and the repository's actual protection configuration;
this historical table does not establish that configuration.

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

## Historical local checks

The phase-specific local commands were recorded as follows. Current clean-checkout
validation requires the recovery procedure linked above before checking controls:

```bash
python3 scripts/phase06/check_locker_boundary.py
python3 docs/ci/check_control_plane.py
```

The second command reports a pre-existing dirty worktree without rejecting it,
which keeps it usable while independent component work is in progress. CI uses
`--require-clean --require-remote` and also requires `HEAD == origin/main` on a
push to `main`.

The historical integration lanes required a runner with Docker-backed GitHub
Actions services. At the time this contract was recorded, that local environment
had no Docker executable and reported services as unavailable. The current
workstation has Docker; availability of a specific service and authority to run
it must be established by that lane's actual execution evidence. The old
environment observation is not a current limitation or an approval.
