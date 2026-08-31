# 0302 — BACKLOG MASTER

## Backlog Priorizado — RAG Enterprise Premium

---

## P0 — CRÍTICO (Foundation)

| ID | Título | Módulo | Dependência | Phase |
|---|---|---|---|---|
| P0-001 | Session persistence no servidor | Auth | Nenhuma | F0 |
| P0-002 | Login/logout funcional | Auth | Nenhuma | F0 |
| P0-003 | RBAC middleware em todos os endpoints | Auth | Session | F0 |
| P0-004 | request_id em todos os logs | Telemetry | Nenhuma | F0 |
| P0-005 | Health check robusto (/health) | Telemetry | Nenhuma | F0 |
| P0-006 | Middleware de extração de workspace_id | Auth | Session | F0 |
| P0-007 | CRUD tenants com persistência | Admin | Auth | F1 |
| P0-008 | CRUD usuários com persistência | Admin | Auth | F1 |
| P0-009 | Isolamento de workspace em todas as queries | Admin | Auth + Admin | F1 |
| P0-010 | Proteção tenant bootstrap | Admin | CRUD tenants | F1 |

---

## P1 — ALTA PRIORIDADE (Core Features)

| ID | Título | Módulo | Dependência | Phase |
|---|---|---|---|---|
| P1-001 | Hybrid search (dense + sparse + RRF) | Retrieval | Auth | F2 |
| P1-002 | Query RAG com citações | Query/RAG | Retrieval | F2 |
| P1-003 | Upload + parsing + chunking | Ingestion | Auth | F1 |
| P1-004 | Embedding + indexing no Qdrant | Ingestion | Chunking | F1 |
| P1-005 | Dataset de 20+ perguntas reais | Evaluation | Query/RAG | F2 |
| P1-006 | Hit rate evaluation framework | Evaluation | Dataset | F2 |
| P1-007 | Groundedness check | Query/RAG | LLM response | F2 |
| P1-008 | Low confidence warning | Query/RAG | Groundedness | F2 |
| P1-009 | Suite TKT-010 de não-vazamento | Admin | Isolamento | F1 |
| P1-010 | Métricas por tenant | Telemetry | Auth | F3 |

---

## P2 — MÉDIA PRIORIDADE (Enhancements)

| ID | Título | Módulo | Dependência | Phase |
|---|---|---|---|---|
| P2-001 | Dashboard executivo | Telemetry | Métricas | F3 |
| P2-002 | SLI/SLO definidos | Telemetry | Métricas | F3 |
| P2-003 | Alertas configurados | Telemetry | SLI/SLO | F3 |
| P2-004 | request_id ponta a ponta | Telemetry | Logs | F3 |
| P2-005 | TypeScript checks pass | Build | Código completo | F4 |
| P2-006 | Smoke tests estáveis | Build | Código completo | F4 |
| P2-007 | Suite pytest conclusiva | Build | Testes | F4 |
| P2-008 | Log aggregation | Telemetry | request_id | F3 |

---

## P3 — BAIXA PRIORIDADE (Future)

| ID | Título | Módulo | Dependência | Phase |
|---|---|---|---|---|
| P3-001 | Cohere Rerank | Retrieval | RRF working | F+ |
| P3-002 | Supabase Auth SSO | Auth | Current auth working | F+ |
| P3-003 | MinIO/S3 storage | Ingestion | Multi-service need | F+ |
| P3-004 | LangSmith integration | Evaluation | Dataset working | F+ |
| P3-005 | Multi-session support | Auth | Session persistence | F+ |

---

## Detalhamento — P0 Items

### P0-001: Session Persistence
- **O que:** Implementar armazenamento de sessão no servidor (in-memory)
- **Onde:** Auth Module (src/auth/)
- **Como:** Dicionário em memória com Session ID como chave
- **Dependência:** Nenhuma
- **Critério de pronto:** Sessão persiste entre requests, expira após timeout

### P0-002: Login/Logout Funcional
- **O que:** Implementar POST /auth/login e POST /auth/logout
- **Onde:** Auth Module (src/auth/routes.py)
- **Como:** Validar credenciais, criar/invalidar sessão
- **Dependência:** Session persistence
- **Critério de pronto:** Login cria sessão, logout destrói sessão

### P0-003: RBAC Middleware
- **O que:** Middleware que valida role em cada endpoint protegido
- **Onde:** Auth Module (src/auth/middleware.py)
- **Como:** Decorator/dependency que verifica role do usuário
- **Dependência:** Session persistence
- **Critério de pronto:** Usuário sem role não acessa endpoint, logs de acesso negado

### P0-004: request_id em Logs
- **O que:** Middleware que gera e propaga request_id
- **Onde:** Telemetry Module (src/telemetry/logging.py)
- **Como:** UUID gerado no entry point, propagado via context vars
- **Dependência:** Nenhuma
- **Critério de pronto:** request_id presente em todo log entry

### P0-005: Health Check Robusto
- **O que:** GET /health retornando status de todas as dependências
- **Onde:** Telemetry Module (src/telemetry/health.py)
- **Como:** Checks синхронные for Qdrant, OpenAI, filesystem
- **Dependência:** Nenhuma
- **Critério de pronto:** /health retorna 200 com status de cada dependência

### P0-006: Workspace ID Middleware
- **O que:** Extrair workspace_id da sessão e adicionar ao request state
- **Onde:** Auth Module (src/auth/middleware.py)
- **Como:** Middleware que popula request.state.workspace_id
- **Dependência:** Session persistence
- **Critério de pronto:** workspace_id disponível em todos os endpoints

### P0-007: CRUD Tenants
- **O que:** POST/GET/PUT/DELETE /tenants com persistência
- **Onde:** Admin Module (src/admin/routes.py)
- **Como:** CRUD com storage em memória ou filesystem
- **Dependência:** Auth (RBAC)
- **Critério de pronto:** Admin pode criar, listar, atualizar, deletar tenants

### P0-008: CRUD Usuários
- **O que:** POST/GET/PUT/DELETE /users com persistência
- **Onde:** Admin Module (src/admin/routes.py)
- **Como:** CRUD com storage em memória ou filesystem
- **Dependência:** Auth (RBAC)
- **Critério de pronto:** Admin pode criar, listar, atualizar, deletar usuários

### P0-009: Isolamento de Workspace
- **O que:** Todas as queries filtradas por workspace_id
- **Onde:** Todos os módulos (queries)
- **Como:** Filtro obrigatório em todas as operações de dados
- **Dependência:** Auth + Admin
- **Critério de pronto:** Dados de um workspace não aparecem em outro

### P0-010: Proteção Tenant Bootstrap
- **O que:** Impedir deletar tenant com dados ativos
- **Onde:** Admin Module (src/admin/service.py)
- **Como:** Validação antes de DELETE /tenants/{id}
- **Dependência:** CRUD Tenants
- **Critério de pronto:** Tentativa de deletar tenant com dados retorna erro 400

---

## Riscos e Mitigações (Backlog Level)

| ID | Risco | Mitigação |
|---|---|---|
| R1 | Gap código/docs | Validação em cada sprint |
| R2 | Breaking change frontend | Migration guide, comunicação antecipada |
| R3 | Regressões | Suite pytest + smoke tests |
| R4 | Dependência APIs externas | Health checks + fallback graceful |

---

## Próximo Passo

Avançar para criação de estrutura de sprints e execução da Phase 0.