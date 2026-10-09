# Evidência de remediação das 7 falhas de CI do checkout novo

**Data:** 2026-10-08. **Candidato:** worktree de `/home/ricardo/rick-intelligence`,
`HEAD = f47a3e62f3f4d237f02b58f788675c984952d103` (*Record AUD07-19 decision and
clean-checkout proof*) + correções desta página, commitadas e empurradas como
`4d2ac2c` (*Fix the seven failing CI lanes of the clean checkout*).
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
autorizados pelo utilizador em 08/10/2026 e executados como `4d2ac2c`. Os resultados do
CI desse push estão em §7.

## 7. Resultado do push (`4d2ac2c`, 2026-10-08T23:22:20Z)

| Workflow (run) | Conclusão | Observação |
|---|---|---|
| `RICK canonical quality lanes` (`37859057203`) | falha | 7 de 8 jobs verdes (`FAST`, `FRONTEND`, `SECURITY`, `RAG-EVAL`, `CONTRACT`, `SUPPLY-CHAIN`, `UNIT`); falha **só** o job `PHASE3`, por decisão de §6 |
| `phase-1.3-api-kernel` (`37859057204`) | **sucesso** | era vermelho em `f47a3e6` |
| `phase-1.3.1-identity-canonicalization` (`37859057299`) | **sucesso** | era vermelho em `f47a3e6` (`pyjwt`) |
| `phase-1.4-rag-extraction` (`37859057226`) | **sucesso** | era vermelho em `f47a3e6` |
| `phase-1.5-root-professor` (`37859057185`) | **sucesso** | era vermelho em `f47a3e6` |
| `phase-1.6-root-ingestion` (`37859057225`) | falha | `make api16-verify` devolveu `checks_passed: false` — diagnosticado e corrigido em §7.1; **verde no run `37864065077` (`7608f77`)** |
| `State of Art / release integrity` (`37859057262`) | falha | **546 passed / 10 subtests** (os 45 failed de `f47a3e6` resolvidos); falha agora só `release integrity` — §7.2 |
| `Phase 1.1 Root Foundation` (`37859057232`) | **sucesso** | já era verde |

Balanço do push inicial: 5 workflows verdes, 3 vermelhos.

## 8. Estado final após as correções de §7 (runs de `7608f77`)

| Workflow | Conclusão |
|---|---|
| `RICK canonical quality lanes` (`37864065133`) | 7 de 8 jobs verdes (`UNIT`, `CONTRACT`, `RAG-EVAL`, `FAST`, `FRONTEND`, `SECURITY`, `SUPPLY-CHAIN`); só `PHASE3` vermelho **por decisão de §6** |
| `phase-1.6-root-ingestion` (`37864065077`) | **sucesso** (correção de §7.1) |
| `Phase 1.1 Root Foundation` (`37864065087`) | **sucesso** |
| `State of Art / release integrity` (`37864065017`) | falha — só `release integrity`; §7.2 (pré-existente desde 10/09) |
| `phase-1.3`, `phase-1.3.1`, `phase-1.4`, `phase-1.5` | **sucesso** no run `4d2ac2c` (não reexecutados por filtros de caminho nos commits seguintes) |

Das 7 pipelines vermelhas de `f47a3e6`, 6 ficaram verdes (5 lanes de fase + os 7 jobs do
`quality` excepto `PHASE3`, que ficou vermelho por decisão explícita) e 1 (`State of
Art`) ficou com os testes corrigidos mas retém o seu gate de evidência de runtime, que
já falhava antes deste trabalho. Nenhum limiar, teste ou gate foi alterado; as três
alterações de suporte acrescentadas neste ciclo (`failed_checks`/`CHECK` no
`verify.py`, `output_tail` e o passo `npm ci` do `phase-1.6`) só tornaram o falhanço
diagnóstico e igualaram o job ao dos restantes workflows.

### 7.1 phase-1.6 — parser TypeScript em falta no job

`scripts/phase16/verify.py` engolia a saída de cada comando, pelo que o JSON do CI só
dizia `checks_passed: false` sem nomear o comando. O ciclo seguinte acrescentou
`failed_checks` (comando, `exit_code`, `test_pass_count`, `timed_out`, `output_tail`) e
uma linha `CHECK` por comando à saída — sem alterar o valor de saída nem nenhum limiar —
e revelou:

- `make api16-full` → `exit 2`, `test_pass_count 0`, falha em `validate`;
- `make api15-full` → `exit 2`, `test_pass_count 0`, falha em `api15-boundaries`;
- em ambos: `check_boundaries.py` → `"status": "FAIL"` com erro
  `"TypeScript boundary parser failed; install the pinned apps/web dependencies"`.

**Causa raiz:** o job `phase-1.6` era o único que executa `validate`/`api15-boundaries`
sem instalar as dependências pinadas de `apps/web` — `quality` (3×), `phase-1.1` (2×),
`phase-1.5` e `state-of-art-quality` têm o passo `npm ci`; `phase-1.6` não tinha. A
reprodução local fiel ao CI (venv novo de `test.lock`, sem `.runtime/venvs/cvg`) passava
os 6 comandos porque o anfitrião já tem `apps/web/node_modules`.

