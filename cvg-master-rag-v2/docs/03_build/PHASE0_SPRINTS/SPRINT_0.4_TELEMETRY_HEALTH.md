# PHASE 0 — SPRINT 0.4: Telemetry + Health

## Objetivo
Implementar logging estruturado com request_id e health check robusto.

## Escopo
- Logging estruturado
- request_id propagation
- GET /health endpoint
- Health checks para dependências

## Tasks

### Task 0.4.1: Structured Logging
**O QUE:** Implementar logging estruturado em formato JSON
**ONDE:** src/telemetry/logging.py
**COMO:** Python logging com JSON formatter
**DEPENDÊNCIA:** Nenhuma
**CRITÉRIO DE PRONTO:** Logs em formato JSON com timestamp, level, request_id, workspace_id

### Task 0.4.2: Request ID Middleware
**O QUE:** Middleware que gera e propaga request_id
**ONDE:** src/telemetry/middleware.py
**COMO:** UUID gerado no entry point, armazenado em context vars
**DEPENDÊNCIA:** Nenhuma
**CRITÉRIO DE PRONTO:** request_id gerado para cada request e propagado

### Task 0.4.3: Health Check Endpoint
**O QUE:** Implementar GET /health com status de dependências
**ONDE:** src/telemetry/health.py
**COMO:** FastAPI route com checks para Qdrant, OpenAI, filesystem
**DEPENDÊNCIA:** Nenhuma
**CRITÉRIO DE PRONTO:** /health retorna 200 com status de cada dependência

### Task 0.4.4: Workspace ID in Context
**O QUE:** Adicionar workspace_id ao contexto de logging
**ONDE:** src/telemetry/logging.py
**COMO:** Context var para workspace_id extraído da sessão
**DEPENDÊNCIA:** Session persistence
**CRITÉRIO DE PRONTO:** workspace_id presente em todos os logs de operations

## Riscos
- Overhead de logging em produção (mitigação: reduced logging mode)

## Critérios de Validação
- [ ] Logs em formato JSON estruturado
- [ ] request_id em todo log entry
- [ ] /health retorna status de Qdrant, OpenAI, filesystem
- [ ] workspace_id em logs quando disponível

## Status
⚪ PENDENTE