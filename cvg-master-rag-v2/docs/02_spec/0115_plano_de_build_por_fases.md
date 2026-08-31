# 0115 — Plano de Build por Fases

## Estrutura de Fases

### Fase 0 — Fundação
**Objetivo:** Criar base operacional e auth real

**Módulos envolvidos:**
- Auth Module (servidor)
- Telemetry Module (logs e health)

**Entregáveis:**
- Session persistence no servidor
- RBAC em endpoints
- request_id em logs
- Health check robusto

**Riscos:**
- Breaking change no frontend existente
- Migração de headers para sessão

**Dependências:**
- Nenhuma (base)

**Critérios de pronto:**
- Login/logout funciona com sessão persistente
- RBAC enforced no servidor
- request_id em todos os logs
- /health retorna status correto

---

### Fase 1 — Isolamento e Persistência
**Objetivo:** Provar isolamento multi-tenant e persistência admin

**Módulos envolvidos:**
- Admin Module
- Tenant isolation in all services

**Entregáveis:**
- CRUD de tenants persistence
- CRUD de usuários persistence
- Isolamento verificado (3 tenants)
- Suite de não-vazamento

**Riscos:**
- Gap entre código e docs atual
- Validação de isolamento

**Dependências:**
- Fase 0 (auth)

**Critérios de pronto:**
- Tenant com dados não pode ser removido
- 3 tenants ativos sem vazamento
- TKT-010 suite passa

---

### Fase 2 — Dataset e Avaliação
**Objetivo:** Criar dataset real e validação objetiva

**Módulos envolvidos:**
- Evaluation service
- Telemetry (métricas)

**Entregáveis:**
- Dataset de 20+ perguntas reais
- Hit rate top-5 >= 60%
- Métricas por tenant

**Riscos:**
- Dataset não representa realidade

**Dependências:**
- Fase 0 (auth)
- Fase 1 (isolamento)

**Critérios de pronto:**
- Dataset existe e é executável
- hit_rate_top5 >= 60%
- Gates verificáveis

---

### Fase 3 — Observabilidade Enterprise
**Objetivo:** Completar observabilidade para operação

**Módulos envolvidos:**
- Telemetry (métricas avançadas)
- Alertas

**Entregáveis:**
- request_id ponta a ponta
- Métricas por tenant
- SLI/SLO definidos
- Dashboard executivo

**Riscos:**
- Overhead de logging

**Dependências:**
- Fase 0, 1, 2

**Critérios de pronto:**
- Traces completos
- Alertas configurados
- Dashboard legível

---

### Fase 4 — Hardening e Release
**Objetivo:** Consolidar e liberar gate F3

**Módulos envolvidos:**
- Todos

**Entregáveis:**
- TypeScript checks pass
- Smoke tests estáveis
- Suite pytest conclusiva
- Reauditoria formal

**Riscos:**
- Regressões

**Dependências:**
- Fase 3

**Critérios de pronto:**
- TSC --noEmit passa
- Smoke tests passam
- pytest passa
- Gate F3 aprovado

---

## Critérios de Auditoria por Fase

| Fase | Critério |
|---|---|
| F0 | Auth server-side funcionando, RBAC enforced |
| F1 | Isolamento provado com suite |
| F2 | Dataset real validado |
| F3 | Observabilidade completa |
| F4 | Reauditoria aprova gate F3 |

---

## Próximo Passo

Avançar para 0116_matriz_de_dependencias.md