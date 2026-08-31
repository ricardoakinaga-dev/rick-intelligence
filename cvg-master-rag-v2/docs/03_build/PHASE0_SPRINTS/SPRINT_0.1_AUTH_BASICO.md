# PHASE 0 — SPRINT 0.1: Auth Module Básico

## Objetivo
Implementar autenticação básica com login/logout funcional.

## Escopo
- Session storage in-memory
- POST /auth/login
- POST /auth/logout
- Session validation middleware

## Tasks

### Task 0.1.1: Session Storage
**O QUE:** Criar sessão em memória com expiry
**ONDE:** src/auth/session.py
**COMO:** Dicionário Python com Session ID → Session data
**DEPENDÊNCIA:** Nenhuma
**CRITÉRIO DE PRONTO:** Sessão armazenada, resgatada e expirada corretamente

### Task 0.1.2: Login Endpoint
**O QUE:** Implementar POST /auth/login com validação de credenciais
**ONDE:** src/auth/routes.py
**COMO:** FastAPI route validando email/senha, criando sessão
**DEPENDÊNCIA:** Session storage
**CRITÉRIO DE PRONTO:** POST /auth/login retorna session_id com credenciais válidas; retorna 401 com credenciais inválidas

### Task 0.1.3: Logout Endpoint
**O QUE:** Implementar POST /auth/logout invalidando sessão
**ONDE:** src/auth/routes.py
**COMO:** FastAPI route que remove sessão do storage
**DEPENDÊNCIA:** Session storage
**CRITÉRIO DE PRONTO:** Session invalidada após logout; sessão inexistente retorna 401

### Task 0.1.4: Session Validation
**O QUE:** Dependency que valida sessão em requests protegidos
**ONDE:** src/auth/dependencies.py
**COMO:** FastAPI dependency que extrai session_id do header e valida
**DEPENDÊNCIA:** Session storage
**CRITÉRIO DE PRONTO:** Requests com sessão válida passam; requests sem sessão válida retornam 401

## Riscos
- In-memory storage não persiste entre restarts (aceitável para MVP)

## Critérios de Validação
- [ ] Login cria sessão válida
- [ ] Logout invalida sessão
- [ ] Sessão validada em endpoints protegidos
- [ ] Credenciais inválidas retornam 401

## Status
🟡 EM EXECUÇÃO