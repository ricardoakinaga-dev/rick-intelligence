# Backlog executivo — RICK Intelligence Triplo AAA

**Data-base:** 2026-09-07
**Status:** backlog de promoção proposto a partir da auditoria atual
**Prioridade:** `P0` bloqueia promoção; `P1` é necessário para a barra AAA;
  `P2` é evolução após estabilidade.
**Regra:** nenhum item muda para `DONE` sem evidência atual na fronteira
  correspondente.

Este backlog é aditivo e datado. Ele não substitui nem reescreve o controle
existente em `.agent/backlog.json` ou os documentos `state-of-art-*`; serve como
plano executivo de fechamento da lacuna entre o root local e o produto de
produção Triplo AAA.

Documentos relacionados:

- [Plano executivo](triplo-aaa-executive-plan-2026-09-07.md)
- [Roadmap](triplo-aaa-roadmap-2026-09-07.md)
- [Auditoria](../reports/relatorio-auditoria-state-of-art-2026-09-07.md)

## 1. Estados

| Estado | Significado |
| --- | --- |
| `READY_NOW` | pode ser iniciado sem decisão externa nova |
| `READY_AFTER_R0` | depende do fechamento da integridade local |
| `IN_PROGRESS_LOCAL` | há implementação local, mas o aceite de produção está aberto |
| `BLOCKED_DECISION` | depende de decisão de produto, segurança ou operações |
| `BLOCKED_EXTERNAL` | depende de serviço, credencial, corpus ou ambiente autorizado |
| `DONE_LOCAL_SCOPE` | concluído apenas no escopo local explicitamente indicado |
| `DONE` | aceite completo do item, incluindo evidência e regressão |

## 2. Fundação e integridade

| ID | P | Item | Estado | Aceite/evidência | Dependências |
| --- | ---: | --- | --- | --- | --- |
| AAA-001 | P0 | Corrigir o contexto do benchmark Phase 1.5 com `tenant_id` explícito | `DONE_LOCAL_SCOPE` | `make api15-full` passou sem enfraquecer `RetrievalContext`; benchmark executável com contexto tenant-scoped | — |
| AAA-002 | P0 | Reexecutar matriz Phase 1.5 e Phase 1.6 no mesmo revision | `DONE_LOCAL_SCOPE` | `make api15-verify` e `make api16-verify` PASS; artifacts atuais em `docs/progress/` | AAA-001 |
| AAA-003 | P0 | Reconciliar performance web 620/920 ms e registrar build/window | `DONE_LOCAL_SCOPE` | `make web-validate` atualizou o pacote Cycle5; LCP máximo 692 ms e CLS 0,0245569; 620/920 ms permanecem históricos | AAA-002 |
| AAA-004 | P0 | Congelar Quality Bar Triplo AAA e manifest de candidato | `DONE_LOCAL_SCOPE` | `docs/progress/manifests/quality-bar-triplo-aaa-2026-09-07.json` fixa A1/A2/A3, thresholds, limites e NO-GO | AAA-002, AAA-003 |
| AAA-005 | P0 | Separar evidência histórica de evidência vigente | `DONE_LOCAL_SCOPE` | documentação marca 620/920 ms como históricos e 532 ms como vigente; escopo local permanece explícito | — |
| AAA-006 | P0 | Corrigir o fluxo de release evidence e fingerprint | `BLOCKED_EXTERNAL` | `release-evidence.json` atual, checkout candidato limpo e gate íntegro | AAA-004, ambiente de release |

## 3. Dados, persistência e ingestão durável

