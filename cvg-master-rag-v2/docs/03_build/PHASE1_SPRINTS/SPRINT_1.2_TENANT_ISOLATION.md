# PHASE 1 — SPRINT 1.2: Tenant Isolation

## Objetivo
Implementar e validar isolamento completo entre workspaces.

## Escopo
- Filtro de workspace_id em todas as queries
- Validação de isolamento
- Proteção de tenant bootstrap

## Tasks

### Task 1.2.1: Workspace Filter on Queries
**O QUE:** Adicionar filtro workspace_id em todas as operações de dados
**ONDE:** src/*/service.py (todos os módulos)
**COMO:** Filtro obrigatório em queries
**DEPENDÊNCIA:** Sprint 1.1 (Admin CRUD)
**CRITÉRIO DE PRONTO:** Dados filtrados por workspace_id corretamente

### Task 1.2.2: Bootstrap Tenant Protection
**O QUE:** Impedir deletar tenant com dados ou usuários ativos
**ONDE:** src/admin/service.py
**COMO:** Validação antes de DELETE /tenants/{id}
**DEPENDÊNCIA:** Sprint 1.1
**CRITÉRIO DE PRONTO:** Tentativa de deletar tenant ativo retorna 400

### Task 1.2.3: Isolation Verification
**O QUE:** Verificar que dados não vazam entre workspaces
**ONDE:** Tests de integração
**COMO:** Criar 3 tenants, ops em cada, verificar não vazamento
**DEPENDÊNCIA:** Workspace filter
**CRITÉRIO DE PRONTO:** Suite TKT-010 passa

## Riscos
- Filtro pode ser esquecido em alguma query (mitigação: code review + tests)

## Critérios de Validação
- [ ] Filtro workspace_id em todas as queries
- [ ] Tenant bootstrap protegido
- [ ] Suite TKT-010 passa sem vazamento

## Status
⚪ PENDENTE