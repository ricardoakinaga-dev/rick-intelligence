# PRD26 — onda local 1 (PRD26-003, 010 e 011)

**Data:** 24/10/2026, 23:02 America/Sao_Paulo · **UTC:** 25/10/2026, 02:02
**HEAD:** `dc79ec6f829b5690c6206b6ccba67021a78fcf35` · **Branch:** `archive/local-runtime-20261011`
**Worktree:** 7 entradas no início da onda; 15 ao final (documentos PRD26/AVAL24, evidência, `README.md`, `docs/INDEX.md`, `apps/web/playwright.config.ts`, `mypy.ini`, `docs/baselines/mypy-baseline.txt`, `apps/api/src/core/errors.py`).
**Status:** `VERIFY` local — implementação e evidência prontas; **não é `DONE`**, não há aceite formal, release ou promoção.
**Atualização:** a matriz E2E completa foi reexecutada após a mudança de `TMPDIR`: **363/363 passed**, 5,8 min, LCP máx. 916 ms.

## 1. Escopo

| Contrato | Entrega nesta onda | Estado |
|---|---|---|
| PRD26-003 | Correção do drift documental corrente | `VERIFY` |
| PRD26-010 | `TMPDIR` curto e portátil no E2E | `VERIFY` |
| PRD26-011 | mypy ampliado de 14 para 19 módulos | `VERIFY` |

## 2. PRD26-003 — documentação corrente

**Mudanças:**

- `docs/architecture/production-runtime.md`: reconhece a evidência M5 de PostgreSQL/Redis/S3/Qdrant e multi-worker 8/8, mantendo produção, IdP, provider, restore, observabilidade, performance/chaos/soak e deploy como `NOT_RUN`/`BLOCKED_EXTERNAL`.
- `docs/operations/release-readiness.md`: status passa a `REFERENCE / PARTIAL RUNTIME EVIDENCE`; a seção de ambiente registra o lab descartável e separa explicitamente o que continua `NOT_RUN`.
- `docs/roadmap-auditoria-2026-10-24.md` e `docs/plans/execplan-aud24-2026-10-24.md`: linha de status local atualizada para M3/M5, E2E 363/363 e candidato limpo.
- `docs/INDEX.md`: estados de arquitetura e operação atualizados; AVAL24/PRD26 já linkados.

**Aceite local:** `make docs-check` = 0 erros; nenhuma afirmação `CURRENT` contradiz a evidência M0–M5; links novos resolvem.

## 3. PRD26-010 — `TMPDIR` portátil

**Mudança:** `apps/web/playwright.config.ts` cria e exporta um diretório curto
(`RICK_WEB_E2E_TMPDIR` ou `/tmp/rick-e2e`) antes de iniciar browser e servidores.
O caminho longo do workspace deixa de ser herdado pelo Chrome.

**Verificação discriminante:**

```bash
cd apps/web
TMPDIR="$PWD/../../.runtime/tmp/e2e-long-path-for-prd26-portability-check" \
TMP="$PWD/../../.runtime/tmp/e2e-long-path-for-prd26-portability-check" \
npx playwright test tests/canonical-shell.spec.ts --project=mobile
```

Resultado: **5/5 passed em 13,6 s**, com o `TMPDIR` longo do chamador. Antes da
mudança, a mesma condição produzia `FATAL: Socket path too long` no Chrome.

**Matriz completa:** `make web-build` + `make web-e2e` = **363/363 passed**, 5,8 min, LCP máx. 916 ms, CLS 0,0022, 18 casos de performance.

## 4. PRD26-011 — tipagem

**Mudança:** `mypy.ini` e `docs/baselines/mypy-baseline.txt` passam a cobrir
`core/security.py`, `core/csrf.py`, `core/request_context.py`, `core/errors.py`
e `models.py`, todos com limite 0/0. `core/errors.py` recebeu anotações
explícitas em `_ServerErrorResponse` (`Scope`/`Receive`/`Send`).

**Verificação:** `make typecheck` = **PASS**, 19 módulos/roots, 0 erros.

**Limite:** rotas não-auth, services de ingestão/retrieval, stores e worker
continuam fora do denominador; a cobertura não é integral.

## 5. Comandos e resultados

| Comando | Exit | Resultado |
|---|---:|---|
| `make typecheck` | 0 | mypy 19 roots, 0/0 |
| `make lint` | 0 | Python, fronteiras e ESLint |
| `make docs-check` | 0 | 1.192 links, 0 erros |
| `npx playwright test tests/canonical-shell.spec.ts --project=mobile` | 0 | 5/5, com `TMPDIR` longo |
| `make web-build` + `make web-e2e` | 0 | **363/363**, 5,8 min; LCP 916 ms |
| `make validate` | 0 | Control plane 12/12, quality bar PASS |
| `make ci` | 0 | Validate, fast tests, lint, typecheck e build |
| `git diff --check` | 0 | Sem whitespace |

## 6. Limitações

- Nenhum gate externo foi executado nesta onda.
- Não há aceite formal; os três contratos permanecem `VERIFY`.
- A matriz E2E completa e o build de produção foram reexecutados após a mudança de `TMPDIR`; a evidência é local e não substitui CI remoto.
- O score AVAL24 não foi recalculado; a evidência é de implementação local.

## 7. Próximo passo

Executar a matriz E2E completa e o build de produção no candidato atualizado,
registrar o envelope e levar PRD26-003/010/011 à revisão de aceite (G1). Não
iniciar M3/M4 sem D04 e autorização externa.
