# 0117 — Backlog Estruturado

## Backlog por Fase

### Fase 0 — Fundação

#### P0 (Must Have)
- [ ] Session persistence no servidor
- [ ] Login/logout funcional
- [ ] RBAC enforced em endpoints
- [ ] request_id em todos os logs
- [ ] Health check robusto (/health)
- [ ] Middleware de auth (sessão + workspace_id)

#### P1 (Should Have)
- [ ] Logout invalidando sessão
- [ ] Tempo de expiração de sessão configurável

#### P2 (Nice to Have)
- [ ] Session debugging endpoint
- [ ] Multi-session support

**Estimativa:** 5 dias
**Definition of Done:** Login/logout funciona com sessão persistente, RBAC enforced, request_id em logs, /health retorna status correto

---

### Fase 1 — Isolamento e Persistência

#### P0 (Must Have)
- [ ] CRUD de tenants (persistence)
- [ ] CRUD de usuários (persistence)
- [ ] Isolamento verificado (3 tenants)
- [ ] Suite TKT-010 de não-vazamento
- [ ] Admin: proteção de tenant bootstrap

#### P1 (Should Have)
- [ ] Tenant com dados: não pode ser removido
- [ ] Validação de workspace_id em todas as queries

#### P2 (Nice to Have)
- [ ] Admin UI para gestão de tenants
- [ ] Bulk user import

**Estimativa:** 8 dias
**Definition of Done:** Tenant com dados não pode ser removido, 3 tenants ativos sem vazamento, TKT-010 suite passa

---

### Fase 2 — Dataset e Avaliação

#### P0 (Must Have)
- [ ] Dataset de 20+ perguntas reais
- [ ] Hit rate top-5 >= 60%
- [ ] Framework de avaliação executável
- [ ] Métricas por tenant

#### P1 (Should Have)
- [ ] Dataset com ground truth
- [ ] Relatório de avaliação automática
- [ ] Dashboard de métricas

#### P2 (Nice to Have)
- [ ] Dataset de 100+ perguntas
- [ ] Integração com LangSmith
- [ ] A/B testing de retrieval

**Estimativa:** 10 dias
**Definition of Done:** Dataset existe e é executável, hit_rate_top5 >= 60%, gates verificáveis

---

### Fase 3 — Observabilidade Enterprise

#### P0 (Must Have)
- [ ] request_id ponta a ponta
- [ ] SLI/SLO definidos
- [ ] Dashboard executivo
- [ ] Alertas configurados
- [ ] Tracing completo

#### P1 (Should Have)
- [ ] Métricas por tenant
- [ ] Log aggregation
- [ ] Alert escalation

#### P2 (Nice to Have)
- [ ] SLA formal com cliente
- [ ] Automated incident creation
- [ ] Runbook integration

**Estimativa:** 7 dias
**Definition of Done:** Traces completos, alertas configurados, dashboard legível

---

### Fase 4 — Hardening e Release

#### P0 (Must Have)
- [ ] TypeScript checks pass (tsc --noEmit)
- [ ] Smoke tests estáveis
- [ ] Suite pytest conclusiva
- [ ] Reauditoria formal
- [ ] Gate F3 aprovado

#### P1 (Should Have)
- [ ] Performance benchmarks
- [ ] Load testing
- [ ] Security scan

#### P2 (Nice to Have)
- [ ] Automated release notes
- [ ] Changelog generation
- [ ] Post-mortem template

**Estimativa:** 5 dias
**Definition of Done:** TSC --noEmit passa, smoke tests passam, pytest passa, gate F3 aprovado

---

## User Stories por Módulo

### Auth Module
- **US-001:** Como usuário, quero fazer login com email/senha para acessar o sistema
- **US-002:** Como operador, quero fazer logout para invalidar minha sessão
- **US-003:** Como admin, quero que o sistema valide permissões em cada endpoint

### Ingestion Module
- **US-004:** Como operador, quero fazer upload de documentos para que sejam indexados
- **US-005:** Como operador, quero visualizar o status do processamento dos meus documentos
- **US-006:** Como admin, quero poder reprocessar documentos com problema

### Retrieval Module
- **US-007:** Como usuário, quero buscar por documentos relevantes para minha query
- **US-008:** Como sistema, quero ranquear resultados usando RRF para melhor precisão

### Query/RAG Module
- **US-009:** Como usuário, quero fazer perguntas e receber respostas com citações
- **US-010:** Como usuário, quero saber quando a confiança da resposta é baixa

### Admin Module
- **US-011:** Como admin, quero criar e gerenciar tenants para organizar workspaces
- **US-012:** Como admin, quero criar e gerenciar usuários para controlar acesso
- **US-013:** Como admin, quero visualizar logs de auditoria para rastrear ações

### Telemetry Module
- **US-014:** Como admin, quero visualizar métricas para monitorar o sistema
- **US-015:** Como sistema, quero gerar alertas quando SLI violar SLO

---

## Priorização

### Matriz de Priorização
| | Impacto Alto | Impacto Baixo |
|---|---|---|
| **Esforço Alto** | F0 Auth, F1 Isolamento | F3 Observabilidade |
| **Esforço Baixo** | F2 Dataset, F4 Hardening | — |

### Foco de Execução
1. **F0 Auth** (Alto Impacto, Alto Esforço) — Baseia todo o sistema
2. **F1 Isolamento** (Alto Impacto, Alto Esforço) — Diferenciador enterprise
3. **F2 Dataset** (Alto Impacto, Baixo Esforço) — Validação objetiva
4. **F3 Observabilidade** (Baixo Impacto, Alto Esforço) — Operação profissional
5. **F4 Hardening** (Baixo Impacto, Baixo Esforço) — Consolidação

---

## Definition of Done por Feature

### Feature: Session Persistence
- [ ] Sessão armazenada em memória do servidor
- [ ] Session ID retornado ao cliente
- [ ] Session ID válido em todas as requests
- [ ] Logout destrói sessão
- [ ] Sessão expira após timeout

### Feature: RBAC
- [ ] Roles definidos (admin, operator, viewer)
- [ ] Middleware valida role em cada endpoint
- [ ] Usuário não pode acessar endpoint sem role
- [ ] Logs registram tentativa de acesso negado

### Feature: Tenant Isolation
- [ ] Queries filtradas por workspace_id
- [ ] Dados de um tenant não vazam para outro
- [ ] Suite de não-vazamento passa
- [ ] Admin não pode ver dados de outro tenant

### Feature: Hybrid Search
- [ ] Dense vectors (OpenAI embeddings)
- [ ] Sparse vectors (BM25)
- [ ] RRF fusion
- [ ] Top-k results com scores

### Feature: RAG with Citations
- [ ] Contexto recuperado e passado ao LLM
- [ ] Citações incluídas na resposta
- [ ] Groundness check
- [ ] Low confidence warning

---

## Próximo Passo

Avançar para 0120_spec_master.md