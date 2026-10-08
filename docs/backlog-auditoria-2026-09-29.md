# Backlog executável — Auditoria 29/09/2026

**Versão:** BL29-v1  
**Origem:** [relatório](reports/relatorio-auditoria-geral-2026-09-29.md) e [roadmap](roadmap-auditoria-2026-09-29.md).  
**Estado:** backlog proposto; não altera o estado canônico em `.agent/` nem encerra tarefas históricas Q17/Q24/R27.

## Convenções

- **P0:** segurança, isolamento ou gate bloqueador.
- **P1:** produto, integração ou evidência necessária para promoção.
- **P2:** qualidade, manutenção e melhoria operacional.
- **P/M/G:** porte relativo, não prazo.
- D01–D07 são decisões externas já usadas pelo projeto; preparação local pode avançar, mas execução dependente permanece bloqueada sem autorização.
- Aceite comum: reprodução, mudança mínima, teste positivo/negativo, regressão, diff revisado, candidato/tree, comando, exit code, artefato sanitizado, limitações e plano de recuperação.

## Fila priorizada

| ID | Marco | Prioridade | Porte | Dependências | Decisão |
|---|---|---:|---:|---|---|
| RA29-01 | M0 | P0 | M | — | — |
| RA29-02 | M0 | P0 | G | RA29-01 | — |
| RA29-03 | M1 | P0 | G | RA29-02 | D01/D02 |
| RA29-04 | M1 | P0 | M | RA29-02 | — |
| RA29-05 | M1 | P0 | M | RA29-02 | D02 |
| RA29-06 | M2 | P1 | M | RA29-02 | — |
| RA29-07 | M2 | P1 | G | RA29-02 | — |
| RA29-08 | M2 | P1 | M | RA29-02 | — |
| RA29-09 | M2 | P1 | M | RA29-07 | — |
| RA29-10 | M2 | P2 | M | RA29-02 | — |
| RA29-11 | M2 | P2 | M | RA29-02 | — |
| RA29-12 | M3 | P2 | M | RA29-02 | — |
| RA29-13 | M3 | P2 | M | RA29-02 | — |
| RA29-14 | M3 | P1 | M | RA29-06, RA29-12 | — |
| RA29-15 | M3 | P1 | M | RA29-12 | D07 |
| RA29-16 | M4 | P1 | G | RA29-03, RA29-14, RA29-15 | D01–D04 |
| RA29-17 | M4 | P1 | M | RA29-16 | D01/D02 |
| RA29-18 | M5 | P1 | G | RA29-16 | D01/D02/D05 |
| RA29-19 | M5 | P1 | G | RA29-18 | D03/D05 |
| RA29-20 | M5 | P0 | G | RA29-18/19 | D07 |

## M0 — Baseline e desenho

### RA29-01 — Reproduzir falhas e congelar baseline

**Origem:** benchmark falho, E2E inconclusivo e intermitência `worker.ingestion.published`.  
**Entregar:** fixtures/reproduções isoladas, matriz de comandos e baseline do candidato atual.  
**Aceite:** cada falha reproduzida ou classificada como não reproduzível após três execuções; nenhum teste enfraquecido; árvore e artefatos identificados.

### RA29-02 — Desenhar migração de integridade cross-scope

**Origem:** `infrastructure/migrations/0002_product_schema.sql:115-153,188-201`.  
**Entregar:** inventário de dados, constraints compostas para documento/escopo, jobs/documento, conversation/membership, collection e message/conversation; plano de backfill, validação, rollback e compatibilidade.  
**Aceite:** consultas e writers afetados mapeados; estados inválidos detectáveis; migração não mascara ou apaga dados; testes negativos definidos antes do BUILD.

## M1 — Integridade e segurança

### RA29-03 — Implementar constraints compostas e isolamento DB

