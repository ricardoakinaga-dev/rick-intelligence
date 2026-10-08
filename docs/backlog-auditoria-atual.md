# Backlog executável — Snapshot histórico

> **HISTORICAL / SUPERSEDED em 2026-10-01.** Os itens RA72 abaixo são snapshot preservado, não a fila atual. Consulte o [backlog de 2026-10-01](backlog-auditoria-2026-10-01.md), o [roadmap correspondente](roadmap-auditoria-2026-10-01.md) e o [relatório](reports/relatorio-auditoria-geral-2026-10-01.md).

**Origem histórica:** [roadmap anterior](roadmap-auditoria-atual.md) e relatório de auditoria anterior.
**Estado:** snapshot proposto; não altera o estado canônico em `.agent/`.

## Convenções

- **P0:** bloqueador de segurança, integridade ou promoção.
- **P1:** correção necessária para entrega integrada confiável.
- **P2:** qualidade, manutenção ou melhoria operacional.
- **M/G:** porte relativo, não prazo.
- Cada item exige reprodução, implementação mínima, teste positivo/negativo, regressão, diff revisado, comando, exit code, artefato e limitações.

## Fila priorizada

| ID | Marco | Prioridade | Porte | Dependências |
|---|---|---:|---:|---|
| RA72-01 | M0 | P0 | M | — |
| RA72-02 | M0 | P0 | M | RA72-01 |
| RA72-03 | M0 | P1 | M | RA72-01 |
| RA72-04 | M1 | P0 | G | RA72-02 |
| RA72-05 | M1 | P0 | M | RA72-02 |
| RA72-06 | M1 | P1 | G | RA72-02 |
| RA72-07 | M1 | P1 | M | RA72-02 |
| RA72-08 | M1 | P1 | M | RA72-02 |
| RA72-09 | M2 | P0 | M | RA72-01 |
| RA72-10 | M2 | P1 | G | RA72-09 |
| RA72-11 | M2 | P1 | M | RA72-09 |
| RA72-12 | M2 | P1 | M | RA72-09 |
| RA72-13 | M2 | P2 | M | RA72-09 |
| RA72-14 | M3 | P1 | M | RA72-10, RA72-13 |
| RA72-15 | M3 | P1 | M | RA72-02 |
| RA72-16 | M4 | P1 | G | RA72-04, RA72-14, RA72-15 |
| RA72-17 | M4 | P1 | M | RA72-16 |
| RA72-18 | M5 | P0 | G | RA72-16 |
| RA72-19 | M5 | P1 | G | RA72-18 |
| RA72-20 | M5 | P0 | G | RA72-18, RA72-19 |

## M0 — Baseline e rastreabilidade

### RA72-01 — Reproduzir bloqueadores atuais

**Problemas:** `web-validate` falha por Vitest ausente; gates completos não fecham; runtime externo não executado.

**Aceite:** reproduzir cada falha em até três execuções, registrar exit code e separar falha de código de ausência de dependência/serviço; nenhum threshold é reduzido.

### RA72-02 — Criar índice documental canônico

**Problemas:** documentos Phase 0/1.1/2 contradizem a arquitetura Phase 3; existem múltiplos relatórios e artefatos não rastreados.

**Aceite:** índice com autoridade, status, `as-of`, SHA, predecessor, links e classificação `CURRENT/HISTORICAL/NOT_RUN`; verificador detecta divergências de fase.

### RA72-03 — Congelar scorecard e manifesto de evidências

**Aceite:** matriz dos 27 itens, comando completo, ambiente, SHA/tree, exit code, artefato, validade e limitações; relatório histórico não é sobrescrito.

## M1 — Integridade e segurança

### RA72-04 — Corrigir integridade cross-scope no banco

**Problemas:** FKs separadas em chunks, jobs, conversas e mensagens.

**Aceite:** migração versionada com constraints compostas, backfill/rollback documentados e PostgreSQL rejeitando associações cross-tenant/workspace/collection/document/conversation.

### RA72-05 — Remover `password_plain` persistente

**Aceite:** nenhuma senha reversível em stores persistentes; criação, login, troca e fixtures continuam funcionando; busca automatizada falha se o campo reaparecer.

### RA72-06 — Tornar worker timeout-safe

**Problemas:** thread daemon pode continuar após timeout.

**Aceite:** handler expirado não publica, confirma, altera store ou ultrapassa lease; testes cobrem timeout, lease perdido, retry e side effect tardio.

### RA72-07 — Garantir auditoria de mutações críticas

**Problemas:** delete emite auditoria após mutação e reindex não emite auditoria.

**Aceite:** delete/reindex/config/admin usam política uniforme, com falha auditável, estado reconciliável e testes de sink indisponível.

