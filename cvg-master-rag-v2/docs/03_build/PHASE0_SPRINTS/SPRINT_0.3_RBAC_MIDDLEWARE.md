# PHASE 0 — SPRINT 0.3: RBAC Middleware

## Objetivo
Implementar Role-Based Access Control em todos os endpoints protegidos.

## Escopo
- Roles definidos (admin, operator, viewer)
- Decorator de RBAC
- Validação em endpoints

## Tasks

### Task 0.3.1: Role Definitions
**O QUE:** Definir enum de roles e escopos
**ONDE:** src/auth/rbac.py
**COMO:** Enum com admin, operator, viewer + escopos
**DEPENDÊNCIA:** Sprint 0.1
**CRITÉRIO DE PRONTO:** Roles definidos com permissões corretas

### Task 0.3.2: RBAC Decorator
**O QUE:** Criar decorator que valida role antes de endpoint
**ONDE:** src/auth/rbac.py
**COMO:** Decorator @require_role(role) que verifica session.role
**DEPENDÊNCIA:** Role definitions
**CRITÉRIO DE PRONTO:** Decorator aplica role check corretamente

### Task 0.3.3: Protected Endpoints
**O QUE:** Aplicar RBAC em todos os endpoints protegidos
**ONDE:** src/*/routes.py (todos os módulos)
**COMO:** Adicionar decorator aos endpoints que requerem auth
**DEPENDÊNCIA:** RBAC decorator
**CRITÉRIO DE PRONTO:** Todos os endpoints protegidos têm RBAC

### Task 0.3.4: Audit Log for Denied Access
**O QUE:** Logar tentativas de acesso negado
**ONDE:** src/auth/rbac.py
**COMO:** Log warning com user_id, endpoint, required_role
**DEPENDÊNCIA:** RBAC decorator
**CRITÉRIO DE PRONTO:** Tentativas de acesso negado são logadas

## Riscos
- Breaking change se frontend não validar role (mitigação: backend sempre valida)

## Critérios de Validação
- [ ] Roles definidos (admin, operator, viewer)
- [ ] Decorator verifica role corretamente
- [ ] Acesso negado retorna 403
- [ ] Tentativas de acesso negado são logadas

## Status
⚪ PENDENTE