**Correção:** `.github/workflows/phase-1.6.yml` ganhou o mesmo par de passos dos outros
workflows — `actions/setup-node@49933ea5…` (v4.4.0) com `node-version: "22.19.0"` e
cache npm sobre `apps/web/package-lock.json`, seguido de
`npm ci --ignore-scripts --no-audit --no-fund` em `apps/web` —, colocado entre a
instalação de `requirements/test.lock` e `make control-inputs-restore`. Nenhum limiar,
teste ou gate foi alterado.

### 7.2 State of Art — envelopes de runtime não vinculados (pré-existente)

O job passou dos 45 testes falhados para **546 passed**, mas
`release_integrity.py --require-clean --evidence .runtime/release/release-evidence.json`
rejeita o manifesto com `DIRTY_RELEASE_EVIDENCE_REJECTED`, `FAILED_RUNTIME_REJECTED`,
`MISSING_EVIDENCE_REJECTED`, `MISSING_GATE_REJECTED`, `WRONG_HASH_REJECTED` e
`WRONG_TREE_REJECTED`: os envelopes dos gates `redis`, `postgresql`, `frontend-e2e`,
`accessibility` e `visual` não têm `commit_sha`/`tree_sha`/`checkout_fingerprint`
vinculados ao manifesto, não estão limpos nem correntes, têm `observed_at` fora da
janela e `raw_artifacts[0]` ausente. É a mesma classe do PHASE3 de §6 — evidência de
runtime que só as lanes de runtime sob autoridade podem produzir — e este workflow
vinha vermelho desde `b52f32c` (10/09/2026), portanto não é regressão deste commit.
Fica registado como achado aberto com a mesma opção §6: nenhum gate alterado.

## 9. Lane RUNTIME do job `quality` — duas remediações e verificação ao vivo (09/10/2026)

### 9.1 Diagnóstico: packet local vs packet do CI

O job `quality` só executa as cinco lanes de runtime (`RUNTIME`, `FRONTEND-RUNTIME`,
`PERFORMANCE`, `CHAOS`, `SOAK`) em `workflow_dispatch`/`schedule`. Reproduzi o packet localmente
no checkout limpo e comparei com o packet gerado pelo próprio CI:

| Packet | Geração | Classificação | Bloqueios |
| --- | --- | --- | --- |
| CI, schedule `37765169700` (`b52f32c`) | 2026-10-08T10:42:51Z | `DEVELOPMENT` | 33 |
| Local, `6f83e7c` | 2026-10-09T01:21:05Z | `DEVELOPMENT` | 26 |
| Dispatch `37871005009` (`a9ee017`) | 2026-10-09T01:51:07Z | `DEVELOPMENT` | 26 |
| Dispatch `37872405794` (`ce7a579`) | 2026-10-09T02:09:18Z | `DEVELOPMENT` | **25** |

As oito lanes locais que falhavam no CI dividem-se em duas causas, ambas de ambiente do job:

- **`web-lint`, `web-typecheck`, `web-build`** — o job `RUNTIME` instalava apenas
  `requirements/test.lock` e corria `make triple-aaa-verify`, cujos lanes web executam
  `cd apps/web && npm run …`. Sem `npm ci` os três falhavam. O job `FRONTEND-RUNTIME` já tinha
  o par de passos; `RUNTIME` não. Mesma classe da §7.1.
- **`control-plane`** (`make validate`) — o primeiro subcomando de `validate` é
  `control-inputs-check` (`restore_control_inputs.py --check`), que rejeita inputs em falta; o
  job `RUNTIME` nunca corria `make control-inputs-restore` (o job `FAST` sim). Idêntico à classe
  corrigida em §2.
- `domain`, `worker`, `api-root`, `api-contract` já não falhavam: ficaram verdes com as
  correções A–G de §2 (verificado: `make api16-domain api16-worker api16-root` = 1704 passed,
  `make api-contract` = `OpenAPI OK: 55 paths`, `make web-lint web-typecheck` = 0).

### 9.2 Correções e verificação ao vivo

| Commit | Alteração | Linhas |
| --- | --- | --- |
| `a9ee017` | `Install web dependencies in the Phase 3 runtime job` | +8 (`setup-node@49933ea5…` com cache npm + `npm ci --ignore-scripts --no-audit --no-fund` em `apps/web`) |
| `ce7a579` | `Restore control inputs in the Phase 3 runtime job` | +2 (`make control-inputs-restore` antes de `make triple-aaa-verify`) |

Verificação por `workflow_dispatch` sobre o `quality.yml` (repo público, sem custo):

- `37871005009` (`a9ee017`): bloqueios **33 → 26**; desbloqueadas ao vivo `api-contract`,
  `api-root`, `domain`, `worker`, `web-build`, `web-lint`, `web-typecheck`.