| ID | P | Item | Estado | Aceite/evidência | Dependências |
| --- | ---: | --- | --- | --- | --- |
| AAA-010 | P0 | Escolher Postgres, tenancy model, retenção e estratégia de migração | `BLOCKED_DECISION` | ADR aprovado por Domain, Security e Ops | decisão humana |
| AAA-011 | P0 | Implementar schema Postgres de collections, documents, chunks, jobs, sessions e audit | `READY_AFTER_R0` | migration up/down, constraints, indexes, checksums e isolamento | AAA-010 |
| AAA-012 | P0 | Criar runner de migrations com checksum, lock e rollback seguro | `READY_AFTER_R0` | execução em banco descartável, repeatability e failure recovery | AAA-011 |
| AAA-013 | P0 | Escolher e integrar object storage S3-compatible | `BLOCKED_DECISION` | adapter injetado, bucket privado, auth, timeout e lifecycle | decisão humana |
| AAA-014 | P0 | Implementar object lifecycle, checksum, retention e cleanup lease | `READY_AFTER_R0` | upload/download autorizado, path traversal negative, orphan cleanup e reopen | AAA-013 |
| AAA-015 | P0 | Promover a fila local para broker/durable queue multi-instância | `BLOCKED_DECISION` | idempotência, backpressure, retry finito, dead-letter, lease e cancellation | escolha de broker |
| AAA-016 | P0 | Integrar worker production com composition root | `IN_PROGRESS_LOCAL` | envelope imutável de admissão e payload seguro implementados em `packages/ingestion`; API→fila→worker e restart continuam abertos | AAA-015, AAA-019 |
| AAA-017 | P0 | Conectar Qdrant live ao retrieval root | `READY_AFTER_R1` | health, upsert, query, ACL, delete/count, timeout e cleanup live | AAA-011 |
| AAA-018 | P0 | Conectar Redis lease ao Professor/worker | `READY_AFTER_R1` | owner-safe acquire/renew/release, expiry, replacement e degraded health | AAA-015 |
| AAA-019 | P0 | Compor provider externo resiliente no ambiente de produção | `BLOCKED_EXTERNAL` | secret injection, timeout, retry, circuit breaker, budget, redaction e shutdown | provider/secret manager |
| AAA-020 | P1 | Retenção e purge de jobs, objetos, vetores e audit | `READY_AFTER_R1` | política versionada, audit event, dry-run e negative de remoção indevida | AAA-011, AAA-014, AAA-015 |

## 4. Identidade, segurança e isolamento

| ID | P | Item | Estado | Aceite/evidência | Dependências |
| --- | ---: | --- | --- | --- | --- |
| AAA-021 | P0 | Escolher IdP/OIDC e modelo de claims | `BLOCKED_DECISION` | threat model e ADR de subject/tenant/role/scopes | decisão humana |
| AAA-022 | P0 | Implementar OIDC, discovery, JWKS, callback e sessão segura | `BLOCKED_EXTERNAL` | IdP descartável, token expiry, invalid issuer/audience e logout | AAA-021 |
| AAA-023 | P0 | Implementar revogação, rotação e encerramento de sessões | `READY_AFTER_R2` | logout global, revoke admin, replay negative e audit sem segredo | AAA-022, AAA-011 |
| AAA-024 | P0 | Executar matriz completa de tenant/workspace/collection em todas as rotas | `READY_AFTER_R2` | cross-scope 401/403/404 conforme contrato, zero leakage e zero oracle | AAA-022, AAA-011, AAA-017 |
| AAA-025 | P0 | Substituir rate limit process-local por política distribuída | `IN_PROGRESS_LOCAL` | login/chat/compatibilidade/recuperação têm buckets locais compartilhados e 429 neutro; multi-réplica/distribuído permanece aberto | AAA-015, AAA-018 |
| AAA-026 | P1 | Fechar CSRF/CORS/cookie/browser matrix contra ambiente real | `READY_AFTER_R2` | origin/referer/token, SameSite, secure cookie, preflight e headers | AAA-022 |
| AAA-027 | P1 | Migrar armazenamento de senha para Argon2id e planejar rehash | `READY_AFTER_R2` | migration segura, fallback PBKDF2 somente para rehash controlado | AAA-022 |
| AAA-028 | P0 | Consolidar secret management e threat model operacional | `READY_AFTER_R1` | nenhum segredo em logs, traces, jobs, dumps, errors ou artifacts | AAA-013, AAA-019, AAA-022 |

## 5. Retrieval, grounding e produto de inteligência