**Origem:** gaps de FKs separados em chunks, jobs e mensagens.  
**Entregar:** migration versionada e atualização de stores/upserts para respeitar escopo.  
**Aceite:** PostgreSQL rejeita associações cross-tenant/workspace/collection/document/conversation; dados válidos continuam inserindo, lendo e migrando; rollback documentado.  
**Prova:** testes de migration e matriz negativa em PostgreSQL descartável; execução instalada só com D02.

### RA29-04 — Eliminar `password_plain` persistente

**Origem:** `apps/api/src/services/identity_service.py:224-227`.  
**Entregar:** hash também em stores persistentes de dev/test, ou store explicitamente efêmero sem dump/arquivo.  
**Aceite:** busca no repositório e testes não encontram senha reversível persistida; login, criação e alteração de senha continuam funcionando; fixtures usam valores não reutilizáveis.

### RA29-05 — Impor escopo na rota administrativa

**Origem:** atualização administrativa delega a validação ao provider.  
**Entregar:** validação explícita de tenant/workspace do alvo e contrato uniforme para providers in-memory/PostgreSQL.  
**Aceite:** alvo de outro escopo retorna negativa segura sem mutação; testes de autorização passam em todos os providers.

## M2 — Gates locais verdes

### RA29-06 — Corrigir benchmark de evidência

**Origem:** `scripts/phase15/benchmark.py` falha com `benchmark fixture did not produce approved evidence`.  
**Entregar:** fixture determinístico, contrato de aprovação e thresholds justificáveis.  
**Aceite:** caso aprovado produz evidence aprovado; casos sem cobertura/sem fonte continuam reprovados; `api15-benchmark` e `api15-full` passam sem reduzir a barra.

### RA29-07 — Corrigir matriz Playwright/axe e confirmação

**Origem:** `axe.run arguments are invalid` e timeout em `visual-matrix.spec.ts` no modal/teclado.  
**Entregar:** chamada axe válida, lifecycle do modal determinístico, foco/descrição acessíveis e correções de reflow.  
**Aceite:** matriz 321 testes completa nas larguras configuradas; nenhum erro de axe/timeout; evidências visuais e acessibilidade sanitizadas.

### RA29-08 — Eliminar corrida de telemetria da ingestão

**Origem:** `api16-full` teve 1 falha em 751 e reexecução isolada passou.  
**Entregar:** sincronização/contrato de publicação de eventos sem depender de timing incidental.  
**Aceite:** teste isolado e execução repetida/paralela passam; eventos têm ordem e boundedness documentados; `api16-full` verde.

### RA29-09 — Completar gates raiz

**Origem:** `make lint/typecheck/build` não cobre integralmente `apps/web`, API e worker.  
**Entregar:** alvos raiz chamam as verificações canônicas ou renomear/documentar claramente os escopos.  
**Aceite:** um gate raiz detecta falha representativa web/API/Python; comandos e CI usam o mesmo contrato.

### RA29-10 — Reduzir warnings deprecatórios

**Origem:** 424 warnings em 751 testes de API, incluindo HTTPX/Starlette.  
**Entregar:** atualizar usos deprecados ou registrar disposição com issue/versão alvo.  
**Aceite:** warnings conhecidos eliminados ou explicitamente classificados; não ocultar warnings via filtros globais; suíte permanece verde.

### RA29-11 — Definir coverage mínimo e reprodutibilidade Python

**Origem:** ausência de threshold obrigatório e manifests locais sem equivalência completa ao lock CI.  
**Entregar:** threshold por suíte, relatório versionado/sanitizado e instalação local/CI alinhadas com hashes quando aplicável.  
**Aceite:** cobertura baixa falha o gate; dependências resolvem de forma reproduzível; exclusões justificadas.

## M3 — Reprodutibilidade e operação preparada

### RA29-12 — Reconciliar toolchain e Compose

**Origem:** drift Qdrant/Redis entre `toolchain.json` e Compose.  
**Entregar:** fonte canônica, versões alinhadas e validação que detecta drift.  
**Aceite:** referências únicas e `make compose-static`/toolchain check verdes.

### RA29-13 — Hardening de workflows e MinIO

