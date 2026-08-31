# 0102 — Bounded Contexts

## Domínios Identificados

### Domínio 1: INGESTÃO
**Responsabilidade:** Upload, parse, chunk e indexação de documentos

**Fronteiras:**
- Aceita arquivos (PDF, DOCX, MD, TXT)
- Produz chunks indexados no Qdrant
- Persiste corpus em filesystem

**O que pertence:**
- Validação de formato
- Parse por tipo
- Chunking recursivo
- Geração de embeddings
- Indexação no Qdrant

**O que NÃO pertence:**
- Lógica de autenticação
- Interface de usuário
- Métricas de negócio

---

### Domínio 2: RETRIEVAL
**Responsabilidade:** Busca híbrida e recuperação de contexto

**Fronteiras:**
- Recebe query text
- Produz chunks relevantes com scores

**O que pertence:**
- Embedding de query
- Busca densa (dense)
- Busca esparsa (BM25/sparse)
- Fusão RRF
- Filtragem (workspace_id, document_id, tags, page_hint)

**O que NÃO pertence:**
- Geração de resposta
- Autenticação
- Persistência de sessão

---

### Domínio 3: QUERY/RAG
**Responsabilidade:** Geração de respostas fundamentadas

**Fronteiras:**
- Recebe query do usuário
- Consulta Retrieval
- Produz resposta com citações

**O que pertence:**
- Montagem de contexto
- Chamar LLM
- Formatar resposta com citações
- Avaliar low confidence
- Calcular groundedness

**O que NÃO pertence:**
- Indexação de documentos
- Autenticação (mas usa sessão)

---

### Domínio 4: AUTENTICAÇÃO E AUTORIZAÇÃO
**Responsabilidade:** Identidade, sessão e permissões

**Fronteiras:**
- Valida credenciais
- Gerencia sessões
- Aplica RBAC

**O que pertence:**
- Login/logout
- Validação de credenciais
- Criação de sessão
- RBAC (admin/operator/viewer)
- Validação de workspace

**O que NÃO pertence:**
- Lógica de negócio
- Retrieval/Query
- Persistência de documentos

---

### Domínio 5: ADMINISTRAÇÃO
**Responsabilidade:** Gestão de tenants e usuários

**Fronteiras:**
- CRUD de tenants
- CRUD de usuários
- Associação usuário-role-tenant

**O que pertence:**
- Criar/editar/remover tenant
- Criar/editar/remover usuário
- Associar role a usuário
- Auditoria de operações admin

**O que NÃO pertence:**
- Lógica de negócio core
- Retrieval/Query
- Autenticação (usa AuthDomain)

---

### Domínio 6: TELEMETRIA
**Responsabilidade:** Observabilidade e logs

**Fronteiras:**
- Coleta logs
- Agrega métricas
- Health check

**O que pertence:**
- request_id generation
- Query logging
- Ingestion logging
- Metrics aggregation
- Health check
- Auditoria admin logging

**O que NÃO pertence:**
- Lógica de negócio
- Autenticação

---

## Relações entre Contextos

```
AUTH ──────────────────────► ALL (validação de sessão)
   │
   ▼
ADMIN ──► TENANTS/USERS (CRUD, auditoria)
   │
   ▼
INGESTION ──► QDRANT (indexação)
   │
   ▼
RETRIEVAL ──► QDRANT (busca)
   │
   ▼
QUERY ──► RETRIEVAL ──► LLM (resposta)
   │
   ▼
TELEMETRY ◄──── ALL (logs e métricas)
```

---

## Riscos de Acoplamento

### Risco 1: Auth em todos os lugares
- Solução: Middleware centralizado
- Cada domínio recebe workspace_id da sessão validada

### Risco 2: Qdrant como dependency única
- Solução: Health check, modo degradado
- Se Qdrant offline → degraded status

---

## Próximo Passo

Avançar para 0103_mapa_de_modulos.md