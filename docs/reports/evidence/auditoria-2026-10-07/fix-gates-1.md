# Evidência de correção — gates M0/AUD07-03 a AUD07-09

**Data:** 2026-10-07. **Candidato:** worktree de `/home/ricardo/rick-intelligence`,
`HEAD = b52f32c141916a2ea3af1a6b913bd91f380606e0` (*Record alternate Docker endpoint probe*).
**Ambiente:** Python 3.12.3 (`.runtime/venvs/cvg`), Node v24.20.0 / npm 11.19.0 no host
(os workflows continuam pinando `3.12.3` / `22.19.0` via `setup-*`).

Esta página é o **depois** da tabela de gates em [`baseline-gates.md`](baseline-gates.md).

## 1. Gates no candidato (worktree do repositório)

| Gate | Comando | Exit | O que mudou |
|---|---|---|---|
| Validação | `make validate` | **0** | `check_boundaries.py` inverteu a política para "ausente da árvore + presente no histórico"; `check_toolchain.py` deixou de exigir `historical_ci_images`; `check_control_plane.py` não exige mais `.github/workflows/phase-0.6.yml` |
| Testes rápidos | `make test-fast` | **0** | lanes legadas removidas; `jsonschema` vem do lock; somadas as regressões de rota, ACL, runner e do validador de workflows |
| Lint | `make lint` | **0** | lanes Professor/CVG/Locker removidas; lint canônico `apps/web` = 0 |
| Typecheck | `make typecheck` | **0** | só `apps/web` tsc + `compileall scripts packages` |
| Build | `make build` | **0** | só o build canônico do `apps/web` |
| **CI completo** | `make ci` | **0** | 17 lanes, todas `exit 0` |
| Segurança de API | `make api-security` | **0** | 76 passed (A07) |
| Testes de API | `make api-test` | **0** | 1571 passed, 18 skipped |
| Phase 1.3.1 | `make api131-full` | **0** | 1571 passed |
| Phase 1.4 | `make api14-full` | **0** | 1571 passed |
| Phase 1.5 | `make api15-full` | **0** | contracts/provider/lock/professor/root/benchmark |
| Phase 1.6 | `make api16-full` | **0** | domain + cobertura + benchmark |
| Estáticos | `make ops-static` / `make compose-static` | **0** / **0** | 297 testes; 16 serviços renderizados em cada topology |
| Avaliação | `make eval-retrieval` / `make security-adversarial` | **0** / **0** | fixture offline; 8 registros adversariais |
| `pip check` | `.runtime/venvs/cvg/bin/python -m pip check` | **0** | *No broken requirements found.* |

Lane a lane de `make ci` (clean checkout), todas `exit 0` — 15 casos, 17 linhas `<==`
(contando os dois `pytest` aninhados de route/security e de ACL):

```
current root boundary validator ·
current root boundary validator · Phase 1.1 boundary validator regression ·
Phase 1.5 boundary validator regression · Phase 1.5 benchmark contract regression ·
<exit 0 do pytest aninhado> canonical route/security contract regression ·
<exit 0 do pytest aninhado> canonical retrieval ACL regression ·
CI runner and workflow-validator regressions ·
current root boundary validator · Phase 1.1 Python syntax ·
canonical API/worker Python syntax ·
canonical web lint · canonical web TypeScript compiler ·
canonical scripts/packages Python compilation · canonical web production build
```

`make ci` é `validate + test-fast + lint + typecheck + build` (`mode_ci` em
`scripts/phase11/runner.py`): **ele não roda** as suítes Python canônicas
(`phase14.py full`), a suíte de worker nem as regressões de validador/runner —
essas estão em `make test` (`mode_test`) e suas regressões parciais aparecem aqui
só através de `test-fast`.

## 2. `make ci` em checkout limpo (AUD07-09)

Procedimento — o único pré-requisito é o próprio repositório (`.git` + locks), nenhum
diretório local prévio (`.runtime/`, `node_modules/`, caches):

```sh
git ls-files -co --exclude-standard | while IFS= read -r f; do [ -e "$f" ] && echo "$f"; done > /tmp/opencode/files.txt
git clone --local /home/ricardo/rick-intelligence /tmp/opencode/clean-checkout   # HEAD = b52f32c
cd /tmp/opencode/clean-checkout
git ls-files -z | xargs -0 -r rm -f ; find . -type d -empty -not -path "./.git/*" -delete
rsync -a --files-from=/tmp/opencode/files.txt /home/ricardo/rick-intelligence/ "$PWD/"
make bootstrap   # exit 0
make ci          # exit 0  -> 17/17 lanes
```

**Saídas arquivadas:** `/tmp/opencode/cc-bootstrap.txt`, `/tmp/opencode/cc-ci.txt`
(só o resultado é reproduzível; os caminhos `/tmp/opencode` não são parte do repositório).
`.runtime` reconstruído no checkout limpo: 293 MB, gerado exclusivamente a partir de
`requirements/test.lock` (`uv pip install --require-hashes`) e `apps/web/package-lock.json`.

