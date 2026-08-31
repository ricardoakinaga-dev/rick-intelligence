# PHASE 2 — SPRINT 2.3: Evaluation Framework

## Objetivo
Criar dataset real e framework de avaliação com hit rate.

## Escopo
- Dataset de 20+ perguntas reais
- Hit rate calculation (top-1, top-3, top-5)
- Evaluation runner
- Metrics aggregation

## Tasks

### Task 2.3.1: Real Questions Dataset
**O QUE:** Criar dataset com 20+ perguntas reais do domínio
**ONDE:** src/evaluation/dataset.py
**COMO:** Perguntas com ground truth (chunk_ids esperados)
**DEPENDÊNCIA:** Sprint 2.2 (Query/RAG)
**CRITÉRIO DE PRONTO:** Dataset com 20+ perguntas + ground truth

### Task 2.3.2: Hit Rate Calculation
**O QUE:** Calcular hit rate top-1, top-3, top-5
**ONDE:** src/evaluation/metrics.py
**COMO:** Comparar chunk_ids retornados vs expected
**DEPENDÊNCIA:** Task 2.3.1
**CRITÉRIO DE PRONTO:** Hit rates calculados corretamente

### Task 2.3.3: Evaluation Runner
**O QUE:** Framework para executar avaliação completa
**ONDE:** src/evaluation/runner.py
**COMO:** Loop sobre dataset, execução de queries, cálculo de métricas
**DEPENDÊNCIA:** Task 2.3.2
**CRITÉRIO DE PRONTO:** Runner executável com output de métricas

### Task 2.3.4: Tenant-Scoped Metrics
**O QUE:** Agregar métricas por tenant
**ONDE:** src/evaluation/aggregator.py
**COMO:** Group by workspace_id para métricas por tenant
**DEPENDÊNCIA:** Task 2.3.3
**CRITÉRIO DE PRONTO:** Métricas agregadas por tenant

### Task 2.3.5: Evaluation Gate
**O QUE:** Validar que hit_rate_top5 >= 60%
**ONDE:** src/evaluation/gate.py
**COMO:** Verificação automática após runner
**DEPENDÊNCIA:** Task 2.3.4
**CRITÉRIO DE PRONTO:** Gate indica PASS/FAIL baseado em threshold

## Riscos
- Dataset pode não representar realidade (mitigação: perguntas de usuários reais)

## Critérios de Validação
- [ ] Dataset com 20+ perguntas reais
- [ ] Hit rate calculation correto
- [ ] Evaluation runner executável
- [ ] Tenant-scoped metrics working
- [ ] Evaluation gate valida hit_rate_top5 >= 60%

## Status
⚪ PENDENTE