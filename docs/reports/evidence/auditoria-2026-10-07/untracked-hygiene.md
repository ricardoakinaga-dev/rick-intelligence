# AUD07-19 — Higiene do worktree: artefatos não rastreados

**Estado:** PASS (escopo local) · **Data:** 2026-10-08 · **Commit base:** `b52f32c141916a2ea3af1a6b913bd91f380606e0`

## Aceitação (backlog `AUD07-19`)

| # | Critério | Resultado | Evidência |
|---|---|---|---|
| 1 | `git status --porcelain` num checkout limpo mostra só mudanças intencionais | **PASS** — `git status --porcelain` no worktree limpo (`git worktree add --detach … HEAD`) = **0 linhas** | secção «Checkout limpo» |
| 2 | A árvore não cresce por execução de teste | **PASS** — `make ci` e `make test` (exit 0 ambos): `git status --porcelain -uall \| sort` **antes = depois = 1380 linhas, 0 linhas de diff** | secção «Crescimento» |
| 3 | `git check-ignore` cobre os padrões generalizados | **PASS** — 12 provas + 5 provas negativas em `scripts/phase11/test_untracked_hygiene.py`; discrimitivo em `discrimination/untracked-hygiene-gitignore.txt` | secção «Correções» |

## Correções aplicadas

1. **`.gitignore` +2 regras** (linhas 72–73), com comentário que liga a tarefa:
   - `.opencode/` — estado da ferramenta (64 MB, 3 758 ficheiros) que aparecia como `?? .opencode/`;
   - `.agent/*.lock` — travões de escrita do control-plane (`.agent/.writer.lock`); os registos de gate `.agent/gates/*.json` continuam rastreáveis.
   - **Regressão da própria tarefa:** a 3.ª regra escrita a princípio (`uv.lock`) foi **revertida** — o experimento E4 mostrou que `check_control_plane` falha 3× num checkout novo com `VERIFY_ARTIFACT_REF … apps/api/uv.lock` (registos `VER-Q24-03-*` de `.agent/verification.jsonl` nomeiam o ficheiro). O ficheiro é hoje **staged** (90 KB) e a regressão passou a tê-lo como prova negativa, para a regra não voltar.
2. **Prova de regressão nova:** `scripts/phase11/test_untracked_hygiene.py` (2 testes) — pergunta ao próprio git com `git check-ignore --no-index -v` quais padrões casam e **qual a regra responsável** (`.next`, `.next-*`, `coverage`, `test-results`, `.coverage`, `tsbuildinfo`, `.runtime`, `.pytest_cache`, `artifacts`, `.opencode/`, `.agent/*.lock`); o `--no-index` é obrigatório, porque sem ele o git ignora a regra sobre ficheiros já no índice. As 5 provas negativas garantem que a exceção AUD07-18 (`!docs/reports/evidence/**/*.log`) nunca esconde evidência mantida — e que `apps/api/uv.lock` continua visível.
3. **Ligação ao runner:** `scripts/phase11/runner.py` passa a correr a regressão em `mode_test_fast` («worktree hygiene / gitignore coverage (AUD07-19)»), ou seja em `make ci`.

**Antes/depois do `git status --porcelain` (a nível de diretório):** 241 `??` → **239** com as 2 regras → **241** depois das entradas novas desta tarefa (prova de regressão, discriminação e `apps/api/uv.lock` reposto como visível).

## Medição: crescimento por execução de teste

```text
git status --porcelain -uall | sort > before   # 1380 linhas
make ci      # exit 0
git status --porcelain -uall | sort > after    # 1380 linhas, diff = 0 linhas
make test    # exit 0
diff before <(git status --porcelain -uall | sort)   # 0 linhas
```

Suites de `make test`: 614+103, 17, 1704+18, 734 e **496** (494 + os 2 testes novos) — todas a 0.

## Classificação dos 238 `??` restantes (todos intencionais: 231 ficheiros + 7 diretórios)

