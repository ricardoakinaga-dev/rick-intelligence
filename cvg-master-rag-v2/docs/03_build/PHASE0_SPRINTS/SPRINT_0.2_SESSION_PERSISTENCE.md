# PHASE 0 — SPRINT 0.2: Session Persistence

## Objetivo
Implementar persistência de sessão server-side com timeout configurável.

## Escopo
- Session expiry mechanism
- Refresh de sessão
- Configuração de timeout

## Tasks

### Task 0.2.1: Session Expiry
**O QUE:** Implementar expiração automática de sessões
**ONDE:** src/auth/session.py
**COMO:** Thread/timer que remove sessões expiradas
**DEPENDÊNCIA:** Session storage (Sprint 0.1)
**CRITÉRIO DE PRONTO:** Sessões expiram após timeout configurado

### Task 0.2.2: Session Refresh
**O QUE:** Implementar extensão de TTL em cada request válida
**ONDE:** src/auth/session.py
**COMO:** Ao validar sessão, estender expiry
**DEPENDÊNCIA:** Session expiry
**CRITÉRIO DE PRONTO:** Sessão ativa tem TTL estendido em cada uso

### Task 0.2.3: Configurable Timeout
**O QUE:** Permitir configurar session timeout via env/config
**ONDE:** src/config.py
**COMO:** Variável de ambiente SESSION_TIMEOUT_SECONDS
**DEPENDÊNCIA:** Session expiry
**CRITÉRIO DE PRONTO:** Timeout configurável via variável de ambiente

## Riscos
- Background cleanup thread overhead (aceitável para MVP)

## Critérios de Validação
- [ ] Sessão expira após timeout configurado
- [ ] Sessão válida tem TTL estendida
- [ ] Sessão expirada retorna 401

## Status
⚪ PENDENTE