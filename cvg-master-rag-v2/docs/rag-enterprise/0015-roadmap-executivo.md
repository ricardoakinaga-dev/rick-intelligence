# 0015 — Roadmap Executivo (Atualizado 2026-04-17)

## Objetivo

Registrar o roadmap executivo que leva a base atual até a versão final **Enterprise Premium**, incluindo frontend robusto e plataforma multiempresa.

---

## Estado Atual (Reauditoria 2026-04-17)

### Nota Geral: 91/100 (subida de 87)

O programa possui um motor RAG core (F0) sólido e funcional:
- API REST ✅
- Ingestão e parsing ✅
- Chunking recursivo ✅
- Retrieval híbrido (dense + sparse + RRF) ✅
- Query e grounding ✅
- Telemetria estruturada ✅
- Frontend Next.js 15 completo ✅
- **Dataset de 30 perguntas reais com HIT@5=100% ✅ (NOVO)**
- **Auth com password verificado ✅ (NOVO)**
- **Isolamento multi-tenant comprovado ✅ (NOVO)**

### O que ainda bloqueia gates

1. **Reranking não implementado** — gap F1 vs documentação
2. **SLA/alertas não implementados** — gap F3
3. **HyDE não implementado** — promise F2 pendente
4. **Semantic chunking não implementado** — promise F2 pendente

### Classificação executiva

| Fase | Status | Nota |
|---|---|---|
| F0 — Foundation | ✅ LIBERADO | 95/100 |
| F1 — Profissional | ⚠️ Parcial | 78/100 |
| F2 — Premium | ⚠️ Frontend OK, features pendentes | 82/100 |
| F3 — Enterprise | ⚠️ Auth OK, SLA pendente | 70/100 |

---

## Visão Final do Produto

A versão final deve entregar:

- backend forte
- frontend robusto com chat, painel, administração
- multitenancy com isolamento provado
- RBAC com auth enterprise real
- observabilidade enterprise com alertas e SLA
- dataset de avaliação real e auditável

---

## Sequência Estratégica (Atualizada)

```text
F0 — Foundation ✅ (funcional)
    ↓
F1 — Operação Profissional ⚠️ (parcial)
    ↓
F2 — Produto Premium ⚠️ (frontend OK, features pendentes)
    ↓
F3 — Plataforma Enterprise ❌ (bloqueada por auth e dataset)
```

---

## Prioridades Executivas (Reordenadas)

### Prioridade 0 — Dataset de Avaliação

**Antes de qualquer gate, criar dataset real.**

- 20+ perguntas reais (não sintéticas)
- Múltiplos documentos
- Schema validado

**Sem dataset, nenhum gate é verificável.**

### Prioridade 1 — Segurança e Auth

- Substituir auth demo por autenticacao real
- RBAC server-side com memberships persistidas
- Sessions que sobrevivem reinicialização

### Prioridade 2 — Operacao Profissional

- Reranking ou documentar justificativa
- Dataset expandido 30+
- chunk_size tuning

### Prioridade 3 — Produto Premium

- Semantic chunking ou justificativa
- HyDE ou remoção do roadmap
- Dashboard executivo

### Prioridade 4 — Enterprise Platform

- Multitenancy com isolamento provado
- Auth enterprise (Supabase)
- Alertas e SLA

---

## Marco Final Esperado

Ao final do roadmap, o programa deve ser:

- backend forte com dataset auditável
- frontend forte e maduro
- produto premium com features completas
- plataforma enterprise com isolamento provado

---

## Próximo Passo Imediato

**Criar dataset real de 20+ perguntas antes de qualquer gate.**

O backlog `0033` e planos `0035`/`0036` já existem e são completos — mas o dataset é a blockers de todos os gates.
