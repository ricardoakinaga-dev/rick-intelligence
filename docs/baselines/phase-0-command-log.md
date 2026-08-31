# Phase 0 command log

Observed on 2026-08-31 UTC in the workspace root. The initial command table was
captured before the required additive CVG runtime-state/execution-log overlay;
the log records exact reproduction status and does not convert unavailable
checks into passes. The replay recipes below were added during the final
evidence reconciliation.

| Scope | Command | Result |
| --- | --- | --- |
| child repository state | `git -C <child> status --short --branch` for all three children | all clean `main...origin/main` at baseline capture; later CVG docs-only overlay is recorded in the report |
| CVG backend | `python3 -m pytest -q src/tests` | blocked: `/usr/bin/python3: No module named pytest` |
| CVG root Phase 0 test | `python3 -m pytest -q tests/test_phase0.py` | blocked: pytest unavailable |
| Professor install | `npm ci --no-audit --no-fund` | pass, 194 packages |
| Professor build | `OPENAI_API_KEY=phase0-test-key npm run build` | pass |
| Professor declared tests | `OPENAI_API_KEY=phase0-test-key npm test` | fail before tests: `ERR_REQUIRE_CYCLE_MODULE` under Node 22 `--loader ts-node/esm` |
| Professor alternate test | `OPENAI_API_KEY=phase0-test-key node -r ts-node/register --test src/core/processor.test.ts` | four assertions passed, imported Redis handles kept the process open; interrupted after assertions; not the declared script result |
| Locker install | `npm ci --no-audit --no-fund` | pass, 80 packages |
| Locker syntax | `node --check server.js` | pass |
| Locker package scripts | `npm run` | only `start`; no test script |
| Frontend install | `npm ci --no-audit --no-fund` | blocked: package/lockfile out of sync; missing Playwright entries and version mismatches |
| Frontend lint/build | `npm run lint`, `npm run build` | not run after blocked install; initial missing-binary checks failed |
| CVG secret scan | `python3 src/scripts/scan_secrets.py` | pass: no high-signal secrets found |
| Docker | `docker --version` | unavailable: command not found |
| Qdrant | `curl -fsS --max-time 2 http://127.0.0.1:6333/readyz` | unavailable: connection refused |
| default Redis | `redis-cli -h 127.0.0.1 -p 6379 ping` | `PONG`; not used or modified |
| isolated Redis/Locker | `redis-server` on 6397 plus Locker on 3317, then `tests/phase0/redis-locker-characterization.mjs` | pass; both processes stopped and ports verified closed |

Historical CVG documents mention earlier live Qdrant and test counts, but their
timestamps and runtime paths predate this checkout's current environment; those
are linked in the architecture/report as stale evidence only.

## Reproduction recipes for saved performance values

The Professor benchmark is deterministic at the dependency boundary and requires
the already-built `rick-professor/dist`:

```sh
npm --prefix rick-professor run build
OPENAI_API_KEY=phase0-test-key node tests/phase0/professor-injected-benchmark.mjs
```

The Locker benchmark uses only an isolated Redis and Locker process. The
following commands show the relevant launch and probe sequence; wait for the
health endpoint before running the benchmark and stop only the two PIDs created
here:

```sh
phase0_tmp="$(mktemp -d)"
redis-server --bind 127.0.0.1 --port 6397 --save '' --appendonly no --dir "$phase0_tmp" >"$phase0_tmp/redis.log" 2>&1 &
redis_pid=$!
REDIS_URL=redis://127.0.0.1:6397 PORT=3317 npm --prefix modulo-redis-locker start >"$phase0_tmp/locker.log" 2>&1 &
locker_pid=$!
curl -fsS http://127.0.0.1:3317/healthz
LOCKER_URL=http://127.0.0.1:3317 node tests/phase0/locker-http-benchmark.mjs
kill "$locker_pid" "$redis_pid"
```

The benchmark scripts save the raw samples and calculate p50/p95 using the
nearest observed sample. This is a local reproducibility aid, not a production
capacity or latency SLO.
