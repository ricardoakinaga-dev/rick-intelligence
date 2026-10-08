# Relatório de implementação R27 — 27/09/2026

**Base:** [roadmap R27](../roadmap-auditoria-2026-09-27.md), [backlog R27](../backlog-auditoria-2026-09-27.md), auditoria geral 79/100.

## Resultado executivo

Foram implementadas as tarefas locais R27-01 a R27-07 e R27-13. As tarefas dependentes de runtime/autoridade externa foram tentadas de forma real e permaneceram corretamente `BLOCKED_EXTERNAL`; nenhum PASS foi fabricado.

| Tarefa | Resultado |
|---|---|
| R27-01 — CSRF nonce por sessão | **IMPLEMENTADO / PASS LOCAL** |
| R27-02 — bootstrap MinIO sem root no healthcheck | **IMPLEMENTADO / PASS ESTÁTICO** |
| R27-03 — consolidar diálogos/helpers frontend | **IMPLEMENTADO / PASS LOCAL** |
| R27-04 — pin de actions/flags de instalação | **IMPLEMENTADO / PASS ESTÁTICO** |
| R27-05 — reconciliar toolchain | **IMPLEMENTADO / PASS DOCUMENTAL** |
| R27-06 — `retrieval_mode` explícito | **IMPLEMENTADO / PASS LOCAL** |
| R27-07 — autoridade dos gates A24-09 | **IMPLEMENTADO / EXPLICITADO, NÃO DESBLOQUEADO** |
| R27-08 — fluxo golden real | **BLOCKED_EXTERNAL** |
| R27-09 — outbox ponta-a-ponta | **BLOCKED_EXTERNAL** |
| R27-10 — restore/RPO/RTO | **BLOCKED_EXTERNAL** |
| R27-11 — capacidade | **BLOCKED_EXTERNAL** |
| R27-12 — caos/soak | **BLOCKED_EXTERNAL** |
| R27-13 — D04 | **IMPLEMENTADO COMO INTAKE CLÍNICO + REVISÃO HUMANA** |
| R27-14 — revisão independente | **BLOCKED_EXTERNAL / D07** |
| R27-15 — promoção | **BLOCKED_EXTERNAL / D07** |

## Alterações implementadas

### Segurança e composição

- CSRF: novo cookie nonce `rick_csrf`, não-HttpOnly, `SameSite=Strict`, emitido no login e removido no logout; o frontend lê o nonce e envia `X-CSRF-Token`; o backend valida o double-submit com `hmac.compare_digest`, preservando o token estático de compatibilidade e a validação Origin/Referer.
- Configuração adicionada: `CSRF_COOKIE_NAME`, com validação de nome visível.
- Healthcheck MinIO em dev/staging passou a usar endpoint nativo sem credencial root. O root permanece apenas no serviço MinIO e no bootstrap administrativo que cria bucket/policy/usuário scoped; API/worker continuam usando somente credenciais scoped.
- `retrieval_mode="auto"` foi explicitado na composição canônica, documentando que o modo escolhe híbrido quando sparse existe e degrada com sinal explícito em schemas legados.
- `toolchain.json` agora distingue o baseline histórico Phase 0.6 das imagens do laboratório canônico; `docs/architecture/toolchain.md` documenta as duas autoridades sem sobrescrever o baseline histórico.
- Actions não-pinadas de `phase-1.3.yml`, `phase-1.3.1.yml` e `phase-1.4.yml` foram fixadas em `checkout@v4.2.2` e `setup-python@v5.6.0`; as dependências inline foram consolidadas em `requirements/phase13.lock`, com hashes, `--require-hashes`, `--only-binary=:all:` e `pip check`.

### Frontend

- `ConfirmDialog` compartilhado usa `useId`, evitando colisão de IDs, e aceita `busyLabel`.
- `AdminConfirmDialog` duplicado foi removido; a tela administrativa usa o componente compartilhado.
- `errorMessage` simples foi centralizado em `apps/web/lib/api.ts`; a variante de casos com semântica D04 foi preservada intencionalmente.

### D04

A decisão escolhida foi “domínio clínico amplo”. A implementação usa `ClinicalDomainPolicy` (`rick-clinical-domain-v1`): solicitações clínicas entram no fluxo de classificação, mas recebem `DomainRisk.HIGH` e `human_review_required=True`, gerando `ESCALATE` antes da geração pelo provider. Isso implementa amplo intake sem liberar aconselhamento clínico autônomo sem revisão.

