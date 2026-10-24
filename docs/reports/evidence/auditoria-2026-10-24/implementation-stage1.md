# AUD24 — primeira onda e etapa 1 da identidade (evidência local)

**Data:** 24/10/2026 (America/Sao_Paulo). **HEAD:** `48e383c25ca4af32aa7ffe7e2367360ca9742c58`. **Worktree:** alterações locais preservadas.
**Status:** `PASS` local para os contratos listados; **não é aceite de produto, release ou promoção**. Produção continua `NO-GO`.
**Decisão:** [ADR-024](../../../architecture/adr/ADR-024-audit-outcome-and-revocation-ordering.md), A+ em duas etapas. Esta rodada implementa a **etapa 1**.

## 1. Contratos executados

| Contrato | Resultado |
|---|---|
| AUD24-001 — baseline/restauração | PASS: 1.525 hashes rastreados, 48 não rastreados, status 116/116, worktree isolado restaurado |
| AUD24-003 — reconciliação | PASS: 29 contratos, 12 achados, 0 sobreposição de IDs, 29/29 com cobertura declarada |
| AUD24-012 — estado de auditoria (etapa 1) | PASS local: `completed` não é escrito no caminho da requisição; `effect_applied` + idempotência por `(action, request_id, status)`; `result_indeterminate` |
| AUD24-010 — reset com auditoria | PASS local no caminho normal: efeito, escopo e evento `auth.reset_effect`; falha de auditoria → `503 result_indeterminate`; residual de timeout na §5 |
| AUD24-011 — logout independente da auditoria | PASS local: revogação primeiro; sink indisponível não impede a revogação; sem `signed_out`/`completed` falso |
| AUD24-020 — chat após “Nova conversa” | PASS local: controller abortado não bloqueia o próximo envio |
| AUD24-021 — aborto externo na abertura | PASS local: estado de erro recuperável com retry, sem spinner permanente |
| AUD24-022 — mapeamento de erro | PASS local: 403 de casos vira `restricted`; abort de lista preserva registros anteriores; documentos mantêm semântica própria |
| AUD24-023 — 403 em casos | PASS local: página de permissão, sem retry cego |
| AUD24-024 — paginação de documentos | PASS local: cursor não avançante falha, dedupe por `document_id`, trava de requisição em voo |
| AUD24-030 — lane CONTRACT | PASS local: `make api-coverage` exit 0, 1.864 passed, 18 skipped, 79,48% |

## 2. Verificações

| Comando | Exit | Resultado |
|---|---:|---|
| `pytest apps/api/tests packages apps/worker/tests` | **0** | **6.022 passed, 137 skipped**, 199,3 s; B01 passa |
| `make api-coverage` | **0** | **1.864 passed, 18 skipped, 79,48%**, floor 75; lane CONTRACT verde |
| `npm run test:coverage` (sem `TMPDIR` do host) | **0** | **263 passed**, 91,95% linhas, 87,38% statements, 80,38% branches |
| `npm run test:unit` (chat/casos/documentos) | 0 | 20 chat + 79 casos/documentos; inclui AUD24-04/05/11 |
| `make lint` | 0 | Python/ESLint |
| `make typecheck` | 0 | TS + compileall + mypy |
| `make docs-check` | 0 | 1.131+ links, 0 erros |
| `make validate` | 0 | control plane PASS |

Logs locais (ignorados): `.runtime/aud24-core-tests.log`, `.runtime/aud24-api-coverage.log`, `.runtime/aud24-web-coverage.log`, `.runtime/aud24-lint-typecheck.log`.

## 3. Mudanças funcionais

