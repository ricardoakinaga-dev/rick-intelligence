# 0301 — ROADMAP.md

## Roadmap de Construção — RAG Enterprise Premium

---

## PHASE 0 — Fundação

### Objetivo
Criar base operacional com auth server-side e telemetry essencial.

### Entregáveis
- Session persistence no servidor
- Login/logout funcional
- RBAC enforced em endpoints
- request_id em todos os logs
- Health check robusto (/health)

### Riscos
- Breaking change no frontend existente
- Migração de headers para sessão

### Dependências
- Nenhuma (base)

### Critérios de Sucesso
- Login/logout funciona com sessão persistente
- RBAC enforced no servidor
- request_id em todos os logs
- /health retorna status correto

---

## PHASE 1 — Isolamento e Persistência

### Objetivo
Provar isolamento multi-tenant e persistência admin.

### Entregáveis
- CRUD de tenants persistence
- CRUD de usuários persistence
- Isolamento verificado (3 tenants)
- Suite de não-vazamento
- Proteção de tenant bootstrap

### Riscos
- Gap entre código e docs atual
- Validação de isolamento

### Dependências
- Phase 0 (Auth)

### Critérios de Sucesso
- Tenant com dados não pode ser removido
- 3 tenants ativos sem vazamento
- TKT-010 suite passa

---

## PHASE 2 — Dataset e Avaliação

### Objetivo
Criar dataset real e validação objetiva.

### Entregáveis
- Dataset de 20+ perguntas reais
- Hit rate top-5 >= 60%
- Framework de avaliação executável
- Métricas por tenant

### Riscos
- Dataset não representa realidade

### Dependências
- Phase 0 (Auth)
- Phase 1 (Isolamento)

### Critérios de Sucesso
- Dataset existe e é executável
- hit_rate_top5 >= 60%
- Gates verificáveis

---

## PHASE 3 — Observabilidade Enterprise

### Objetivo
Completar observabilidade para operação enterprise.

### Entregáveis
- request_id ponta a ponta
- SLI/SLO definidos
- Dashboard executivo
- Alertas configurados
- Tracing completo

### Riscos
- Overhead de logging

### Dependências
- Phase 0, 1, 2

### Critérios de Sucesso
- Traces completos
- Alertas configurados
- Dashboard legível

---

## PHASE 4 — Hardening e Release

### Objetivo
Consolidar e liberar gate F3.

### Entregáveis
- TypeScript checks pass (tsc --noEmit)
- Smoke tests estáveis
- Suite pytest conclusiva
- Reauditoria formal
- Gate F3 aprovado

### Riscos
- Regressões

### Dependências
- Phase 3

### Critérios de Sucesso
- TSC --noEmit passa
- Smoke tests passam
- pytest passa
- Gate F3 aprovado

---

## Timeline Sugerida

| Phase | Estimativa | Acumulado |
|---|---|---|
| Phase 0 — Fundação | 5 dias | 5 dias |
| Phase 1 — Isolamento | 8 dias | 13 dias |
| Phase 2 — Dataset | 10 dias | 23 dias |
| Phase 3 — Observabilidade | 7 dias | 30 dias |
| Phase 4 — Hardening | 5 dias | 35 dias |
| **Total** | **35 dias** | — |

---

## Sprint Breakdown

### Phase 0
- Sprint 0.1: Auth Module básico
- Sprint 0.2: Session persistence
- Sprint 0.3: RBAC middleware
- Sprint 0.4: Telemetry + Health

### Phase 1
- Sprint 1.1: Admin Module CRUD
- Sprint 1.2: Tenant isolation
- Sprint 1.3: Suite não-vazamento

### Phase 2
- Sprint 2.1: Retrieval Module
- Sprint 2.2: Query/RAG Module
- Sprint 2.3: Evaluation framework

### Phase 3
- Sprint 3.1: Tracing avançado
- Sprint 3.2: SLI/SLO + Alertas
- Sprint 3.3: Dashboard

### Phase 4
- Sprint 4.1: TypeScript checks
- Sprint 4.2: Smoke tests
- Sprint 4.3: Final audit

---

## Próximo Passo

Avançar para 0302_BACKLOG_MASTER.md