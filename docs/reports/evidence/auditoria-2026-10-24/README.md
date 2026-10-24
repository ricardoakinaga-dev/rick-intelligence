# Evidência AUD24 — primeira onda (M0)

**Data:** 24/10/2026 (America/Sao_Paulo). **Status:** `PASS` para AUD24-001 e AUD24-003; adoção no controlador ainda não declarada como aceite.
**HEAD:** `48e383c25ca4af32aa7ffe7e2367360ca9742c58`, branch `archive/local-runtime-20261011`.
**Baseline auditada:** [relatório AUD24](../../relatorio-auditoria-2026-10-24.md), 74,7/100, `NO-GO`.

## AUD24-001 — baseline e restauração

| Item | Resultado |
|---|---|
| Entradas de status no worktree | 116 (71 modificadas, 45 não rastreadas em status; 48 arquivos não rastreados hasheados) |
| Arquivos rastreados hasheados | 1.525 |
| Arquivos não rastreados hasheados | 48 |
| Arquivos no patch | 71 |
| Restauração em worktree isolado | `PASS` — 1.525/1.525 hashes rastreados OK |
| Hashes não rastreados | `PASS` — 48/48 OK |
| Status original × restaurado | `PASS` — 116/116 entradas idênticas |
| Deleções | 0 |

**Método:** `git status`, `git diff --binary`, `sha256sum` de rastreados/não rastreados, `git worktree add --detach HEAD`, aplicação do patch binário, cópia dos não rastreados, verificação `sha256sum -c`, comparação de `git status`. O worktree temporário foi removido após a prova.

**Artefatos locais (ignorados):** `.runtime/auditoria-2026-10-24/` — `tracked.patch`, `hashes-tracked.txt`, `hashes-untracked.txt`, `status-before.txt`, `untracked.txt`, `restore-check-*.log`, `manifest.json`, `restore-report.json`.
**Artefatos duráveis:** [baseline-manifest.json](baseline-manifest.json), [restore-report.json](restore-report.json).

**Limitações:** captura local, não backup externo; artefatos ignorados (`artifacts/`, `.runtime/`) não foram incluídos; não autoriza commit, release ou promoção.

## AUD24-003 — reconciliação AUD24 ↔ AUD15 ↔ PROD12

| Verificação | Resultado |
|---|---|
| Contratos AUD24 | 29 (11 P0, 13 P1, 5 P2) |
| Achados AUD24 | 12 |
| Achados com exatamente um contrato primário | 12/12 |
| Contratos com cobertura declarada | 29/29 |
| Dependências AUD24 desconhecidas | 0 |
| Sobreposição de IDs com AUD15/PROD12 | 0 |
| `make docs-check` | PASS — 1.131 links, 0 erros |
| `make validate` / control plane | PASS |

**Matriz:** [reconciliation.json](reconciliation.json). **Método:** parsing do relatório e do backlog, validação de IDs/dependências, checagem de sobreposição de namespaces, `make docs-check` e `make validate`.

**Limitações:** a matriz prova consistência documental, não implementação; 003 (governança), 033 (VPS), 044 (RAG) e 045 (acessibilidade) são cobertos por dimensão/obrigação, não por um achado AUD24-01…12.

## Gate G0

| Critério | Evidência | Estado |
|---|---|---|
| Baseline reproduzível, nenhum arquivo perdido | restore-report + hashes | PASS |
| Decisão B01 ratificada | [ADR-024](../../../architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md) | PASS |
| IDs reconciliados, sem duplicação | reconciliation.json | PASS |
| Quality bar/comandos congelados | [plano](../../../plans/execplan-aud24-2026-10-24.md), [primeira onda](../../../plans/aud24-first-wave-2026-10-24.md) | PASS |
| Nenhum código de produção alterado nesta onda | `git diff` de apps/packages | PASS |

**G0 local:** `PASS`. A adoção/aceite no controlador é um ato separado e não foi declarada por este documento.
