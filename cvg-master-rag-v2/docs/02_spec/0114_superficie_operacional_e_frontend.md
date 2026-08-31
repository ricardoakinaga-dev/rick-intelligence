# 0114 — Superfície Operacional e Frontend

## Superfícies do Sistema

### Tela: Login
**URL:** `/login`
**Objetivo:** Autenticação de usuário
**Dados consumidos:**
- Session (result of login)
**Ações disparadas:**
- POST /auth/login
- Redirect to dashboard on success

**Estados:**
- Default: form vazio
- Loading: spinner
- Error: mensagem de erro
- Success: redirect

---

### Tela: Dashboard
**URL:** `/dashboard`
**Objetivo:** Visão geral do sistema
**Dados consumidos:**
- GET /metrics (workspace_id from session)
**Ações disparadas:**
- Refresh de métricas

**Estados:**
- Default: KPIs exibidos
- Loading: skeleton
- Empty: "Sem dados"
- Error: mensagem

---

### Tela: Documents
**URL:** `/documents`
**Objetivo:** Listagem e upload de documentos
**Dados consumidos:**
- GET /documents?workspace_id=... (list)
- POST /documents/upload (upload)
**Ações disparadas:**
- Upload de arquivo
- Remoção de documento (future)

**Estados:**
- Default: lista de documentos
- Empty: "Nenhum documento"
- Upload: progress bar
- Error: mensagem

---

### Tela: Search
**URL:** `/search`
**Objetivo:** Busca com evidências
**Dados consumidos:**
- POST /search (query execution)
**Ações disparadas:**
- Query submission
- Filtro applied

**Estados:**
- Default: form de busca
- Loading: spinner
- Results: lista de chunks com scores
- No results: "Nenhum resultado"
- Low confidence: warning

---

### Tela: Chat
**URL:** `/chat`
**Objetivo:** Query RAG com resposta
**Dados consumidos:**
- POST /query
- Citations (in response)
**Ações disparadas:**
- Query submission

**Estados:**
- Default: chat interface
- Loading: resposta pendente
- Response: answer with citations
- Low confidence: warning badge
- Grounded: green indicator

---

### Tela: Audit
**URL:** `/audit`
**Objetivo:** Logs de queries e eventos
**Dados consumidos:**
- GET /metrics (for aggregated)
**Ações disparadas:**
- Filtros aplicados

**Estados:**
- Default: logs listados
- Filtered: resultados filtrados
- Empty: "Nenhum log"

---

### Tela: Admin
**URL:** `/admin`
**Objetivo:** Gestão de tenants e usuários
**Dados consumidos:**
- GET /tenants
- GET /users
- POST /tenants
- POST /users
- PUT /users/{id}
- DELETE /users/{id}
**Ações disparadas:**
- CRUD operations
- Role changes

**Estados:**
- Default: lista de entidades
- Form: create/edit
- Loading: spinner
- Error: mensagem
- Protected: tenant bootstrap protected

---

## Validações Relevantes

### Login
- Email format
- Password non-empty
- Credenciais inválidas → erro 401

### Upload
- File type validation (client-side)
- Max size (client-side)
- Server validates again

### Search/Query
- Query non-empty
- Workspace_id from session

---

## Estados de Erro, Vazio e Carregamento

### Loading States
- Skeleton/shimmer
- Spinner para ações
- Progress bar para upload

### Empty States
- Mensagem contextual
- Call to action quando aplicável

### Error States
- Mensagem clara
- Ação de retry quando aplicável

---

## Riscos de Inconsistência com Backend

### Risco 1: Frontend não valida role
- Mitigação: Backend valida RBAC em cada endpoint

### Risco 2: Stale data em listagens
- Mitigação: Refresh after mutations

### Risco 3: Session expired não detecta
- Mitigação: 401 redirect to login

---

## Próximo Passo

Avançar para 0115_plano_de_build_por_fases.md