| ID | P | Item | Estado | Aceite/evidência | Dependências |
| --- | ---: | --- | --- | --- | --- |
| AAA-030 | P0 | Aprovar corpus licenciado e política de dados sensíveis | `BLOCKED_DECISION` | owner de produto/legal registra origem, licença, retenção e anonimização | decisão humana |
| AAA-031 | P0 | Versionar golden set por persona e dificuldade | `READY_AFTER_R0` | queries, expected evidence, ACL scopes, idioma e versão reproduzível | AAA-030 |
| AAA-032 | P0 | Fixar thresholds de retrieval e freshness | `BLOCKED_DECISION` | recall/hit@k, leakage, citation coverage, freshness e latency aprovados | AAA-031 |
| AAA-033 | P0 | Executar avaliação live no Qdrant com corpus aprovado | `READY_AFTER_R3` | zero ACL leakage, thresholds pass, latency e cleanup | AAA-017, AAA-031, AAA-032 |
| AAA-034 | P0 | Fechar Professor grounded generation live | `READY_AFTER_R3` | evidence gate, unsupported claims, citation markers, provider failures e budgets | AAA-019, AAA-033 |
| AAA-035 | P1 | Implementar OCR, tabelas, páginas e provenance prioritários | `READY_AFTER_R3` | fixtures por formato, page/source accuracy e fallback explícito | AAA-014, AAA-030 |
| AAA-036 | P1 | Criar feedback/review queue humana | `READY_AFTER_R3` | audit trail, triagem, no silent prompt mutation e rollback de decisão | AAA-034, observabilidade |
| AAA-037 | P1 | Versionar prompt, policy, model e embedding config | `READY_AFTER_R3` | resposta identifica versões e mudança invalida evidence antiga | AAA-032, AAA-034 |
| AAA-038 | P1 | Definir custo e orçamento por consulta/tenant | `READY_AFTER_R3` | budgets, quota, alertas e comportamento de excesso | AAA-019, AAA-037 |

## 6. Web, UX e acessibilidade

| ID | P | Item | Estado | Aceite/evidência | Dependências |
| --- | ---: | --- | --- | --- | --- |
| AAA-040 | P0 | Validar web contra API root real sem intercept de produção | `READY_AFTER_R1` | login, documents, search, chat e admin com banco/queue live | AAA-016, AAA-022 |
| AAA-041 | P0 | Implementar tenant switcher e navegação por permissão | `IN_PROGRESS_LOCAL` | mudança de identidade remonta estado privado e nunca concede ACL | AAA-022, AAA-024 |
| AAA-042 | P0 | Fechar workspace de documentos completo | `IN_PROGRESS_LOCAL` | upload, progress, empty, forbidden, retry, cancel, delete, reindex e stale-state tests | AAA-040 |
| AAA-043 | P0 | Fechar busca/chat com evidence drawer e confidence honesta | `IN_PROGRESS_LOCAL` | citations, no-evidence, weak, provider error, copy/export seguro | AAA-034, AAA-040 |
| AAA-044 | P0 | Fechar teclado, foco, contraste, zoom, reflow e reduced motion | `IN_PROGRESS_LOCAL` | WCAG AA manual + axe sem Critical/High em 375/768/1440 | AAA-041, AAA-042, AAA-043 |
| AAA-045 | P0 | Eliminar ou justificar os 6 skips de viewport | `DONE_LOCAL_SCOPE` | `make web-validate` executou 234/234 em 375/768/1440 sem skip planejado ou executável; Cycle5 também persiste 320px, escala 200% e interações | AAA-044 |
| AAA-046 | P1 | Integrar estados de readiness, audit e incident na UX | `IN_PROGRESS_LOCAL` | estados `ready`, `degraded`, `unavailable` e desconhecido têm cópia/recovery local; integração live e incident feed permanecem abertas | AAA-040, AAA-050 |
| AAA-047 | P0 | Rodar crítica visual independente do produto completo | `READY_AFTER_R4` | packet final selado com 141 PNGs/141 JSONs, mas o ciclo independente de 2026-09-07 não emitiu parecer dentro da janela; score >=95 e ausência de Critical/High continuam obrigatórios | AAA-044, AAA-045 |