**Origem:** actions sem pin uniforme, root credential no bootstrap e Jaeger in-memory.  
**Entregar:** pins exatos, bootstrap scoped, secrets separados e disposição explícita de persistência de tracing.  
**Aceite:** scan estático rejeita action não pinada; init não recebe root; staging mantém o comportamento documentado.

### RA29-14 — Integrar observabilidade e readiness reais

**Origem:** observabilidade local sem prova de collector, alertas, traces/SLO e lifecycle API.  
**Entregar:** laboratório com OTLP/Prometheus/Jaeger, health/readiness, shutdown e alertas observáveis.  
**Aceite:** erro, fila, latência e trace correlacionam API/worker; alertas e SLO possuem teste de entrega; sem alegar produção.

### RA29-15 — Conectar lanes de autoridade

**Origem:** `triple_aaa_verify.py` com `command=None` em lanes obrigatórias.  
**Entregar:** executor/produtor real ou processo humano documentado, dono, formato, validade e fonte de aceite.  
**Aceite:** `make triple-aaa-verify` rejeita ausência/stale/tampered e nunca trata `command=None` ambíguo como PASS; D07 registrado.

## M4 — Runtime integrado

### RA29-16 — Executar golden path distribuído

**Origem:** ausência de integração API+worker+PostgreSQL+Redis+Qdrant+S3+provider.  
**Entregar:** upload → objeto → job → worker → index → retrieval → evidence → resposta citada → histórico, com cenário negativo e isolamento.  
**Aceite:** todos os serviços e versões identificados; lineage, idempotência, permissões e resposta verificáveis; evidência vinculada ao mesmo candidato.  
**Decisão:** D01–D04.

### RA29-17 — Testar outbox sob falha e restart

**Origem:** reconciliação administrativa ainda sem prova ponta a ponta.  
**Entregar:** sink indisponível, restart, concorrência, retry/backoff e dead-letter no ambiente real.  
**Aceite:** sem perda/duplicação silenciosa; API reflete estado; recuperação documentada.

## M5 — Resiliência e promoção

### RA29-18 — Medir restore e RPO/RTO

**Origem:** área 24 NOT_RUN/BLOCKED_EXTERNAL.  
**Entregar:** seed → backup → destruição controlada → restore → verificações/digests.  
**Aceite:** valores medidos, dados e permissões coerentes, falhas detectadas; `phase3-restore-runtime` executado com autorização D01/D02/D05.

### RA29-19 — Medir capacidade, chaos e soak

**Origem:** ausência de números operacionais reais.  
**Entregar:** p50/p95/p99, throughput, primeiro token, memória, filas, falhas injetadas e janela de estabilidade.  
**Aceite:** budgets D03/D05 comparados a resultados, efeitos duplicados/corrupção ausentes ou bloqueadores reabertos.

### RA29-20 — Revisão independente, reauditoria e decisão

**Origem:** promoção NO-GO e ausência de revisão/autoridade same-SHA.  
**Entregar:** CI same-SHA, revisão independente, nova auditoria 26 itens, pacote íntegro e decisão Go/No-Go.  
**Aceite:** nenhum gate alto pendente, evidências não expiradas/tamperadas, assinatura/autoridade D07 registrada; promoção automática ou por média é rejeitada.

## Rastreabilidade

| Achado do relatório | Tarefas |
|---|---|
| Integridade cross-tenant/cross-workspace | RA29-02, RA29-03, RA29-05 |
| `password_plain` | RA29-04 |
| Benchmark falho | RA29-01, RA29-06 |
| E2E/axe/modal | RA29-01, RA29-07 |
| Intermitência de ingestão | RA29-01, RA29-08 |
| Gate raiz/coverage/warnings | RA29-09, RA29-10, RA29-11 |
| Toolchain/CI/MinIO/observabilidade | RA29-12, RA29-13, RA29-14 |
| Lanes sem executor | RA29-15 |
| Runtime integrado/outbox | RA29-16, RA29-17 |
| Restore/capacidade/chaos/soak | RA29-18, RA29-19 |
| Revisão e promoção | RA29-20 |
