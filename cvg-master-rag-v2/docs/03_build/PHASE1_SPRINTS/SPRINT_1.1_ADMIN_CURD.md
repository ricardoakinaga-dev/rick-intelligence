# PHASE 1 — SPRINT 1.1: Admin Module CRUD

## Objetivo
Implementar CRUD completo de tenants e usuários com persistência.

## Escopo
- CRUD /tenants
- CRUD /users
- Persistência em memória ou filesystem

## Tasks

### Task 1.1.1: Tenant CRUD
**O QUE:** Implementar POST/GET/PUT/DELETE /tenants
**ONDE:** src/admin/routes.py
**COMO:** FastAPI routes com storage em memória
**DEPENDÊNCIA:** Sprint 0.3 (RBAC)
**CRITÉRIO DE PRONTO:** Admin pode criar, listar, atualizar e deletar tenants

### Task 1.1.2: User CRUD
**O QUE:** Implementar POST/GET/PUT/DELETE /users
**ONDE:** src/admin/routes.py
**COMO:** FastAPI routes com storage em memória
**DEPENDÊNCIA:** Sprint 0.3 (RBAC)
**CRITÉRIO DE PRONTO:** Admin pode criar, listar, atualizar e deletar usuários

### Task 1.1.3: User-Tenant Association
**O QUE:** Associar usuários a tenants via workspace_id
**ONDE:** src/admin/service.py
**COMO:** Campo tenant_id/workspace_id em User
**DEPENDÊNCIA:** Tenant CRUD + User CRUD
**CRITÉRIO DE PRONTO:** Usuários pertencem a tenant correto

### Task 1.1.4: Admin Service Layer
**O QUE:** Criar service layer para lógica de admin
**ONDE:** src/admin/service.py
**COMO:** Commands e validações de negócio
**DEPENDÊNCIA:** Tenant CRUD + User CRUD
**CRITÉRIO DE PRONTO:** Lógica de negócio isolada em service

## Riscos
- Storage em memória não persiste entre restarts (aceitável para F0/F1)

## Critérios de Validação
- [ ] CRUD /tenants funciona completamente
- [ ] CRUD /users funciona completamente
- [ ] Usuários associados a tenants
- [ ] Service layer isola lógica de negócio

## Status
⚪ PENDENTE