## 7. Observabilidade, performance e release

| ID | P | Item | Estado | Aceite/evidência | Dependências |
| --- | ---: | --- | --- | --- | --- |
| AAA-050 | P0 | Integrar exporter/collector de logs, métricas e traces | `READY_AFTER_R1` | redaction, bounded labels, correlation e no-data explícito | AAA-019, AAA-028 |
| AAA-051 | P0 | Implementar readiness real das dependências | `READY_AFTER_R1` | dependency down/up, required/optional, safe JSON e no secret | AAA-016, AAA-017, AAA-018, AAA-019 |
| AAA-052 | P0 | Executar backup/restore completo | `BLOCKED_EXTERNAL` | Postgres, Redis/Qdrant aplicável, object store, checksums, ACL e smoke | AAA-011, AAA-014, AAA-017 |
| AAA-053 | P1 | Executar load, soak, concurrency e cost tests | `READY_AFTER_R5` | p50/p95/p99, memory, queue depth, provider cost, thresholds e limits | AAA-016, AAA-033 |
| AAA-054 | P0 | Produzir imagens imutáveis e compose/deploy de produção | `BLOCKED_EXTERNAL` | image digest, secrets injection, health, network isolation e no default secret | AAA-016, AAA-019, AAA-050 |
| AAA-055 | P0 | Executar restart, dependency failure e incident drills | `READY_AFTER_R5` | runbook, detection, containment, recovery time e audit trail | AAA-050, AAA-051, AAA-052 |
| AAA-056 | P0 | Implementar canary, rollback e migration roll-forward | `READY_AFTER_R5` | switch reversível, metrics window, rollback rehearsal e compatibility | AAA-012, AAA-054, AAA-055 |
| AAA-057 | P1 | Definir dashboards, alerts e ownership de SLO | `READY_AFTER_R5` | error rate, latency, dead-letter, ACL denials, health e alert delivery | AAA-050, AAA-053 |
| AAA-060 | P0 | Rodar Integration Reviewer fresco | `READY_AFTER_R6` | revisão independente, packet selado, gaps e verdict por critério | todos P0 |
| AAA-061 | P0 | Rodar Final Critic do programa completo | `READY_AFTER_R6` | A1/A2/A3, segurança, web, ops e release sem autoaprovação | AAA-060 |
| AAA-062 | P0 | Gerar `release-evidence.json` e manifest final | `READY_AFTER_R6` | HEAD, fingerprint, commands, current evidence, limitations e reviewers | AAA-056, AAA-060 |
| AAA-063 | P0 | Decisão formal Go/No-Go | `BLOCKED_DECISION` | Product/Security/Ops aceitam ou rejeitam residual risk com autoridade | AAA-061, AAA-062 |
| AAA-064 | P2 | Retrospectiva e evolução pós-release | `READY_AFTER_R6` | incident learnings, cost/quality deltas e backlog seguinte | AAA-063 |

## 8. Ordem imediata de execução

O próximo ciclo deve executar somente esta sequência:

1. `AAA-001` — corrigir o benchmark.
2. `AAA-002` — reexecutar e registrar as matrizes.
3. `AAA-003` — reconciliar performance web.
4. `AAA-004` — congelar Quality Bar e manifest.
5. `AAA-010`, `AAA-013`, `AAA-015`, `AAA-021` e `AAA-030` — abrir as decisões
   humanas que desbloqueiam o spine, a segurança e o corpus.

Nenhum item P0 externo deve ser marcado como concluído por inspeção estática ou
por um serviço simulado.

## 9. Critério de priorização

Quando houver capacidade limitada, a ordem é:

1. correctness, autorização e integridade de dados;
2. durabilidade, recovery e observabilidade;
3. grounding, freshness e qualidade da resposta;
4. acessibilidade, estados e clareza da UX;
5. performance/custo e polish.

Um item de polish nunca deve ultrapassar um P0 de segurança, dados, grounding
ou disponibilidade.
