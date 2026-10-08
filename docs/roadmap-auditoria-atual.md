# Roadmap de remediação — Snapshot histórico

> **HISTORICAL / SUPERSEDED em 2026-10-01.** Preservado como snapshot, não é a sequência atual. Consulte o [roadmap de 2026-10-01](roadmap-auditoria-2026-10-01.md) e o [relatório correspondente](reports/relatorio-auditoria-geral-2026-10-01.md).

**Base histórica:** [relatório de auditoria](reports/relatorio-auditoria-state-of-art-2026-09-07.md) e auditoria anterior realizada no checkout local.
**Nota de referência:** 72/100.
**Estado:** `STATE_OF_ART_CANDIDATE / NO-GO`.
**Objetivo:** elevar a qualidade verificável, sem confundir testes locais com evidência de produção.

## Princípios

1. Corrigir primeiro integridade, segurança e bloqueadores funcionais.
2. Não reduzir thresholds para transformar falha em sucesso.
3. Toda entrega deve registrar comando, exit code, SHA/tree, artefato e limitações.
4. `NOT_RUN`, `BLOCKED_EXTERNAL` e `INCONCLUSIVO` não são PASS.
5. Nenhum banco, provider, deploy ou operação destrutiva deve ser executado sem autorização explícita.

## Marcos

| Marco | Foco | Resultado esperado | Dependência |
|---|---|---|---|
| M0 | Baseline e rastreabilidade | falhas reproduzidas, escopo congelado e autoridade documental definida | nenhuma |
| M1 | Integridade e segurança | constraints cross-scope, worker seguro e auditoria confiável | M0 |
| M2 | Gates locais | API, worker, benchmark e web reproduzíveis e verdes | M1 |
| M3 | Reprodutibilidade operacional | toolchain, CI, Compose e observabilidade coerentes | M2 |
| M4 | Runtime integrado | golden path com Postgres, Redis, Qdrant, object store e provider | M3 + autorizações |
| M5 | Resiliência e promoção | restore, RPO/RTO, carga, chaos, soak e revisão independente | M4 + autorizações |

## M0 — Baseline e rastreabilidade

- Reproduzir `web-validate`, ausência de `vitest`, falhas E2E/axe e timeout do worker.
- Fixar matriz atual de notas, comandos e artefatos.
- Criar índice documental canônico com status, `as-of`, SHA, autoridade e predecessor.
- Classificar documentos Phase 0/1.1/2 como históricos quando contradisserem o estado Phase 3.

**Saída:** baseline reproduzível e documentação sem autoridade concorrente.

## M1 — Integridade e segurança

- Implementar constraints compostas para documentos, chunks, jobs, conversas e mensagens.
- Executar testes negativos cross-tenant/workspace/collection em PostgreSQL descartável.
- Remover `password_plain` de qualquer store persistente.
- Corrigir timeout do worker para impedir side effects após expiração.
- Tornar delete e reindex auditáveis antes/depois da mutação conforme ADR-008.
- Validar `permission_overrides` por schema fechado e aplicar escopo na rota administrativa.
- Definir boundary protegido para `/metrics` e `/health/ready`.

**Gate M1:** nenhuma falha P0/P1 de integridade ou segurança sem disposição formal.

## M2 — Gates locais

- Instalar dependências lockadas e corrigir `apps/web` para que typecheck/build/coverage executem.
- Corrigir benchmark de evidence sem relaxar a barra.
- Corrigir `axe.run`, foco, teclado e confirmação do modal; concluir a matriz Playwright.
- Eliminar a corrida de `worker.ingestion.published`.
- Fazer `make typecheck`, `make build` e `make ci` cobrirem explicitamente API, worker e web.
- Definir thresholds obrigatórios de coverage e tratar warnings deprecados.

**Gate M2:** `api-security`, `api16-full`, benchmark e `web-validate` verdes em execução reproduzível.

## M3 — Reprodutibilidade operacional

- Definir uma única fonte de versões entre `toolchain.json`, Compose e CI.
- Garantir instalação local equivalente ao CI, incluindo hashes quando aplicável.
- Separar credenciais de bootstrap e remover defaults perigosos.
- Validar readiness, shutdown, métricas, traces e alertas em laboratório isolado.
- Gerar manifesto de release vinculado ao mesmo SHA/tree limpo.

**Gate M3:** candidato limpo, artefatos íntegros e checks estáticos/reprodutíveis verdes.

## M4 — Runtime integrado

Com autorização, executar em ambiente descartável:

`upload → object store → fila → worker → parse/chunk/embed → Qdrant → retrieval → evidence → Professor → decision → resposta → histórico`.

Incluir isolamento tenant A/B, acesso negado, fonte insuficiente, restart, retry, outbox e reconciliação.

**Gate M4:** evidência commit-bound de todos os componentes; nenhum fallback local contado como runtime de produção.

## M5 — Resiliência e promoção

- Medir backup/restore, RPO/RTO e reidratação.
- Executar carga, p50/p95/p99, throughput, memória, custo e limites.
- Executar chaos e soak com falhas controladas.
- Obter revisão independente de segurança, arquitetura, operações e web.
- Recalcular o scorecard e emitir decisão Go/No-Go.

**Gate M5:** nenhum bloqueador alto, evidências frescas e autoridade de promoção registrada.

## Estado de implementação desta rodada

- **Concluído localmente:** baseline documental (M0), timeout/lease guard do worker, auditoria prévia de reindex, logging sanitizado de falhas de auditoria de login, modelo fechado de `permission_overrides` e instalação das dependências web.
- **Validado:** `make api-security`, `make api16-worker`, `make api16-root`, `make validate`, `make lint`, `make typecheck`, `make build` e `make web-coverage` passaram.
- **Bloqueado localmente:** `api-coverage` e `worker-coverage` exigem `pytest-cov` instalado no interpretador usado pelo Makefile; a dependência está declarada em `requirements/test.lock`, mas não está instalada neste ambiente.
- **Ainda externo:** PostgreSQL/Redis/Qdrant/object storage/provider reais, restore, carga, chaos, soak e observabilidade distribuída.

## Caminho crítico

`M0 → M1 → M2 → M3 → M4 → M5`

Preparação documental e correções locais podem ocorrer em paralelo, mas runtime e promoção continuam bloqueados até os gates anteriores.