Restam 907 entradas em `git status` porque o candidato ainda **não foi commitado**: elas são
as modificações e as remoções dos três componentes aposentados. Nenhuma delas é um artefato
local prévio — tudo foi reconstruído a partir dos locks.

## 3. Reproduções discriminantes ainda falham (requisito de AUD07-09)

A correção de A02/A03 **ainda não foi aplicada** nesta etapa. Ambas as reproduções continuam
saindo com **exit 0** (defeito presente), como exigido:

```sh
.runtime/venvs/cvg/bin/python docs/reports/evidence/auditoria-2026-10-07/repro/repro_a02_archive_search.py   # exit 0
.runtime/venvs/cvg/bin/python docs/reports/evidence/auditoria-2026-10-07/repro/repro_a03_idempotency.py      # exit 0
```

Saída de A03 registrada nesta execução: `"cross_conversation_replay_defect": true`
(`expected_other_conversation: conv-B`).
Sairão com **exit 1** quando AUD07-10/11 forem concluídos.

## 4. Fixture: remover uma dependência do lock derruba a lane (AUD07-08)

`scripts/phase11/check_canonical_ci.py::_collect_lock_inputs` é a casa canônica da regra
"todo pin direto de `requirements/*.in` precisa estar no lock gerado"; roda dentro de
`make ops-static`, que é lane da lane `fast` do `quality.yml`.

```sh
cp requirements/runtime.lock /tmp/opencode/runtime.lock.bak
# apaga o bloco `jsonschema==4.26.0 \` do requirements/runtime.lock
make ops-static   # exit 2
# FAIL: requirements/runtime.lock: pin jsonschema==4.26.0 from requirements/runtime.in is absent or mismatched
cp /tmp/opencode/runtime.lock.bak requirements/runtime.lock   # restaurado byte a byte
```

Regressão permanente:
`scripts/phase11/test_check_canonical_ci.py::test_removing_a_dependency_from_the_lock_fails_the_lock_contract`
afirma a mensagem exata.

## 5. Mudanças de código desta etapa

| Área | Mudança |
|---|---|
| `scripts/phase11/runner.py` | constantes/lane legadas (`CVG`, `FRONTEND`, `PROFESSOR`, `LOCKER`, `cvg_env`, `run_preserving_generated_artifacts`, `_missing_cvg_approved_corpus`, `_start_locker`) removidas; `bootstrap`/`test-fast`/`test`/`lint`/`typecheck`/`build`/`test-integration`/`eval` repontados para os alvos canônicos; `PYTHON` passa a vir de `scripts/phase13/pyenv.py` |
| `scripts/phase11/test_compose_lifecycle.py` | teste do corpus CVG substituído por `test_full_test_mode_runs_only_canonical_lanes` |
| `scripts/phase11/check_workflow_actions.py` | segunda regra estática: step ativo não pode citar componente aposentado (comentário é permitido); regressões em `test_check_workflow_actions.py` |
| `scripts/phase15/check_boundaries.py` | flag `--retired-only` (mesma predicação de `check_preservation`, sem segunda implementação da política) |
| `.github/workflows/` | `phase-0.6.yml` **excluído** (40 refs); `quality.yml` supply-chain sem os 3 caminhos; `phase-1.1.yml` usando `requirements/test.lock` + `apps/web/package-lock.json`; `phase-1.5.yml`/`phase-1.6.yml` usando `check_boundaries.py --retired-only`. **58 → 0** referências legadas |
| `toolchain.json` | `installation` aponta para `requirements/test.lock`/`apps/web/package-lock.json`; `historical_ci_images` e a nota do Locker aposentados; `provenance` sem `phase-0.6.yml` |
| `docs/ci/check_control_plane.py`, `docs/ci/README.md`, `docs/architecture/toolchain.md` | `phase-0.6.yml` fora dos *required files*; prosa histórica corrigida |
| `Makefile` | `PYTEST := $(PYTHON) $(ROOT)/scripts/phase13/pyexec.py` nas receitas `api15-*`/`api16-*`/cobertura; `PYTHON ?= python3` **mantido** (contrato estático de `check_canonical_ci.py`) |
| `scripts/phase13/pyexec.py` | novo: troca apenas o intérprete pelo `pyenv.interpreter()`, preservando `PYTHONPATH`; sem venv é no-op (CI) |
| `scripts/phase05/bootstrap-runtime.sh` | já instalava `test.lock` com `--require-hashes` + `pip check` (AUD07-08) |

## 6. Verificação negativa preservada

`scripts/phase15/test_check_boundaries.py` continua rejeitando import proibido
(`forbidden import apps.api`) e import TypeScript legado em produção — 6 testes, `OK`.
Nenhum alvo obrigatório foi removido para ficar verde; apenas lanes cujos caminhos não
existem mais.
