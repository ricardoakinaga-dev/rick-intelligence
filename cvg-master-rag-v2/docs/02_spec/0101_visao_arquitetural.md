# 0101 — Visão Arquitetural

## Objetivo

Definir a macroarquitetura coerente com o PRD.

---

## Estilo Arquitetural

### Escolha: Modular Monolith com Camadas

**Justificativa:**
- Fase 0 usa FastAPI Modular Monolith (funciona bem)
- Microserviços só quando necessário (Fase 3+)
- Manter simplicidade enquanto valida

### Arquitetura em Camadas

```
┌─────────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js)                       │
│  Shell, Documents, Search, Chat, Dashboard, Admin, Audit     │
└─────────────────────────────┬───────────────────────────────┘
                              │ HTTP/REST
┌─────────────────────────────┴───────────────────────────────┐
│                    API GATEWAY / FASTAPI                   │
│  Auth Middleware, RBAC Middleware, Routes                   │
└──────────┬──────────────┬──────────────┬─────────────────────┘
           │              │              │
┌──────────┴────┐  ┌──────┴────┐  ┌─────┴─────────────┐
│  Services     │  │  Services  │  │  Services          │
│  Ingestion   │  │  Retrieval │  │  Auth/RBAC         │
└──────────────┘  └────────────┘  └────────────────────┘
           │              │              │
┌──────────┴──────────────┴──────────────┴──────────────────┐
│                    DATA LAYER                                │
│  Filesystem (corpus)  │  Qdrant (vectors)  │  Memory/Session  │
└─────────────────────────────────────────────────────────────┘
```

---

## Blocos do Sistema

### Backend (FastAPI)
- **Ingestion Service:** Upload, parse, chunk, index
- **Retrieval Service:** Hybrid search, RRF, filters
- **Auth Service:** Login, logout, session, RBAC
- **Admin Service:** CRUD tenants/users
- **Telemetry Service:** Logs, metrics, health

### Frontend (Next.js)
- **Shell:** Navigation, auth, tenant selector
- **Documents:** Upload, list, metadata
- **Search:** Query, results, filters
- **Chat:** Query, response, citations
- **Dashboard:** KPIs, metrics
- **Admin:** Tenants, users, roles
- **Audit:** Query logs, events

### Infraestrutura
- **Qdrant:** Vector DB (dense + sparse)
- **Filesystem:** Corpus storage
- **OpenAI:** Embeddings + LLM

---

## Fronteiras

### Backend vs Frontend
- Backend expõe REST API
- Frontend consome REST API
- Contratos definidos via OpenAPI/Swagger

### Serviços vs Dados
- Serviços gerenciam lógica
- Dados (corpus, vectors) são responsabilidade de serviços
- Separação clara de responsabilidades

### Auth vs Outros Serviços
- Auth é middleware central
- Todos os requests passam por validação de sessão
- RBAC aplicado no endpoint, não no service

---

## Justificativas Arquiteturais

### Por que Modular Monolith?
- Comunicação simples (memória)
- Debugging fácil
- Deployment simples
- Não há necessidade de scaling independente ainda

### Por que FastAPI?
- Contrato claro (OpenAPI)
- Python friendly para LLM
- Validação automática (Pydantic)
- Performance boa

### Por que Next.js Frontend?
- Já existe e funciona (F2 aprovado)
- App Router, React, TypeScript
- Shadcn/ui components

---

## Trade-offs

### Aceitos
- Monolith limita scaling independente de componentes
- Auth em memória (vs Redis) pode perder sessões em restart

### Rejeitados
- Microserviços: complexidade prematura
- GraphQL: REST é suficiente para caso de uso
- Redis para sessão: memória é suficiente para F0-F2

---

## Próximo Passo

Avançar para 0102_bounded_contexts.md