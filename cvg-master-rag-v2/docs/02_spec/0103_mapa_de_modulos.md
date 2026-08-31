# 0103 — Mapa de Módulos

## Módulos do Sistema

### Módulo 1: Ingestion Module

**Responsabilidade:** Upload, parse, chunk e indexação de documentos

**Entradas:**
- Arquivo (multipart/form-data)
- workspace_id

**Saídas:**
- document_id
- chunk_count
- status

**Dependências permitidas:**
- Qdrant (indexação)
- Filesystem (persistência)
- OpenAI (embeddings)

**Dependências proibidas:**
- Auth module (tem workspace_id da sessão)

---

### Módulo 2: Retrieval Module

**Responsabilidade:** Busca híbrida

**Entradas:**
- query text
- workspace_id
- top_k, threshold, filters

**Saídas:**
- Lista de chunks com scores
- low_confidence flag

**Dependências permitidas:**
- Qdrant (busca)
- OpenAI (embeddings)

**Dependências proibidas:**
- LLM (geração de resposta)

---

### Módulo 3: Query/RAG Module

**Responsabilidade:** Geração de resposta fundamentada

**Entradas:**
- query text
- workspace_id
- top_k, threshold

**Saídas:**
- Resposta text
- Citations
- Groundedness report

**Dependências permitidas:**
- Retrieval (contexto)
- OpenAI (LLM)

**Dependências proibidas:**
- Ingestion

---

### Módulo 4: Auth Module

**Responsabilidade:** Autenticação e autorização

**Entradas:**
- email, password (login)
- session_id (validação)

**Saídas:**
- Session/token (login)
- User info + roles (validação)
- Boolean de acesso

**Dependências permitidas:**
- Memory (sessões)

**Dependências proibidas:**
- Nenhuma (é independente)

---

### Módulo 5: Admin Module

**Responsabilidade:** Gestão de tenants e usuários

**Entradas:**
- Tenant data (CRUD)
- User data (CRUD)
- role, workspace associations

**Saídas:**
- Confirmação de operação
- Lista de tenants/users

**Dependências permitidas:**
- Auth (RBAC check)

**Dependências proibidas:**
- Business logic (ingestion, retrieval)

---

### Módulo 6: Telemetry Module

**Responsabilidade:** Observabilidade

**Entradas:**
- Events from all modules (via logging)
- Metrics requests

**Saídas:**
- Health status
- Aggregated metrics
- Query logs

**Dependências permitidas:**
- Todas (consome eventos)

**Dependências proibidas:**
- Nenhuma

---

## Ordem de Construção Sugerida

```
1. Auth (base - sem auth, nada funciona)
2. Telemetry (logs e health - debugging)
3. Ingestion (documentos - corpus)
4. Retrieval (busca - teste)
5. Query (RAG - integração)
6. Admin (gestão - operação)
```

---

## Próximo Passo

Avançar para 0104_modelo_de_dominio.md