# Evidência de remediação das 7 falhas de CI do checkout novo

**Data:** 2026-10-08. **Candidato:** worktree de `/home/ricardo/rick-intelligence`,
`HEAD = f47a3e62f3f4d237f02b58f788675c984952d103` (*Record AUD07-19 decision and
clean-checkout proof*) + correções desta página, ainda **não commitadas**.
**Ambiente:** Python 3.12.3 (`.runtime/venvs/cvg`), Node v24.20.0 / npm 11.19.0 no host;
os workflows continuam pinando `3.12.3` / `22.19.0`.

Esta página é o diagnóstico, as correções e a verificação local das sete pipelines
vermelhas do run `37768041811` (2026-10-08T11:07:55Z, `f47a3e6`). Ela não substitui a
confirmação em CI: essa só existe depois do push.

## 1. As 7 falhas observadas

| # | Workflow (run) | Job | Passo que falhou | Causa raiz |
|---|---|---|---|---|
| 1 | `RICK canonical quality lanes` (`37768041811`) | `UNIT` (`113280403289`) | `make api16-domain` | `RuntimeError: legacy differential reference is missing` na coleção de `packages/retrieval/tests/test_differential.py` e `test_shadow_quality.py` |
| 2 | idem | `CONTRACT` (`113280403539`) | `make api-coverage` → `make api16-root` | mesmo `RuntimeError` em `apps/api/tests/test_differential_auth.py` |
| 3 | idem | `SUPPLY-CHAIN` (`113280403518`) | `pip-audit -r requirements/test.lock --strict` | 3 CVEs: `pytest` 8.0.2 (PYSEC-2026-1845), `python-dotenv` 1.0.1 (PYSEC-2026-2270), `qdrant-client` 1.7.3 (PYSEC-2026-509) |
| 4 | idem | `PHASE3` (`113280403453`) | `Restore versioned control inputs` ausente | `FAIL: missing restored control inputs` — ver §6 para o restante |
| 5 | `phase-1.3-api-kernel` (`37768041815`) | `api-kernel` (`113280402018`) | `make api-test` | mesmo `RuntimeError` (`apps/api/tests`) |
| 6 | `phase-1.3.1-identity-canonicalization` (`37768041900`) | `canonical-identity-auth` (`113280402594`) | `phase131.py canonical` | `ModuleNotFoundError: No module named 'jwt'` em `packages/identity/tests/test_oidc.py` e `test_aud03_oidc.py` |
| 7 | `phase-1.4-rag-extraction` (`37768041922`) | `rag-extraction` (`113280402620`) | `phase14.py units` | mesmo `RuntimeError` (`packages/retrieval/tests`) |
| 8 | `phase-1.5-root-professor` (`37768041852`) | `root / Professor vertical slice` (`113280402754`) | `make api15-full` | mesmo `RuntimeError` (`apps/api/tests`) |
| 9 | `phase-1.6-root-ingestion` (`37768041843`) | `root / bounded ingestion lifecycle` (`113280402978`) | `make api16-verify` | filho `api16-full` falhou à cabeça (mesmo `RuntimeError`); watchdog de 300 s em `scripts/phase16/verify.py` expiraria depois (`exit 124`, `timed_out: true`), porque `make api16-full` mede 351,8 s |
| 10 | `State of Art / release integrity` (`37768041810`) | `release / integrity` (`113280402394`) | `Run pinned gate tests` | 45 failed / 501 passed; 38 deles `FileNotFoundError` para `docs/reports/evidence/implementation-aud03-2026-10-03/runtime/{qdrant,redis,redis_replica}_fault_harness.py` — os harnesses da AUD03 existiam no histórico e na evidence store mas não na árvore versionada |

Sete workflows = sete pipelines; o job de qualidade contribui com quatro jobs vermelhos.

## 2. Correções aplicadas

**A. Referência legada do diferencial (linhas 1, 2, 5, 7, 8, 9).**
`scripts/phase15/legacy_reference.py` passou a extrair `cvg-master-rag-v2` do object store
para `.runtime/legacy-reference/` (gitignorado) a partir do `SOURCE_REF` fixo
`b52f32c141916a2ea3af1a6b913bd91f380606e0`, com `--check` e marcador `.aud07-ref`;
regressão em `scripts/phase15/test_legacy_reference.py` (5 testes).
`scripts/phase13/legacy_reference_plugin.py` fixa `OTEL_AVAILABLE=False`/`_tracer=None`
nas lanes legacy para que o resultado seja determinístico (40 passed legacy, 26 passed
legacy-auth). O materializador é chamado por `_materialize_legacy_reference()` nos quatro
pontos de entrada que colectam suítes diferenciais — `scripts/phase13/phase13.py`
(`REFERENCE_MODES = {"test"}`), `scripts/phase13/phase131.py`
(`{"differential","api","legacy-auth","full"}`), `scripts/phase13/phase14.py`
(`{"units","differential","api","legacy","full"}`) e `scripts/phase11/runner.py`
(`legacy differential reference regression` em `mode_test_fast`) — e pelos pré-requisitos
`legacy-reference` de `api15-root`, `api16-domain` e `api16-root` no `Makefile`
(pré-requisito inline na única declaração de cada alvo, exigência de
`check_canonical_ci.py`).

