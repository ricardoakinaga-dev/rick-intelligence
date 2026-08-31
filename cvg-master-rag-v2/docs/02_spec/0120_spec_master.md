# 0120 — SPEC Master

## Especificação Consolidada

Este documento consolida toda a especificação técnica do projeto RAG Enterprise Premium, servindo como fonte única de verdade após validação do gate SPEC.

---

## Visão Arquitetural

### Modular Monolith
- **Camada de Apresentação:** FastAPI + Uvicorn
- **Camada de Aplicação:** Commands e Queries (CQRS-lite)
- **Camada de Domínio:** Entidades, Value Objects, Aggregates
- **Camada de Infraestrutura:** OpenAI, Qdrant, Filesystem

### Domínios (Bounded Contexts)
1. **Ingestion** — Upload, parsing, chunking, embedding
2. **Retrieval** — Busca vetorial híbrida (dense + sparse + RRF)
3. **Query/RAG** — Resposta gerada com contexto + citações
4. **Auth** — Autenticação, sessão, RBAC
5. **Admin** — CRUD de tenants e usuários
6. **Telemetry** — Logs, métricas, health, alertas

---

## Modelo de Domínio

### Entidades Principais

| Entidade | Descrição | Atributos Chave |
|---|---|---|
| **Tenant** | Organização | id, name, created_at, status |
| **Workspace** | Área isolada por tenant | id, tenant_id, name |
| **User** | Usuário do sistema | id, email, role, workspace_id |
| **Session** | Sessão autenticada | id, user_id, workspace_id, expires_at |
| **Document** | Documento carregado | id, workspace_id, name, status, chunk_count |
| **Chunk** | Fragmento indexado | id, document_id, content, vector, workspace_id |

### Value Objects
- **ChunkMetadata:** source_type, page, position
- **SearchScore:** dense_score, sparse_score, rrf_score
- **Citation:** chunk_id, text, score

### Aggregates
- **DocumentAggregate:** Document + Chunks (consistency boundary)
- **UserAggregate:** User + Sessions (lifecycle boundary)

---

## Contratos de API

### REST Endpoints

#### Auth
| Método | Path | Descrição | Auth |
|---|---|---|---|
| POST | /auth/login | Login com email/senha | Público |
| POST | /auth/logout | Logout e invalidação de sessão | Sessão |
| GET | /auth/session | Retorna sessão atual | Sessão |

#### Documents
| Método | Path | Descrição | Auth |
|---|---|---|---|
| GET | /documents | Lista documentos | Operator+ |
| POST | /documents/upload | Upload de documento | Operator+ |
| GET | /documents/{id} | Detalhes do documento | Operator+ |

#### Search
| Método | Path | Descrição | Auth |
|---|---|---|---|
| POST | /search | Busca com evidências | Operator+ |

#### Query
| Método | Path | Descrição | Auth |
|---|---|---|---|
| POST | /query | Query RAG com resposta | Operator+ |

#### Admin
| Método | Path | Descrição | Auth |
|---|---|---|---|
| GET | /tenants | Lista tenants | Admin |
| POST | /tenants | Cria tenant | Admin |
| PUT | /tenants/{id} | Atualiza tenant | Admin |
| DELETE | /tenants/{id} | Remove tenant | Admin |
| GET | /users | Lista usuários | Admin |
| POST | /users | Cria usuário | Admin |
| PUT | /users/{id} | Atualiza usuário | Admin |
| DELETE | /users/{id} | Remove usuário | Admin |

#### Telemetry
| Método | Path | Descrição | Auth |
|---|---|---|---|
| GET | /health | Health check | Público |
| GET | /metrics | Métricas agregadas | Admin |

---

## Eventos de Domínio