A decisão foi registrada em `docs/architecture/domain-decision-policy-2026-09-24.md`.

### A24-09

As lanes `lab-readiness`, `independent-reviews`, `production-runtime`, `sealed-packet` e `final-go-no-go` continuam sem executor local por desenho fail-closed. Seus detalhes agora apontam para `docs/architecture/promotion-authority.md`, que explicita autoridade, evidência aceita e evidência rejeitada. Isso resolve a ambiguidade documental, mas não substitui Docker aprovado, revisão independente, runtime de produção ou Go/No-Go humano.

## Verificações executadas

| Comando | Resultado |
|---|---|
| `make validate` | PASS |
| `python3 scripts/phase11/check_compose.py` | PASS; 14 serviços dev e 14 staging |
| `make triple-aaa-capability-matrix` | PASS; 11 linhas |
| `make api16-root` | PASS; 751 testes |
| `packages/decision` policy + decision tests | PASS; 42 testes |
| `apps/web npm run typecheck` | PASS |
| `apps/web npm run lint` | PASS |
| `apps/web npm run build` | PASS; Next.js production build |
| `uv pip install --dry-run --require-hashes --only-binary=:all:` | PASS; `requirements/phase13.lock` |
| `git diff --check` | PASS |
| Python `compileall` nas áreas modificadas | PASS |
| CSRF/security tests | PASS; 19 testes |

## Tentativa de runtime externo

O laboratório descartável foi executado com credenciais locais efêmeras:

- `integration_lab.py preflight`: passou.
- `integration_lab.py start`: `BLOCKED_EXTERNAL`; o daemon não conseguiu obter `minio/minio:RELEASE.2025-02-28T09-55-16Z` (`pull access denied`).
- O projeto `rick-rec-local-*` não deixou containers em execução.
- Containers de outros projetos não foram adotados nem modificados.
- Golden runtime: `BLOCKED_EXTERNAL` por ausência de `RICK_GOLDEN_RUNTIME_PATH`.
- Restore: `BLOCKED_EXTERNAL` por ausência de autoridade/backup descartável aprovado.
- Performance, chaos e soak: `BLOCKED_EXTERNAL` por ausência dos harnesses `RICK_PHASE3_*_COMMAND`.
- Foi feita uma segunda tentativa exploratória isolada com `quay.io/minio/minio:latest` e `keycloak:26.7.4`; os quatro containers iniciaram e o Postgres ficou `healthy`, mas os probes HTTP do host não foram alcançáveis nesta sessão. O laboratório foi encerrado e seus containers/rede foram removidos. Isso não é evidência do Compose canônico nem de promoção.

Consequentemente, não há evidência para fechar R27-08 a R27-12, nem para alegar RPO/RTO, capacidade, caos, soak, multi-worker, provider real ou fluxo ponta-a-ponta.

## Revalidação das 26 áreas

A revalidação final foi executada contra o checkout atual. Os itens locais foram cobertos por `make validate`, `make lint`, `make typecheck`, `make api16-root`, testes de decisão, build/lint/typecheck do web, validação Compose e matriz Triple AAA. O resultado por área é:

- **Verificado localmente:** 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 15, 16, 17, 19, 20, 21, 22, 23, 25, 26.
- **Verificado parcialmente, sem prova distribuída:** 8, 13, 14, 18, 24.
- **Sem PASS operacional:** 14, 17, 18, 23, 24 e 25 permanecem limitados por runtime/provider/harness/autoridade; isso não foi convertido em aprovação sintética.

A nota histórica de referência permanece **79/100**; nenhuma elevação foi reivindicada sem nova campanha distribuída comparável.

## Pendências que exigem autoridade externa

1. Corrigir ou autorizar a fonte da imagem MinIO do laboratório e executar o Compose canônico isolado.
2. Fornecer provider/corpus/decisões D01–D05 para o fluxo golden e avaliação real.
3. Fornecer revisão independente ligada ao snapshot exato.
4. Fornecer autoridade D07 para selo e Go/No-Go.

**Classificação atual:** `STATE_OF_ART_CANDIDATE`.
**Promoção:** `NO-GO`.