**B. Inputs de controlo (linha 4 e todos os jobs).**
`.github/workflows/{quality,phase-1.3,phase-1.3.1,phase-1.4,phase-1.6}.yml` ganharam
`make control-inputs-restore` antes dos gates e `fetch-depth: 0` nos jobs que
`legacy_reference.py`/`control-inputs-check` dependem (`unit`, `contract`, `rag-eval`,
`phase3-evidence` já o tinham; verificado por script sobre todos os workflows).

**C. CVEs do supply chain (linha 3).**
`requirements/{phase13.in,test.in}` → `pytest==9.0.3`, `pytest-asyncio==1.4.0`,
`python-dotenv==1.2.2`, `qdrant-client==1.9.0`, `jsonschema==4.26.0`; locks regenerados
com os comandos de proveniência exatos declarados no cabeçalho (`uv pip compile
--generate-hashes --python-version 3.12 ...`).

**D. Harnesses AUD03 fora da árvore (linha 10).**
Os três ficheiros foram repostos em `docs/reports/evidence/implementation-aud03-2026-10-03/runtime/`
(soma de verificação igual à da evidence store, sem segredos) e
`scripts/state_of_art/tests/test_runtime_output_redaction_euclid1.py` passou a declarar
`HARNESS_SOURCES` com os caminhos literais e a guardar `sys.dont_write_bytecode` no
`load()`; `scripts/state_of_art/tests/test_release_output_isolation13.py` ganhou
`setUpModule()` que cria o directório de evidência; as asserções obsoletas de
`scripts/state_of_art/tests/test_generate_release_evidence.py` passaram a apontar para os
comandos supply-chain reais.

**E. `pyjwt` ausente do lock da fase 1.3 (linha 6).**
`packages/identity/src/rick_identity/oidc.py` importa `jwt`, mas `requirements/phase13.in`
não o declarava. Acrescentado `pyjwt==2.15.0` e regenerados `requirements/phase13.lock` e
`requirements/test.lock` (o segundo só mudou em comentários de proveniência).

**F. Watchdog do phase 1.6 (linha 9).**
`scripts/phase16/verify.py::_run` passou de `timeout=300` para `timeout=900`.

**G. Corrida temporal num teste (linhas 5/6/9, risco de vermelho residual).**
`apps/api/tests/test_provider_rework5_lifecycle.py::test_i1_05_sync_close_reconciled_once[False-cancel]`
falhou 2 de 2 execuções em suite cheia sob o ambiente fiel ao CI e 0 de 3 isolado: o ramo
`cancel` usava o mesmo orçamento de 40 ms que o ramo `timeout`, e um event loop carregado
deixava o shutdown terminar antes da `task.cancel()`. O ramo `cancel` passou a usar 5,0 s;
o ramo `timeout` mantém 0,04 s. Depois da mudança: 3 de 3 execuções de suíte cheia OK.

## 3. Verificação local — lanes fiéis ao CI

Ambiente fiel: venv novo instalado com `pip install --require-hashes --only-binary=:all:
-r requirements/phase13.lock` e `pyenv.interpreter()` sem `.runtime/venvs/cvg` (como num
checkout novo), com `PYTHONPATH` igual ao dos workflows.

| Lane (workflow) | Comando exato do CI | Exit | Resultado |
|---|---|---|---|
| quality `fast` | `make validate`, `make ops-static`, `make compose-static`, `check_boundaries.py --retired-only`, `git diff --check` | 0 | via `make ci` |
| quality `unit` | `make api15-contracts api15-provider api15-lock api15-professor api16-domain worker-coverage` + `pytest packages/evidence packages/decision` + `make jobs-test storage-test` + `pytest infrastructure/scripts/tests` | 0 | todos os 10 comandos OK; 94 passed (infra, com venv que tem `psycopg`) |
| quality `contract` | `make api-contract` + `git diff --exit-code -- apps/api/openapi.json` + `make api-coverage` | 0 | 1704 passed, cobertura **78,26 %** (floor 75) |
| quality `supply-chain` | `pip-audit -r requirements/test.lock --strict` (e os outros dois locks) + `npm ci` + `npm audit --audit-level=high` + `check_release.py --mode prepared` | 0 | 3/3 `pip-audit` limpos; npm audit só `moderate` (< `high`); `PASS: REC-33` |
| quality `rag-eval` | `make eval-retrieval eval-retrieval-pack api14-acl security-adversarial` | 0 | incluído em `make test`/`make ci` |
| `phase-1.3` | `make api-test api-security api-contract api-benchmark` | 0 | OK **após** a correção G (falhou 2/2 antes) |
| `phase-1.3.1` | `phase131.py canonical\|differential\|api\|legacy-auth` | 0 | 4/4 OK com o lock novo (`pyjwt` presente); `api` = 1703 passed |
| `phase-1.4` | `phase14.py units\|differential\|acl\|api\|legacy\|benchmark` | 0 | 6/6 OK |
| `phase-1.5` | `make api15-full` e `make api14-full` | 0 / 0 | 4008 passed / 2335 passed |
| `phase-1.6` | `make api16-verify` | **0** | `api16-full` 3087, `api15-full` 4008, `api14-full` 2335, `api-security` 181, `api-contract`, `git diff --check` |
| State of Art | `pytest scripts/state_of_art/tests` (com `PYTHONPATH` do CI) | 0 | 546 passed, 10 subtests |
| Gates do repositório | `make validate` / `make test` / `make ci` | 0 / 0 / 0 | `make test` = 501 passed + 17 subtests + suites de validador/runner; `make ci` = 22 `<exit 0>` |