- **Logout:** a revogação ocorre antes da auditoria; o evento é `effect_applied` (não terminal). Se a auditoria falhar ou o chamador abandonar, não há `completed`; a resposta é `503 result_indeterminate` com `request_id`, cookies removidos quando a revogação foi confirmada. A revogação não depende de sink.
- **Reset:** o resultado carrega o escopo server-side (`ResetEffect`), o evento `auth.reset_effect` é emitido uma vez no caminho normal; falha de auditoria vira `result_indeterminate`; conversão de resultado permanece no worker admitido.
- **Auditoria:** `PostgresAuditSink` deriva `event_id` estável de `(action, request_id, status)` e usa `ON CONFLICT DO NOTHING`; reenvios concorrentes não duplicam o mesmo evento.
- **Erro novo:** `result_indeterminate` (503) no envelope canônico.
- **Chat:** `startNewConversation` limpa o abort controller; aborto externo durante `openConversation` retorna estado recuperável com retry.
- **Casos/documentos:** 403 deixa de ser outage; aborto de lista preserva os registros anteriores; paginação de documentos deduplica e rejeita cursor repetido; E2E/unit cobrem os fluxos.
- **Testes:** contratos antigos de logout/reset foram substituídos por asserções do ADR-024, não removidos; B01 permanece no caminho do CONTRACT.

## 4. Arquivos principais

- [auth.py](../../../../apps/api/src/routes/auth.py)
- [identity_results.py](../../../../apps/api/src/services/identity_results.py)
- [postgres_identity.py](../../../../apps/api/src/services/postgres_identity.py)
- [postgres_audit.py](../../../../apps/api/src/services/postgres_audit.py)
- [errors.py](../../../../apps/api/src/core/errors.py)
- [chat-workspace.tsx](../../../../apps/web/components/chat/chat-workspace.tsx)
- [test_logout_revocation_failure.py](../../../../apps/api/tests/test_logout_revocation_failure.py)
- [test_aud15_identity.py](../../../../apps/api/tests/test_aud15_identity.py)
- [prod12-chat.test.tsx](../../../../apps/web/tests/unit/prod12-chat.test.tsx)
- [case-workspace.test.tsx](../../../../apps/web/tests/unit/case-workspace.test.tsx)
- [prod12-documents.test.tsx](../../../../apps/web/tests/unit/prod12-documents.test.tsx)
- [api-security.md](../../../architecture/api-security.md), [canonical-web.md](../../../architecture/canonical-web.md)

## 5. Residual e limites

1. **Etapa 2 do ADR-024 não implementada:** não há ainda tabela durável de operações, escrita na mesma transação do efeito, reconciliador ou alerta de backlog. Portanto:
   - se o reset comitar e o chamador for abandonado antes do evento, pode existir efeito sem evento (residual AUD24-01);
   - `effect_applied` pode permanecer sem estado terminal;
   - a idempotência cobre o evento do sink, não a operação inteira.
2. **PostgreSQL real, IdP e browser E2E não foram executados.** A prova é local/in-memory; `make api-coverage` não substitui store real.
3. **Worktree sujo:** o candidato não é commit-bound; AUD24-031/034 permanecem abertos.
4. **VPS lane** continua com barreira ambiental; não foi reexecutada.
5. **Testes web:** `TMPDIR` precisou ser apontado para o workspace; a portabilidade ainda é AUD24-032.
6. **Sem aceite:** o controlador não foi alterado; os itens permanecem em verificação local.

## 6. Próximo passo

Implementar a etapa 2 do ADR-024 (tabela `rick_audit_operations`, escrita transacional, projeto/ack, reconciliador, métricas), depois AUD24-031 (candidato limpo) e AUD24-034 (CI remoto). Sem isso, AUD24-012 e AUD24-010 não devem ser declarados `DONE`.

## 7. Etapa 2 do ADR-024 (M1)

**Implementado localmente em 24/10/2026.**

