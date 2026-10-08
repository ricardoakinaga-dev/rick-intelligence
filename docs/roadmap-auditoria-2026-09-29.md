# Roadmap de correções e melhorias — Auditoria 29/09/2026

**Versão:** RM29-v1  
**Origem:** [relatório da auditoria](reports/relatorio-auditoria-geral-2026-09-29.md), nota técnica 80/100.  
**Backlog executável:** [backlog da auditoria](backlog-auditoria-2026-09-29.md).  
**Histórico:** os roadmaps de 27/09 e anteriores permanecem históricos; este documento adiciona os gaps confirmados nesta rodada.

## Objetivo

Elevar o candidato de `STATE_OF_ART_CANDIDATE / NO-GO` para um candidato tecnicamente verificável, corrigindo primeiro integridade e segurança, depois estabilizando os gates locais e, somente com autorizações D01–D07, produzindo evidência operacional distribuída. Nenhuma média de notas substitui um gate obrigatório.

## Princípios

1. Não alterar, apagar ou reescrever evidência histórica.
2. Separar correção de código, validação local e prova runtime.
3. Toda tarefa deve registrar candidato/tree, arquivos, comando, exit code, artefato sanitizado, revisão e recuperação.
4. `NOT_RUN`, `BLOCKED_EXTERNAL`, benchmark falho ou E2E inconclusivo não são PASS.
5. Não executar provider, banco, deploy ou operação destrutiva sem autorização correspondente.

## Marcos

| Marco | Foco | Saída verificável | Dependência |
|---|---|---|---|
| **M0 — Baseline e desenho** | Congelar escopo, reproduzir falhas e desenhar constraints | matriz de requisitos, reproduções e plano de migração | nenhuma |
| **M1 — Integridade e segurança** | FKs compostas, isolamento, segredos e autorização | migration segura + testes negativos cross-scope | M0 |
| **M2 — Gates locais verdes** | benchmark, E2E/axe, intermitência, warnings, coverage e gates raiz | checks locais determinísticos e cobertura declarada | M0; M1 para regressões de dados |
| **M3 — Reprodutibilidade e operação preparada** | toolchain, CI, Compose, credenciais, observabilidade e autoridade | candidato limpo, manifests coerentes e executores explícitos | M2 |
| **M4 — Runtime integrado** | golden path, outbox, Redis/Qdrant/S3/provider e telemetria real | evidência commit-bound do fluxo completo | D01–D04 e M3 |
| **M5 — Resiliência e promoção** | restore, RPO/RTO, carga, chaos, soak, revisão independente | métricas medidas e decisão Go/No-Go rastreável | D05–D07 e M4 |

## Sequência recomendada

### M0 — Baseline e desenho

- Criar reproduções determinísticas para a falha de benchmark, falhas Playwright/axe e evento de ingestão intermitente.
- Inventariar os consumidores das colunas denormalizadas e definir a estratégia de migration/backfill/rollback.
- Fixar matriz 26 itens × evidência atualizada, sem confundir os roadmaps históricos.

### M1 — Integridade e segurança

- Adicionar FKs compostas e constraints coerentes para `chunks`, `ingestion_jobs`, `conversations` e `messages`.
- Validar isolamento com tentativas de escrita/leitura cross-tenant, inclusive provider PostgreSQL.
- Remover persistência de `password_plain`; usar hash em todos os stores persistentes ou tornar explicitamente efêmero o modo de teste.
- Fazer a rota administrativa impor e testar o escopo do alvo, não apenas delegá-lo ao provider.

### M2 — Gates locais verdes

- Corrigir o fixture/threshold do benchmark sem reduzir a barra.
- Corrigir o uso de `axe.run`, o fluxo de confirmação/teclado e concluir a matriz Playwright nas três larguras.
- Reproduzir e eliminar a corrida `worker.ingestion.published`; executar `api16-full` sem paralelismo concorrente.
- Cobrir warnings deprecatórios e estabelecer threshold de coverage por suíte.
- Fazer `make lint`, `typecheck` e `build` incluírem explicitamente API, worker e `apps/web`.

### M3 — Reprodutibilidade e operação preparada

- Alinhar `toolchain.json` e Compose; definir uma fonte canônica de versões.
- Pin de todas as GitHub Actions e lock/hash das dependências locais conforme CI.
- Separar credencial root do bootstrap MinIO; revisar Jaeger in-memory e secrets.
- Conectar ou documentar explicitamente donos/executores das lanes `lab-readiness`, `independent-reviews` e `production-runtime`.
- Confirmar composição, readiness, métricas, traces, alertas e shutdown em laboratório isolado.

### M4 — Runtime integrado

Com D01–D04 aprovados, executar em ambiente descartável: upload → objeto → job → worker → parse/chunk/embed → Qdrant → publish → retrieval → evidence → Professor → decision → resposta citada → histórico. Exercitar acesso negado, fonte insuficiente, restart, reconciliação do outbox e isolamento multi-tenant.

### M5 — Resiliência e promoção

Com D05–D07 aprovados, medir restore/RPO/RTO, p50/p95/p99, throughput, filas, memória, chaos e soak. Reexecutar CI same-SHA, obter revisão independente, recalcular as 26 notas e registrar Go/No-Go sem autoaprovação.

## Critérios de saída

- Zero achado alto de integridade/segurança sem disposição aprovada.
- `api15-full`, `api16-full`, benchmark e matriz web verdes, ou falhas explicitamente bloqueadoras.
- Candidate tree limpo e evidência vinculada ao mesmo SHA/tree.
- Runtime integrado, restore, capacidade, chaos, soak, revisão e autoridade comprovados antes de qualquer promoção.

## Caminho crítico

`M0 → M1 → M2 → M3 → M4 → M5`. Preparação documental de M3/M4 pode ocorrer em paralelo, mas não fecha gates sem as dependências e autorizações humanas correspondentes.
