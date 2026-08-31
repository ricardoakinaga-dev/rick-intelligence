---
name: build-engine
description: Usar quando a SPEC estiver aprovada e for necessário executar a construção faseada do sistema. NÃO usar sem SPEC validada (0190_spec_validation.md aprovado), NÃO usar para fazer código sem planejamento completo (BUILD ENGINE MASTER + ROADMAP + BACKLOG).
---

# CONTEXTO

O build-engine é responsável por executar a construção do sistema conforme especificado no SPEC. Ele segue o padrão PHASE → SPRINT → TASK e garante execução controlada, rastreável e auditável.

O build-engine NÃO inventa, NÃO altera escopo, NÃO muda arquitetura. Ele executa o que está na SPEC e no BUILD documentation.

---

# PRÉ-CONDIÇÕES

Antes de iniciar o BUILD, verificar:
1. **EXISTE** `0190_spec_validation.md` aprovado
2. **EXISTE** `/docs/02_spec/` completo (19+ documentos)
3. **EXISTE** `/docs/03_build/` com:
   - `0300_build_engineer_master.md`
   - `0301_roadmap.md`
   - `0302_BACKLOG_MASTER.md`
   - Sprint definitions

---

# EXECUÇÃO

## Fase -1: Pré-Build (Gate Check)
1. Verificar `0390_build_gate.md` — todos os critérios devem estar ✅
2. Criar `/docs/20_master_execution_log.md` se não existir
3. Criar `/docs/30_backlog_master.md` se não existir

## Fase 0: Estrutura de Execução
1. Organizar construção em PHASE → SPRINT → TASK
2. Definir ordem de execução

## Fase 1: Phase 0 — Fundação
1. Executar Sprint 0.1: Auth Module Básico
2. Executar Sprint 0.2: Session Persistence
3. Executar Sprint 0.3: RBAC Middleware
4. Executar Sprint 0.4: Telemetry + Health
5. Gerar relatório PHASE0_REPORT.md

## Fase 2: Phase 1 — Isolamento e Persistência
1. Executar Sprint 1.1: Admin Module CRUD
2. Executar Sprint 1.2: Tenant Isolation
3. Executar Sprint 1.3: Non-Leakage Suite
4. Gerar relatório PHASE1_REPORT.md

## Fase 3: Phase 2 — Dataset e Avaliação
1. Executar Sprint 2.1: Retrieval Module
2. Executar Sprint 2.2: Query/RAG Module
3. Executar Sprint 2.3: Evaluation Framework
4. Gerar relatório PHASE2_REPORT.md

## Fase 4: Phase 3 — Observabilidade Enterprise
1. Executar Sprint 3.1: Advanced Tracing
2. Executar Sprint 3.2: SLI/SLO + Alerts
3. Executar Sprint 3.3: Dashboard
4. Gerar relatório PHASE3_REPORT.md

## Fase 5: Phase 4 — Hardening e Release
1. Executar Sprint 4.1: TypeScript Checks
2. Executar Sprint 4.2: Smoke Tests
3. Executar Sprint 4.3: Final Audit
4. Gerar relatório PHASE4_REPORT.md

## Fase 6: Gate Final
1. Verificar todos os gates de phase
2. Entregar RELATÓRIO FINAL DE BUILD

---

# ESTRUTURA DE SPRINT

Cada sprint deve conter:

### O QUE
Descrição objetiva do que será feito

### ONDE
Arquivo, módulo, domínio ou camada afetada

### COMO
Abordagem de execução baseada na SPEC

### DEPENDÊNCIA
Pré-requisitos técnicos ou funcionais

### CRITÉRIO DE PRONTO
O que precisa existir no final da entrega

---

# ESTADO

## Estados Válidos
| Estado | Significado |
|---|---|
| IN_PROGRESS | Execução em andamento |
| BLOCKED | Sprint bloqueado por dependência |
| WAITING_HUMAN_APPROVAL | Decisão de implementação necessária |
| READY_FOR_NEXT_STEP | Sprint concluído, próximo disponível |
| COMPLETED | Build completo |

## Atualizações de Estado
Após cada sprint:
- Atualizar `current_engine` para "BUILD"
- Atualizar `current_phase` e `current_sprint`
- Atualizar `last_completed_action`
- Atualizar `next_action`
- Atualizar `status`

---

# LOOP

O build-engine segue este loop operacional:

```
LER ESTADO → EXECUTAR SPRINT → VALIDAR → AUDITAR → REGISTRAR → ATUALIZAR ESTADO → PRÓXIMO SPRINT
```

### Regras do Loop
1. **LER** `/docs/99_runtime_state.md` no início de cada iteração
2. **EXECUTAR** sprint conforme planejamento
3. **VALIDAR** critérios de pronto
4. **AUDITAR** sprint (aderência à SPEC, qualidade, contratos)
5. **REGISTRAR** no execution log
6. **ATUALIZAR** estado, log e backlog
7. **DECIDIR** próximo sprint ou bloqueio

### Término do Loop
O loop termina quando:
- Todas as 4 phases concluídas
- Gate F3 aprovado
- `status: COMPLETED`

---

# SAÍDA

Ao final do BUILD, os seguintes artefatos devem existir:

| Artefato | Descrição |
|---|---|
| Código fonte completo | Sistema implementado |
| `0390_build_gate.md` | Gate de build |
| `20_master_execution_log.md` | Log de todas as execuções |
| `30_backlog_master.md` | Backlog atualizado |
| PHASE*_REPORT.md (4) | Relatórios de cada phase |
| Sprint audits | Auditoria de cada sprint |
| Gate F3 | Validação final |

---

# GATE DE TRANSIÇÃO

O build-engine só libera `audit-engine` se:
- Sistema funcional em dev/staging/produção
- Gate F3 aprovado (SPEC requirements)
- `0390_build_gate.md` com todos os critérios ✅

---

# REGRA FINAL

O build-engine NÃO pode:
- Começar sem SPEC aprovada
- Codar sem planejamento (BUILD documentation)
- Executar sprint fora da ordem definida
- Avançar sem validar criteria de pronto
- Encerrar sem atualizar log e estado

O build-engine DEVE:
- Executar conforme SPEC
- Manter rastreabilidade BUILD → SPEC
- Validar cada sprint antes de avançar
- Auditar aderência à especificação
- Atualizar estado e log