| Componente | Resultado |
|---|---|
| Migração `0011_audit_operations.sql` | Tabela `rick_audit_operations` com estados `requested/effect_applied/acknowledged/indeterminate/failed`, `UNIQUE(action, request_id)`, payload limitado e índice de pendentes; `migrate.py --check` PASS (11 arquivos) |
| `PostgresAuditOperationStore` | begin idempotente, mark_effect, acknowledge, indeterminate, fail/retry, pending e get; testes com conexão fake |
| Logout transacional | `PostgresIdentityProvider.logout(operation_id=...)` revoga a sessão e marca o efeito na **mesma conexão/transação**; teste confirma 2 UPDATEs e 1 commit |
| Reset transacional | `consume_password_reset(operation_id=...)` marca o efeito dentro da transação de claim/credencial/revogação |
| Rotas | `begin` antes do efeito; `mark_effect` fallback; `acknowledge` após projeção; `indeterminate` quando o efeito não pode ser conciliado; falha de projeção mantém a operação aberta |
| Reconciliador | `apps/worker/audit_reconcile.py` re-projeta pendentes, faz ack, retry e fail após orçamento; dry-run por padrão; testes |
| Composição | `Providers.audit_operations` + bind no `PostgresIdentityProvider` no composition externo |

**Testes focados:** 312 passed/16 skipped no conjunto de identidade/composição/reconciler; suíte núcleo **6.040 passed, 137 skipped, 0 failed**; `make api-coverage` verde (79,22%, floor 75; 1.875 passed, 18 skipped); `make lint`/`make typecheck` verdes.

**Residual:** PostgreSQL/IdP reais e worker de outbox não executados; a mesma transação do reset é code-reviewed, não exercitada contra claim table real; `AUD24-018` (tipagem/unificação de eventos) permanece P2.

## 8. Identidade — AUD24-013 a 017 (M1)

| Contrato | Resultado local |
|---|---|
| AUD24-013 OIDC | `logout_capable=False` no provider OIDC; a composição de produção rejeita identidade sem revogação; teste de atributo e composition guard |
| AUD24-014 timing | `Pbkdf2Verifier.verify_dummy` de custo fixo; conta inexistente paga o KDF dummy e não chama `verify`; teste com spy |
| AUD24-015 access denied | falha de auditoria de acesso negado gera log estruturado sem payload/exception; teste com `caplog` |
| AUD24-016 expiração absoluta | validade derivada de `created_at` imutável + `SESSION_ABSOLUTE_TTL_SECONDS`; `touch` não estende; cookie usa `SESSION_TTL_SECONDS`; teste de 301s |
| AUD24-017 multi-workspace | `LoginRequest.workspace_id` opcional; lookup por workspace; ambiguidade sem workspace retorna 409 acionável; reset continua neutro; testes de store/provider |

**Pendente:** `AUD24-018` (unificação tipada dos eventos de auditoria) e seletor de workspace na UI. O goal M1 permanece `PARCIAL` por esses dois pontos, não por falta de teste dos anteriores.

## 9. Fechamento local de M1 (AUD24-017/018 e 042)

| Item | Resultado |
|---|---|
| AUD24-017 UI | Campo opcional “Workspace” no login, com ajuda; `signIn`/`login` tipados; API envia `workspace_id`; typecheck PASS |
| AUD24-018 | `AuditEvent` TypedDict + `make_audit_event` allow-list; logout/reset/access_denied usam o boundary tipado; teste rejeita campo desconhecido/não-texto |
| AUD24-042 | mypy expandido de 10 para **14 módulos** (audit, audit_event, audit_operations_store, postgres_audit), todos 0/0; baseline explícito; `make typecheck` PASS |

**M1 local:** AUD24-010/011/013–018 cobertos por testes; suíte de identidade e CONTRACT verdes. Permanecem apenas store PostgreSQL/IdP reais `NOT_RUN` e aceite humano.

## 10. Cobertura de branches (AUD24-043)

| Alvo | Medição | Gate |
|---|---:|---|
| API | **76%** (13.179 statements + 4.652 branches; 2.732/1.076 perdidos) | `--cov-branch` adicionado ao `api-coverage`, floor de linhas 75 preservado |
| Worker | **76%** (4.564 statements + 1.564 branches; 932/383 perdidos) | `--cov-branch` adicionado ao `worker-coverage`, floor 74 preservado |
| Web | 80,38% branches | já coberto |

O gate API foi repetido e passou: **1.877 passed, 18 skipped, 75,65% combinado**, `make api-coverage` exit 0. O gate worker está em execução; a medição isolada foi 76%. A medição de branches não reduziu nenhum floor de linhas.