| Origem | Contagem | Nota |
|---|---|---|
| `apps/` | 65 | código, testes e config nunca commitados (AUD03–AUD06) |
| `docs/` | 64 | 58 `.md` + diretórios (`runbooks/`, `evaluation/`, `ci/control-inputs/`) |
| `packages/` | 64 | código e testes |
| `scripts/` | 24 | inclui a prova de regressão desta auditoria (staged) |
| `infrastructure/` | 11 | `vps/`, migrações `0004`–`0010`, provas |
| restantes | 3 | `.agent/gates/q24-…json`, `.github/workflows/publish-images.yml`, `mypy.ini` — mais `requirements/`, `docs/ci/control-inputs/`, `docs/runbooks/`, `docs/evaluation/`, `infrastructure/vps/`, `apps/web/tests/unit/` como diretórios |

Por extensão: 155 `.py`, 58 `.md`, 5 `.ts`, 5 `.sql`. **Nada foi apagado**: o trabalho do utilizador preservou-se; a limpeza fez-se por regras, não por remoção.

## Zonas grandes: porquê que não entram no status

| Caminho | Tamanho | Regra |
|---|---|---|
| `.runtime/` | 1,5 GB | `**/.runtime/` |
| `artifacts/` | 1,5 GB (inclui a bolsa de evidência) | `artifacts/` |
| `.opencode/` | 64 MB | `.opencode/` **(novo)** |
| `.gauntlet-state-of-art/` | 671 MB | `.gauntlet-*/` |

## Discriminação

`discrimination/untracked-hygiene-gitignore.txt`: **D1 reverter** (remover as 3 regras) → `git check-ignore` deixa de casar, o unittest dá **`unittest_exit=1` (failures=3)** e o `git status` volta a mostrar `.opencode/`, `.agent/.writer.lock` e `apps/api/uv.lock`; **D2 repor** → `unittest_exit=0` (OK) e 0 entradas no status.

## Limite honesto (fora da aceitação, medido; correção à vista do utilizador)

Um checkout limpo do `HEAD` está **vazio** de mudanças (`status` = 0), mas **`make validate`
falha aí (`exit 2`, 734 linhas `[FAIL]`)**. Duas causas distintas, ambas de versionamento:

1. **Ficheiros de CI que nunca foram trackeados.** `git log -- <path>` = vazio para
   `docs/ci/restore_control_inputs.py`, `docs/ci/snapshot_control_inputs.py`,
   `docs/ci/prove_control_restore.py`, `docs/ci/control-inputs/**` (bundle `v2/inputs.tar.xz`
   29 MB, 1 293 ficheiros) e `requirements/*.lock` (316 KB, inclui o `requirements/test.lock` que
   `.github/workflows/quality.yml` usa no 1.º passo). O README de `docs/ci/control-inputs`
   chama-lhes «checked-in controller helpers»/«versioned inputs» e o `Makefile` +
   os 3 workflows (`quality`, `phase-1.1`, `phase-1.5`) dependem deles.
2. **Refs para diretórios ignorados por desenho.** `.agent/backlog.json`/`verification.jsonl`
   apontam 660+ artefactos para `.gauntlet-state-of-art/**` (671 MB, 749 deles **presentes no
   bundle**), `.agent/legacy-v1/` (424 KB), `.review-control-history/` (296 KB), `.runtime/phase-3`
   (7 ficheiros no bundle), `artifacts/rec-m0-v3|v4` e `docs/progress` — todos ignorados pelas
   regras 34/37/39 do `.gitignore`.

### Experimentos (o mesmo estado, quatro montagens)

