# 0116 — Matriz de Dependências

## Matriz de Dependências entre Módulos

### Dependências Diretas

| De \ Para | Auth | Ingestion | Retrieval | Query/RAG | Admin | Telemetry |
|---|---|---|---|---|---|---|
| **Auth** | — | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Ingestion** | ✅ | — | ❌ | ❌ | ❌ | ✅ |
| **Retrieval** | ✅ | ✅ | — | ✅ | ❌ | ✅ |
| **Query/RAG** | ✅ | ✅ | ✅ | — | ❌ | ✅ |
| **Admin** | ✅ | ❌ | ❌ | ❌ | — | ✅ |
| **Telemetry** | ✅ | ✅ | ✅ | ✅ | ✅ | — |

### Legenda
- ✅ = Depende de
- ❌ = Não depende de

---

## Dependências por Fase de Build

### Fase 0 — Fundação
```
Auth ──────┐
           ├── Telemetry (logs, health)
Telemetry ─┘
```
**Ordem:** Telemetry → Auth

### Fase 1 — Isolamento e Persistência
```
Fase 0 (Auth) ──┬── Admin ── Telemetry
                └── Ingestion (workspace isolation)
```
**Ordem:** Auth → Admin, Ingestion

### Fase 2 — Dataset e Avaliação
```
Fase 0 (Auth) ──┐
Fase 1 (Admin, Ingestion) ──┴── Query/RAG + Telemetry
```
**Ordem:** Admin, Ingestion → Query/RAG

### Fase 3 — Observabilidade Enterprise
```
Todos os módulos anteriores ──┴── Telemetry (métricas avançadas)
```
**Ordem:** F0, F1, F2 → Telemetry

### Fase 4 — Hardening e Release
```
Todos os módulos ──┴── Build completo + validação
```
**Ordem:** F3 → Build completo

---

## Dependências Externas

### OpenAI API
| Módulo | Dependência |
|---|---|
| Ingestion | Embeddings (text-embedding-3-small) |
| Query/RAG | LLM (GPT-4o-mini) |

### Qdrant
| Módulo | Dependência |
|---|---|
| Ingestion | Indexação de chunks |
| Retrieval | Busca vetorial |
| Query/RAG | Hybrid search |

### Filesystem
| Módulo | Dependência |
|---|---|
| Ingestion | Persistência de raw documents |
| Admin | Persistência de config |

---

## Dependências Críticas (Caminho Crítico)

### Caminho Crítico F0 → F4
```
Auth → Ingestion → Retrieval → Query/RAG → Telemetry
```

### Margens de Tolerância
- Auth: BLOQUEANTE para todas as fases
- Ingestion: BLOQUEANTE para F2+
- Telemetry: Paralelo, mas requerido para F3+

---

## Riscos de Dependência Circular

### Evitado por Design
- Auth nunca chama outros módulos
- Telemetry é observador passivo (eventos)
- Admin não depende de Query/RAG

### Padrão Established
```
┌─────────┐     ┌───────────┐
│  Auth   │────▶│ Telemetry │
└─────────┘     └───────────┘
     │                ▲
     ▼                │
┌─────────┐     ┌───────────┐
│  Admin  │────▶│  Query    │
└─────────┘     └───────────┘
```

---

## Matrix de Interfaces (Contratos)

| De | Para | Interface | Tipo |
|---|---|---|---|
| Auth | Telemetry | on_login, on_logout | Event |
| Ingestion | Telemetry | on_document_uploaded, on_chunking_completed | Event |
| Ingestion | Retrieval | chunks_created | Command |
| Retrieval | Telemetry | on_retrieval_completed | Event |
| Query/RAG | Retrieval | search(chunks) | Query |
| Query/RAG | Telemetry | on_answer_generated | Event |
| Admin | Telemetry | on_admin_action | Event |

---

## Próximo Passo

Avançar para 0117_backlog_estruturado.md