- `37872405794` (`ce7a579`): bloqueios **26 → 25**; desbloqueado `control-plane`.
- Nos dois dispatches: `FAST`, `UNIT`, `CONTRACT`, `RAG-EVAL`, `SECURITY`, `SUPPLY-CHAIN` e
  `FRONTEND` = `success`; `PHASE3` = `failure` (§6, não consome artefactos de runtime);
  `FRONTEND-RUNTIME`, `PERFORMANCE`, `CHAOS`, `SOAK` = `failure` por autoridade externa
  (`RICK_*`/Docker, `blocked_return_codes={2}`); `NIGHTLY` e `RELEASE` = `skipped` por desenho
  (`NIGHTLY` só em `schedule`; `RELEASE` exige lanes de runtime e o ambiente
  `triple-aaa-promotion`).
- Os runs de push (`37870998102`, `37872381448`) terminaram `cancelled`: entram no mesmo
  `concurrency group` `rick-quality-…` com `cancel-in-progress: true`. Sem perda de cobertura,
  os jobs correram todos nos dispatches.

Estado final da lane RUNTIME (`37872405794`): 4 `FAIL` + 21 `BLOCKED_EXTERNAL`.
Os `FAIL` são `release-evidence-generation` (local, downstream: `make release-evidence`
relata `FAIL` verdadeiro enquanto gates obrigatórios falham) e os externos
`release-integrity`, `phase3-evidence-verify` e `supply-chain`.

**Verificação local após cada alteração:** YAML analisado e `make validate` = 0 em ambas;
nenhum limiar, teste ou gate alterado.

### 9.3 Decomposição do `FAIL` de `supply-chain` (4 sub-checks estáticos)

Regenerei `.runtime/phase-3/supply-chain-runtime-evidence.json` no dispatch `37872405794`
(`freshness: CURRENT`, `commit_sha ce7a579…`, `clean_worktree: true`, `finished_at`
2026-10-09T02:09:07Z) e as quatro falhas estáticas são:

| Sub-check | Observação | Origem |
| --- | --- | --- |
| `lockfiles` | `missing: ["modulo-redis-locker", "rick-professor", "cvg-master-rag-v2/frontend"]` | **AUD07-45** (consumidor órfão de AUD07-02/04) |
| `sbom` | `missing_components`: os mesmos três | **AUD07-45** |
| `licenses` | `missing_lockfiles`: os mesmos três; único `denied` é `@csstools/color-helpers` = `MIT-0` em `apps/web` | **AUD07-45** (allowlist de SPDX) |
| `secret-scan` | 1 candidato: `private_key` em `packages/jobs/tests/test_contracts.py:276` | **AUD07-44** |

**A decisão sobre os três legados já existe:** AUD07-02 está `Concluída (retirada)` e
`docs/architecture/toolchain.md:23` e `docs/ci/README.md:26` registam que "the Phase 0.6
workflow and the three components it guarded (`cvg-master-rag-v2`, `rick-professor`,
`modulo-redis-locker`) were retired by AUD07-02 and AUD07-04". Os diretórios não existem na
árvore (`git ls-files` = 0 entradas). O que falta é despachar os consumidores que ficaram
para trás: `NODE_COMPONENTS` em `scripts/phase11/frontend_supply_runtime_gate.py:51` ainda os
declara como componentes Node canónicos — o gate exige `package.json` e `package-lock.json`
para caminhos que nunca mais existirão, pelo que `lockfiles`, `sbom` e `licenses` ficam
estruturalmente `FAIL`. `docs/architecture/preserved-components.json` declara-os ainda com
`root_snapshot_required: true`. Não foi feita nenhuma alteração a `NODE_COMPONENTS`, ao
manifesto nem à allowlist: alinhar cobertura de um gate é alteração de gate e exige
autoridade (AUD07-45).

O `secret-scan` usa `_HIGH_SIGNAL_SECRETS` (`private_key` = `-----BEGIN (?:RSA \|EC \|OPENSSH
\|DSA )?PRIVATE KEY-----`) sem mecanismo de allowlist para fixtures; o literal pertence a um
teste negativo que verifica a rejeição de chaves em payloads (`test_payload_is_deterministic_
bounded_and_rejects_secret_or_raw_content`). Qualquer correção aqui muda um gate de segurança
e fica registada como **AUD07-44** em vez de aplicada.

### 9.4 Estado

A lane RUNTIME já não apresenta nenhum defeito local: as oito falhas do CI de 08/10/2026 foram
remediadas, restando `release-evidence-generation` (downstream) e as lanes externas. Os achados
abertos continuam a ser (a) PHASE3 `--verify` — opção 3 de §6, (b) `State of Art / release
integrity` — §7.2, e agora (c) **AUD07-44** (`secret-scan` × fixture de teste) e (d)
**AUD07-45** (`NODE_COMPONENTS` e allowlist `MIT-0` do gate `P1-06` não alinhados à retirada
já decidida em AUD07-02/04).