### RA72-08 — Endurecer autorização e endpoints operacionais

**Aceite:** `permission_overrides` possui schema fechado; alvo administrativo é validado explicitamente; `/metrics` e readiness têm boundary documentado e testes de exposição.

## M2 — Gates locais

### RA72-09 — Corrigir instalação e gates do frontend

**Problemas:** `vitest` declarado, mas ausente no ambiente atual.

**Aceite:** `npm ci` reproduz dependências; typecheck, build, unit coverage e E2E executam sem módulos ausentes; lockfile e `node_modules` são coerentes.

### RA72-10 — Fechar benchmark, E2E e acessibilidade

**Aceite:** evidence aprovada no benchmark; matriz Playwright completa; `axe.run`, modal, teclado, foco e estados responsivos passam sem timeout ou erro de API.

### RA72-11 — Eliminar corrida de ingestão/telemetria

**Aceite:** `api16-full` passa em execução isolada, repetida e paralela; evento `worker.ingestion.published` tem ordem, idempotência e boundedness testadas.

### RA72-12 — Unificar gates raiz e coverage

**Aceite:** `make lint`, `typecheck`, `build` e `ci` cobrem API, worker e web; thresholds de coverage são obrigatórios e falham abaixo da barra.

### RA72-13 — Reduzir warnings e corrigir contratos frágeis

**Aceite:** warnings deprecados são removidos ou registrados com owner/versão-alvo; retry multipart, fallback de paginação e cleanup de upload têm testes de falha.

## M3 — Reprodutibilidade operacional

### RA72-14 — Reconciliar toolchain, Compose e CI

**Aceite:** uma fonte canônica de versões; checks detectam drift; instalação local e CI usam as mesmas dependências e pins.

### RA72-15 — Preparar observabilidade e release evidence

**Aceite:** readiness, shutdown, métricas, traces, alertas e manifesto de release têm comandos e artefatos explícitos; candidato limpo é requisito, não inferência.

## M4 — Runtime integrado

### RA72-16 — Executar golden path distribuído

**Aceite:** upload → object store → job → worker → index → retrieval → evidence → resposta → histórico, com provider, Qdrant, Redis e PostgreSQL reais em ambiente descartável; matriz tenant A/B sem leakage.

**Bloqueio:** requer autorização e infraestrutura externa.

### RA72-17 — Testar outbox, restart e recuperação

**Aceite:** falha de sink, restart, retry, concorrência e dead-letter não produzem perda ou duplicação silenciosa; evidência vinculada ao mesmo SHA.

## M5 — Resiliência e promoção

### RA72-18 — Medir backup, restore e RPO/RTO

**Aceite:** seed → backup → destruição controlada → restore → verificação de checksums, contagens, ACLs e reidratação; métricas RPO/RTO registradas.

### RA72-19 — Medir carga, chaos e soak

**Aceite:** p50/p95/p99, throughput, memória, filas, custo, falhas injetadas e estabilidade prolongada comparados aos SLOs; falhas reabrem itens do backlog.

### RA72-20 — Revisão independente e decisão Go/No-Go

**Aceite:** CI same-SHA, revisão independente, scorecard atualizado, evidências não expiradas/tamperadas e autoridade formal registrada. Média de notas não substitui gates.

## Estado atual dos itens

| Estado | Itens | Evidência |
|---|---|---|
| IMPLEMENTADO/VALIDADO | RA72-01, RA72-02, RA72-03, RA72-06, RA72-07, RA72-08, RA72-09 | testes focados, gates raiz, índice e roadmap atualizados |
| PARCIAL/BLOQUEADO | RA72-04, RA72-05, RA72-10, RA72-11, RA72-12, RA72-13 | dependem de PostgreSQL, E2E/runtime ou plugin `pytest-cov` local |
| PENDENTE EXTERNO | RA72-14 a RA72-20 | exigem ambiente, autorização ou revisão independente |

A classificação acima não é uma aprovação de promoção: gates externos ausentes continuam bloqueando `GO`.

## Rastreabilidade

| Achado | Itens |
|---|---|
| Drift documental | RA72-02, RA72-03, RA72-14 |
| Frontend quebrado | RA72-01, RA72-09, RA72-10 |
| Integridade multi-tenant | RA72-04, RA72-08, RA72-16 |
| Worker e concorrência | RA72-06, RA72-11, RA72-17 |
| Auditoria/observabilidade | RA72-07, RA72-08, RA72-15, RA72-17 |
| Benchmark e testes | RA72-01, RA72-10, RA72-12, RA72-13 |
| Runtime e promoção | RA72-16 a RA72-20 |