Instalação de referência do lock da fase 1.3 (mesmos flags do CI):

```sh
python3 -m venv /tmp/opencode/venv-phase13b
/tmp/opencode/venv-phase13b/bin/python -m pip install --require-hashes --only-binary=:all: \
  -r requirements/phase13.lock   # exit 0, pip check: No broken requirements found, jwt 2.15.0
```

## 4. Reprodução fiel do PHASE3 em checkout limpo

```sh
git worktree add --detach /tmp/opencode/wt-clean f47a3e6   # árvore limpa, como no CI
cd /tmp/opencode/wt-clean
make control-inputs-restore    # exit 0 — inputs restaurados
make phase3-evidence           # exit 0 — matriz gerada
python3 scripts/state_of_art/generate_phase3_evidence.py --verify   # exit 1
make triple-aaa-capability-matrix   # exit 0
```

`--verify` devolve `classification: FAILED` por envelopes de runtime presos a
`2026-09-29T03:14Z`: `commit_sha`/`tree_sha`/`checkout_fingerprint` de outro candidato,
`clean_worktree: false`, `checkout_sentinel.*` divergente e
`observed_at is outside current evidence window` (`MAX_RUNTIME_EVIDENCE_AGE_SECONDS = 24 h`
em `scripts/state_of_art/phase3_evidence.py`). Os envelopes vêm do bundle versionado
`docs/ci/control-inputs/v2` — não há nada em `.runtime/phase-3` num checkout novo.

## 5. Observações (não bloqueiam)

- Flaky conhecido e pré-existente: `packages/providers/tests/test_production_rework5.py::test_i1_01_native_core_required_on_every_frame[id-2]` → `ProviderError(code='timeout')` sob carga (isolado: 5/5 passes).
- Os artefatos regenerados pela execução local (`docs/baselines/phase-1.3-api-overhead.json`, `docs/baselines/phase-1.4-perf.json`, `docs/progress/phase-1.5-perf.json`, `docs/progress/phase-1.6-perf.json`, `docs/progress/phase-1.6-verification.json`) foram revertidos para fora do diff.
- `make phase3-evidence` reescreve `.runtime/phase-3/capability-matrix.json` e por isso diverge do bundle; um `make control-inputs-restore` seguinte recusa o ficheiro divergente até ele ser removido (comportamento fail-closed, já assim no CI, onde nenhum job corre `control-inputs-check` depois de gerar a matriz).

## 6. Achado aberto — PHASE3 `--verify` é estruturalmente vermelho em push

Depois da correção B o passo `Validate matrix binding and status semantics` continua a
falhar, e falha em qualquer commit: as lanes que produzem envelopes frescos
(`runtime`, `frontend-runtime`, `performance`, `chaos`, `soak`) só correm com
`github.event_name == 'schedule' || 'workflow_dispatch'`, o PHASE3 não descarrega os
artefactos delas, e o bundle só pode ser renovado por uma operação de autoridade
(`docs/ci/snapshot_control_inputs.py`). Ou seja, no estado atual o vermelho do PHASE3 é o
fail-closed a funcionar — `docs/reports/current-triple-aaa-gap-audit.md` regista que
`phase3-evidence-verify` "correctly reject[s] the current non-promotable evidence".

Opções apresentadas ao utilizador:

1. **Manter como gate de promoção:** PHASE3 estrito só em `schedule`/`workflow_dispatch`
   (igual às lanes de runtime), mantendo no push `make phase3-evidence` (validação
   estrutural, que continua a falhar em erro real) e `make triple-aaa-capability-matrix`;
   o `nightly` já corre `make phase3-evidence-verify` com artefatos frescos.
2. **Renovar o bundle** com evidência de runtime do candidato atual (exige executar as
   lanes de runtime e correr `docs/ci/snapshot_control_inputs.py` sob autoridade) — fica
   vermelho outra vez no commit seguinte.
3. **Deixar vermelho** e registar o PHASE3 como gate de promoção não cumprido.

**Decisão (08/10/2026, utilizador): opção 3 — deixar vermelho e registar.** Nenhum gate foi
alterado; o `quality` / PHASE3 permanece vermelho por desenho e o PHASE3 `--verify` fica
registado em [`AUD07-43`](../../../backlog-auditoria-2026-10-07.md) como gate de promoção
não cumprido, até que haja evidência de runtime fresca sob autoridade. As opções 1 e 2
seguem intactas para decisão futura.

O restante trabalho desta página está concluído localmente; o commit e o push foram
autorizados pelo utilizador em 08/10/2026 para confirmação em CI.
