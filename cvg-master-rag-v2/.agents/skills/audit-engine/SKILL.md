---
name: audit-engine
description: Usar quando o sistema estiver funcional em dev, staging ou produção e precisar de validação real contra PRD, SPEC e práticas enterprise. NÃO usar antes do sistema ter execução observável, NÃO usar apenas com código sem documentação SPEC.
---

# CONTEXTO

O audit-engine é responsável por auditar sistemas em runtime, staging ou produção, garantindo confiabilidade, observabilidade, segurança e aderência ao PRD e SPEC. Ele identifica GAPs, riscos, falhas e oportunidades de hardening.

O audit-engine opera no domínio de **realidade**, não de planejamento. Ele observa:
- Como o sistema se comporta?
- O sistema está aderente à SPEC?
- Existem GAPs entre código e especificação?
- Os logs são investigáveis?
- As métricas são visíveis?

---

# PRÉ-CONDIÇÕES

Antes de iniciar a AUDIT, verificar:
1. **EXISTE** sistema funcional (código em execução)
2. **EXISTE** `/docs/02_spec/` completo (SPEC aprovada)
3. **EXISTE** `/docs/01_prd/` completo (PRD aprovado)
4. Logs e métricas disponíveis para análise

---

# EXECUÇÃO

## Fase 0: Preparação
1. Criar `/docs/04_audit/0400_audit_scope.md`
2. Criar `/docs/04_audit/0401_audit_plan.md`

## Fase 1: Aderência ao PRD
1. Criar `/docs/04_audit/0410_prd_adherence_audit.md`

## Fase 2: Aderência à SPEC
1. Criar `/docs/04_audit/0411_spec_adherence_audit.md`

## Fase 3: Runtime Analysis
1. Criar `/docs/04_audit/0412_runtime_analysis.md`

## Fase 4: Logs Audit
1. Criar `/docs/04_audit/0413_logs_audit.md`

## Fase 5: Metrics Audit
1. Criar `/docs/04_audit/0414_metrics_audit.md`

## Fase 6: Integrations Audit
1. Criar `/docs/04_audit/0415_integrations_audit.md`

## Fase 7: Data Integrity Audit
1. Criar `/docs/04_audit/0416_data_integrity_audit.md`

## Fase 8: Security Governance Audit
1. Criar `/docs/04_audit/0417_security_governance_audit.md`

## Fase 9: Operational Experience Audit
1. Criar `/docs/04_audit/0418_operational_experience_audit.md`

## Fase 10: GAP Analysis
1. Criar `/docs/04_audit/0420_gap_analysis.md`

## Fase 11: Remediation Plan
1. Criar `/docs/04_audit/0421_remediation_plan.md`

## Fase 12: Relatório Final
1. Criar `/docs/04_audit/0490_audit_report.md`
2. Atualizar `/docs/20_master_execution_log.md`

---

# ESTADO

## Estados Válidos
| Estado | Significado |
|---|---|
| IN_PROGRESS | Auditoria em andamento |
| BLOCKED | Auditoria bloqueada por falta de dados |
| WAITING_HUMAN_APPROVAL | GAP crítico requer decisão |
| READY_FOR_NEXT_STEP | Fase concluída |
| COMPLETED | Auditoria completa |

## Atualizações de Estado
Após cada fase:
- Atualizar `current_engine` para "AUDIT"
- Atualizar `current_phase`
- Atualizar `last_completed_action`
- Atualizar `next_action`
- Atualizar `status`

---

# LOOP

O audit-engine segue este loop operacional:

```
LER ESTADO → AUDITAR ÁREA → REGISTRAR FINDINGS → ATUALIZAR ESTADO → PRÓXIMA ÁREA
```

### Regras do Loop
1. **LER** `/docs/99_runtime_state.md` no início de cada iteração
2. **AUDITAR** cada área conforme audit plan
3. **CLASSIFICAR** findings (✔ aderente, ⚠️ parcial, ❌ divergente)
4. **IDENTIFICAR** GAPs e riscos
5. **CRIAR** plano de remediação
6. **ATUALIZAR** estado e log

### Término do Loop
O loop termina quando:
- Todas as 12 fases de auditoria concluídas
- `0490_audit_report.md` existe
- `status: COMPLETED`

---

# SAÍDA

Ao final da AUDIT, os seguintes artefatos devem existir:

| Artefato | Descrição |
|---|---|
| `0400_audit_scope.md` | Escopo da auditoria |
| `0401_audit_plan.md` | Plano de auditoria |
| `0410_prd_adherence_audit.md` | Aderência ao PRD |
| `0411_spec_adherence_audit.md` | Aderência à SPEC |
| `0412_runtime_analysis.md` | Análise de runtime |
| `0413_logs_audit.md` | Auditoria de logs |
| `0414_metrics_audit.md` | Auditoria de métricas |
| `0415_integrations_audit.md` | Auditoria de integrações |
| `0416_data_integrity_audit.md` | Auditoria de integridade de dados |
| `0417_security_governance_audit.md` | Auditoria de segurança |
| `0418_operational_experience_audit.md` | Auditoria de UX |
| `0420_gap_analysis.md` | Análise de GAPs |
| `0421_remediation_plan.md` | Plano de remediação |
| `0490_audit_report.md` | Relatório final |

---

# CLASSIFICAÇÃO DE FINDINGS

| Classificação | Significado |
|---|---|
| ✔ Aderente | Implementado conforme especificação |
| ⚠️ Parcial | Implementação em progresso ou com desvios menores |
| ❌ Divergente | Não implementado ou com desvios significativos |

---

# GAPs

| Severidade | Significado |
|---|---|
| 🔴 Crítico | Sistema não funcional ou risco de segurança |
| 🟠 Importante | Funcionalidade degradada ou risco moderado |
| 🟡 Melhoria | Oportunidade de otimização |

---

# REGRA FINAL

O audit-engine NÃO pode:
- Auditar sem evidência (logs, métricas, código)
- Ignorar runtime (só código não basta)
- Ignorar logs
- Mascarar problemas críticos
- Encerrar sem plano de remediação

O audit-engine DEVE:
- Auditar com evidências reais
- Identificar GAPs com causa raiz
- Criar plano de remediação acionável
- Atualizar estado e log