| Evento | Payload | Publisher |
|---|---|---|
| DocumentUploaded | document_id, workspace_id, source_type | Ingestion |
| ChunkingCompleted | document_id, chunk_count, strategy | Ingestion |
| QueryExecuted | query, workspace_id, result_count | Query/RAG |
| AnswerGenerated | answer, citations, latency_ms, confidence | Query/RAG |
| AdminAction | action, admin_id, target_id, result | Admin |
| LoginAttempt | user_id, result, ip | Auth |

---

## Fluxos Principais

### Fluxo de Ingestion
```
Upload → Parse → Chunk (recursive) → Embed → Index (Qdrant) → Ready
```

### Fluxo de Retrieval
```
Query → Embed → Dense Search → Sparse Search → RRF Fusion → Top-K
```

### Fluxo de Query RAG
```
Query → Retrieval → Context Assembly → LLM → Groundedness Check → Response + Citations
```

---

## Politicas de Integridade

### RN-01: Isolamento de Tenant
Dados de um workspace nunca são expostos a outro workspace.

### RN-02: Consistência de Documento
Chunks são atômicos com seu documento (CUD cascade).

### RN-03: Expiração de Sessão
Sessões expiram após configurado; refresh estende vida.

### RN-04: Não-Deleção de Tenant com Dados
Tenant com documentos ou usuários ativos não pode ser deletado.

### RN-05: RAG Groundedness
Respostas RAG devem ter groundedness >= 0.7 ou marcar low_confidence.

---

## Requisitos Não-Funcionais Consolidado

### Performance
- RNF-01: Latência p99 retrieval < 500ms
- RNF-02: Latência p99 query < 5s
- RNF-03: Throughput: 10 queries/min por workspace

### Segurança
- RNF-04: Autenticação stateless via session token
- RNF-05: RBAC em todos os endpoints protegidos
- RNF-06: Audit log de todas as ações sensíveis

### Observabilidade
- RNF-07: request_id em todos os logs
- RNF-08: Health check com latência de dependências
- RNF-09: SLI/SLO definidos e mensuráveis

---

## Métricas de Sucesso

### Retrieval
- hit_rate_top1 >= 40%
- hit_rate_top3 >= 50%
- hit_rate_top5 >= 60%

### RAG
- grounded_rate >= 85%
- citation_coverage_avg >= 80%
- low_confidence_rate <= 15%

### Sistema
- availability >= 99%
- p99_latency < 3s
- error_rate < 2%

---

## Fase de Build

### Roadmap
| Fase | Foco | Critério de Pronto |
|---|---|---|
| F0 | Fundação (Auth + Telemetry) | Auth server-side funcionando, RBAC enforced |
| F1 | Isolamento e Persistência | Isolamento provado com suite |
| F2 | Dataset e Avaliação | Dataset real validado, hit_rate >= 60% |
| F3 | Observabilidade Enterprise | Traces completos, alertas configurados |
| F4 | Hardening e Release | TSC passa, pytest passa, gate F3 aprovado |

---

## Decisões Arquiteturais

### AD-01: Modular Monolith
**Decisão:** Arquitetura modular monolith em vez de microservices.
**Rationale:** Simplicidade de deploy, consistência transacional, menor overhead operacional.

### AD-02: Hybrid Search (Dense + Sparse + RRF)
**Decisão:** RRF para fusion de resultados dense/sparse.
**Rationale:** Melhor cobertura de busca (sinônimos + termos exatos).

### AD-03: Server-side Sessions
**Decisão:** Sessões armazenadas no servidor (in-memory).
**Rationale:** Auth simples sem Redis; escala com processo.

### AD-04: Recursive Chunking Only (F0)
**Decisão:** Apenas recursive chunking na F0; character/ sentence/ passage em F1+.
**Rationale:** MVP focado em foundation sólida.

### AD-05: OpenAI Only (F0)
**Decisão:** Apenas OpenAI embeddings + LLM na F0.
**Rationale:** MVP sem integração adicional; swap later se necessário.

---

## Próximo Passo

Avançar para 0190_spec_validation.md para validação do gate SPEC.