| # | Montagem | Resultado |
|---|---|---|
| **E1** | `git worktree add HEAD` puro | `git status` = 0 ✓; `make validate` **exit 2** (falta o script de restore, o bundle, os locks e os diretórios históricos) |
| **E2** | E1 + copiar trackeados/não-ignorados + `git add -A` + `make control-inputs-restore` | restore **exit 0** (1 293 ficheiros, `git status` **não cresce** — tudo cai em caminhos ignorados); `validate` falha: `node_modules` ausente e o `git add -A` **ressuscitou** as componentes aposentadas que o staging apaga (`cvg-master-rag-v2`, `rick-professor`, `modulo-redis-locker`) |
| **E3** | E1 + `git diff --cached` (só staging) + não-rastreados | falha: `Makefile` e `check_boundaries.py` estão **modificados sem staged**, logo o `HEAD` aplicado não tinha o alvo `control-inputs-restore` nem a regra nova |
| **E4** | E1 + `git diff --binary HEAD` (staged **e** unstaged) + copiar os 285 não-rastreados + `make control-inputs-restore` + `make validate` | restore **exit 0**; validate **exit 2 → 0**: as 3 falhas iniciais eram `VERIFY_ARTIFACT_REF … apps/api/uv.lock` (regra de ignore errada nesta tarefa, revertida); depois da correção **`RESULT PASS (pass=12 warn=0 fail=0)`** |

**E4 é a prova de que a receita funciona:** um checkout que materialize (a) as alterações
staged+unstaged, (b) os ficheiros hoje `??` e (c) o bundle, corre `make validate` a 0,
mantendo `git status` só com as mudanças intencionais (703 `A`, 439 `D`, 239 `M`, 1 `R`, 0 `??`).

### Opções

| Opção | O que implica | Estado |
|---|---|---|
| **A. Trackear o que falta e commitar o trabalho** | `git add` de `requirements/`, `docs/ci/*.py`, `docs/ci/control-inputs/**` (~29,5 MB) + commit do que já está staged/modificado/deletado (1 382 entradas) | **provado em E4** — checkout novo: `control-inputs-restore` 0 e `make validate` 0. Custo: pack atual de **1,38 MiB** passa a ~+30 MB (o bundle é comprimido e unchangeable por desenho do AUD03-21) |
| **B. Não trackear o bundle; mudar os checks** | exigiria editar `Makefile` + 3 workflows (chamam `control-inputs-restore` e `requirements/test.lock`) e, ainda assim, **660 refs** a `.gauntlet-state-of-art` continuariam por materializar | **não recomendado**: quebra o contrato AUD03-21 e não reproduz os gates em CI |
| **C. Deixar como está** | — | gates só passam nesta máquina; `quality.yml` (push/PR/cron diário) falha no 1.º passo se correr no GitHub |

**Recomendação: A**, com o commit em fatias (M0/M1, M2, código AUD03–06) ou num só — decisão do
utilizador; nenhum commit foi feito. Enquanto não se decide, o estado atual continua verde local.

**Nota para reconciliar com [`fix-gates-1.md`](fix-gates-1.md) §2:** o «checkout limpo» de
AUD07-09 copiava `git ls-files -co --exclude-standard` do worktree corrente (ou seja, incluía
ficheiros não rastreados não-ignorados e a versão já editada de `.agent/backlog.json`), pelo que
não deteta as lacunas 1 e 2 acima. Aqui mede-se worktrees verdadeiramente novos
(`git worktree add --detach … HEAD`).

## Evidência bruta

- `/tmp/opencode/aud19-{before-ci,after-ci,post-docs,post-ci2}.txt` (estado `-uall`), `/tmp/opencode/aud19-{ci,test,validate,ci-final}.log`
- `/tmp/opencode/pristine-aud19/` + `/tmp/opencode/pristine-validate.log` (E1), `/tmp/opencode/e2-*` (E2), `/tmp/opencode/e3-*` (E3), `/tmp/opencode/e4-*` (E4, decisivo), `/tmp/opencode/all-tracked.patch`
- `discrimination/untracked-hygiene-gitignore.txt`
- Próxima tarefa: **AUD07-20** (216 testes pulados por motivo/gate).
