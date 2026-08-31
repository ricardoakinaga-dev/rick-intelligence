# PHASE 4 — SPRINT 4.2: Smoke Tests

## Objetivo
Criar e executar smoke tests estáveis para fluxos críticos.

## Escopo
- Smoke test suite
- Critical flows covered
- Stable execution
- CI integration

## Tasks

### Task 4.2.1: Smoke Test Suite
**O QUE:** Criar suite de smoke tests
**ONDE:** tests/smoke/
**COMO:** Testes de fluxos críticos: login, upload, search, query
**DEPENDÊNCIA:** Sprint 1.1 (Admin CRUD)
**CRITÉRIO DE PRONTO:** Suite com testes para fluxos críticos

### Task 4.2.2: Critical Flows Coverage
**O QUE:** Garantir que fluxos críticos estão cobertos
**ONDE:** tests/smoke/
**COMO:** Login → Upload → Index → Search → Query
**DEPENDÊNCIA:** Task 4.2.1
**CRITÉRIO DE PRONTO:** Todos os fluxos têm smoke test

### Task 4.2.3: Stable Execution
**O QUE:** Garantir que smoke tests executam de forma estável
**ONDE:** tests/smoke/
**COMO:** Isolamento, retries configurados, timeout
**DEPENDÊNCIA:** Task 4.2.2
**CRITÉRIO DE PRONTO:** Smoke tests estáveis (sem flakiness)

### Task 4.2.4: CI Integration
**O QUE:** Integrar smoke tests no CI pipeline
**ONDE:** .github/workflows/ci.yaml
**COMO:** Step de smoke tests antes de deployment
**DEPENDÊNCIA:** Task 4.2.3
**CRITÉRIO DE PRONTO:** CI falha se smoke tests falharem

## Riscos
- Smoke tests podem ser frágeis se dependentes de external services (mitigação: mocking)

## Critérios de Validação
- [ ] Suite de smoke tests criada
- [ ] Fluxos críticos cobertos
- [ ] Smoke tests estáveis
- [ ] CI integration working

## Status
⚪ PENDENTE