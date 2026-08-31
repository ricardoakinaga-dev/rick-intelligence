# PHASE 3 — SPRINT 3.1: Advanced Tracing

## Objetivo
Implementar tracing completo com request_id ponta a ponta.

## Escopo
- Distributed tracing
- Span creation
- Trace propagation
- Trace storage

## Tasks

### Task 3.1.1: Request ID Propagation
**O QUE:** Garantir request_id em todos os pontos do fluxo
**ONDE:** src/telemetry/tracing.py
**COMO:** Context propagation entre módulos
**DEPENDÊNCIA:** Sprint 0.4 (Telemetry)
**CRITÉRIO DE PRONTO:** request_id presente do entry ao response

### Task 3.1.2: Span Creation
**O QUE:** Criar spans para cada operação significativa
**ONDE:** src/*/instrumentation.py (cada módulo)
**COMO:** OpenTelemetry spans
**DEPENDÊNCIA:** Task 3.1.1
**CRITÉRIO DE PRONTO:** Spans criados para retrieval, query, ingestion

### Task 3.1.3: Cross-Module Trace
**O QUE:** Propagar trace entre módulos (auth → retrieval → query)
**ONDE:** src/telemetry/tracing.py
**COMO:** Context carrier entre módulos
**DEPENDÊNCIA:** Task 3.1.2
**CRITÉRIO DE PRONTO:** Trace completo ponta a ponta

### Task 3.1.4: Trace Storage
**O QUE:** Armazenar traces para análise
**ONDE:** src/telemetry/storage.py
**COMO:** Filesystem ou OTLP exporter
**DEPENDÊNCIA:** Task 3.1.3
**CRITÉRIO DE PRONTO:** Traces retrievable para debug

## Riscos
- Overhead de tracing em produção (mitigação: sampling rate configurável)

## Critérios de Validação
- [ ] request_id propagation working
- [ ] Spans criados para operações principais
- [ ] Cross-module trace completo
- [ ] Traces armazenados e retrievable

## Status
⚪ PENDENTE