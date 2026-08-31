# 0016 — Backlog Priorizado (Atualizado 2026-04-17)

## Objetivo

Traduzir a visão final **Enterprise Premium** em backlog executável, corrigido após auditoria técnica de 2026-04-17.

---

## Estado Atual (Auditoria 2026-04-17)

**Nota Geral: 87/100**

- F0: 95/100 ✅ Funcional
- F1: 72/100 ⚠️ Parcial
- F2: 82/100 ⚠️ Frontend OK, features pendentes
- F3: 60/100 ❌ Bloqueado

**Blocker principal: dataset real não existe.**

---

## Estrutura do Backlog

### P0 — Fundação

**Estado: Funcional** (95/100)

Motor RAG core operacional:
- upload e parsing ✅
- chunking recursivo ✅
- retrieval híbrido ✅
- query e grounding ✅
- telemetria ✅
- API REST ✅
- frontend ✅

**ABERTA: Verificação de gate sem dataset real.**

---

### P1 — Dataset de Avaliação (CRÍTICO)

**Estado: NÃO EXISTE** (60/100 atual, bloqueador)

Este é o blocker número 1 de todo o programa.

Itens:
- Criar dataset de 20+ perguntas reais
- Validar schema Pydantic
- Cobrir múltiplos documentos
- Balancear categorias e dificuldade
- Executar baseline de hit_rate

**Critério de aceite:**
- `GET /evaluation/dataset` retorna 20+ perguntas
- Hit rate top-5 >= 60% para gate F0

---

### P2 — Segurança e Auth (P0 no plano corretivo)

**Estado: Demo credentials** (82/100 atual, incompleto)

Itens:
- Autenticacao real no servidor
- RBAC server-side com memberships persistidas
- Sessions duráveis
- log_admin_event() auditável

**Critério de aceite:**
- Auth não depende de X-Enterprise-* do cliente
- Sessions sobrevivem reinicialização

---

### P3 — Operação Profissional

**Estado: Parcialmente implementada** (72/100)

Itens:
- Reranking (Cohere) — implementar ou documentar justificativa
- Dataset expandido 30+
- chunk_size tuning
- Interface web operacional ✅ (frontend existe)

---

### P4 — Produto Premium

**Estado: Frontend OK, features pendentes** (82/100)

Sprints (já executados parcialmente):
- Sprint F1-F8 ✅ Implementados no frontend
- Semantic chunking ❌ Não implementado
- HyDE ❌ Não implementado

---

### P5 — Enterprise Platform

**Estado: Bloqueada** (60/100)

Sprints (plano corretivo H1-H6):
- Sprint G1 ✅ Fundação enterprise
- Sprint G2 ⚠️ Multitenancy e admin core
- Sprint G3 ⚠️ Observabilidade
- Sprint G4 ❌ Release enterprise

---

## Backlog Corretivo (0033/0034/0035/0036)

Os documentos `0033` a `0036` já contêm o backlog completo da rodada corretiva.

Sequência recomendada:
1. OP-01 a OP-06 (Auth, RBAC, Persistência)
2. Dataset (criar antes de qualquer gate)
3. OP-07 a OP-12 (Observabilidade, Qualidade)
4. Reauditoria

---

## Ordem de Execução Recomendada

1. **IMEDIATO:** Criar dataset real de avaliação
2. **Sprint H1-H2:** Auth e persistência
3. **Sprint H3:** Isolamento multi-tenant
4. **Sprint H4:** Avaliação honesta
5. **Sprint H5:** Observabilidade e dashboard
6. **Sprint H6:** Qualidade de release
7. Reauditoria formal

---

## Resultado Final Esperado

O backlog só é considerado concluído quando o projeto atingir:

- Dataset real validado (gate F0 verificável)
- Auth enterprise real
- Isolamento multi-tenant provado
- Frontend robusto ✅ (já existente)
- Observabilidade enterprise
- Gate F3 aprovado

---

## Próximo Passo

1. Criar `src/data/default/dataset.json` com 20+ perguntas reais
2. Executar OP-01 (auth real)
3. Prosseguir com plano corretivo H1-H6
