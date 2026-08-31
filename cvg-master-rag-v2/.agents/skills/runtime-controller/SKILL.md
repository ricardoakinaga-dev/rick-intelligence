---
name: runtime-controller
description: Usar para manter continuidade operacional após qualquer etapa do pipeline CVG. NÃO usar como skill principal (é auxiliar). Deve verificar e atualizar /docs/99_runtime_state.md obrigatoriamente. Preferencialmente explícito, não implícito.
---

# CONTEXTO

O runtime-controller é responsável por manter continuidade operacional e impedir perda de contexto entre execuções. Ele é o guardião do estado e deve ser invoked após qualquer engine executar uma etapa.

O runtime-controller opera no domínio de **controle**, não de conteúdo. Ele não cria PRD, SPEC ou código. Ele garante que o estado esteja correto e que o próximo passo esteja definido.

---

# PRÉ-CONDIÇÕES

Antes de invocar o runtime-controller:
1. Alguma engine (discovery/prd/spec/build/audit) executou uma ação
2. O estado em `/docs/99_runtime_state.md` precisa ser atualizado
3. O log em `/docs/20_master_execution_log.md` precisa de novo entry
4. O backlog em `/docs/30_backlog_master.md` pode precisar update

---

# EXECUÇÃO

## Passo 1: Ler Estado Atual
1. Ler `/docs/99_runtime_state.md`
2. Identificar:
   - `current_engine` atual
   - `current_phase` atual
   - `current_sprint` atual
   - `current_task` atual
   - `status` atual
   - `last_completed_action`
   - `next_action`

## Passo 2: Validar Consistência
1. Verificar se `last_completed_action` está coerente com estado atual
2. Verificar se `next_action` está definido
3. Verificar se status é válido (IN_PROGRESS, BLOCKED, etc.)

## Passo 3: Atualizar Estado
Se ação foi completada:
1. Mover `last_completed_action` para histórico (se aplicável)
2. Definir novo `next_action`
3. Atualizar `current_phase/sprint/task` se aplicável
4. Atualizar `status` para:
   - `READY_FOR_NEXT_STEP` se próximo passo definido
   - `BLOCKED` se há bloqueio
   - `WAITING_HUMAN_APPROVAL` se decisão necessária
   - `COMPLETED` se tarefa finalizada

## Passo 4: Atualizar Log
1. Adicionar entry em `/docs/20_master_execution_log.md`
2. Registrar:
   - timestamp
   - engine
   - phase
   - sprint
   - task
   - action executada
   - result
   - decisions
   - status

## Passo 5: Atualizar Backlog (se aplicável)
1. Verificar `/docs/30_backlog_master.md`
2. Marcar item como completo se applicable
3. Mover para próximo item elegível

## Passo 6: Verificar Bloqueios
Se `blockers` não está vazio:
1. `status` deve ser `BLOCKED`
2. `human_decision_required` deve ser `yes` se aplicável
3. `decision_description` deve estar preenchido

---

# ESTADO

## Estados Válidos (Runtime Controller)
| Estado | Significado |
|---|---|
| IN_PROGRESS | Execução ativa em curso |
| BLOCKED | Execução impedida por bloqueio |
| WAITING_HUMAN_APPROVAL | Aguardando decisão humana |
| READY_FOR_NEXT_STEP | Pronto para próximo passo |
| COMPLETED | Etapa/engine completo |

## Transições de Estado
| De | Para | Condição |
|---|---|---|
| IN_PROGRESS | READY_FOR_NEXT_STEP | Sprint/task concluído |
| IN_PROGRESS | BLOCKED | Bloqueio identificado |
| IN_PROGRESS | WAITING_HUMAN_APPROVAL | Decisão necessária |
| BLOCKED | READY_FOR_NEXT_STEP | Bloqueio resolvido |
| WAITING_HUMAN_APPROVAL | READY_FOR_NEXT_STEP | Decisão recebida |
| READY_FOR_NEXT_STEP | IN_PROGRESS | Próximo passo iniciado |

---

# LOOP

O runtime-controller segue este loop operacional:

```
LER ESTADO → VALIDAR CONSISTÊNCIA → ATUALIZAR ESTADO → ATUALIZAR LOG → ATUALIZAR BACKLOG → VERIFICAR BLOQUEIOS → DEFINIR PRÓXIMO PASSO
```

### Regras do Loop
1. **SEMPRE** ler `/docs/99_runtime_state.md` primeiro
2. **SEMPRE** atualizar estado após qualquer ação de outra engine
3. **SEMPRE** adicionar entry no log
4. **SEMPRE** definir `next_action`
5. **SEMPRE** verificar bloqueios antes de definir próximo passo

### Término do Loop
O loop termina quando:
- Estado consistente
- Log atualizado
- Próximo passo definido (ou completion status)

---

# SAÍDA

Ao invocar o runtime-controller, garantir que:

| Artefato | Status |
|---|---|
| `/docs/99_runtime_state.md` | Atualizado |
| `/docs/20_master_execution_log.md` | Entry adicionada |
| `/docs/30_backlog_master.md` | Atualizado se aplicável |
| `next_action` | Definido |
| `status` | Válido |

---

# REGRAS DE IMPEDIMENTO

O runtime-controller está PROIBIDO de:
- Encerrar sem atualizar estado
- Encerrar sem registrar próximo passo
- Encerrar com status inválido
- Ignorar bloqueios registrados
- Deixar `human_decision_required: yes` sem `decision_description`

O runtime-controller DEVE:
- Impedir encerramento sem estado
- Manter rastreabilidade
- Registrar bloqueios claramente
- Atualizar log com cada ação
- Sempre definir próximo passo ou completion

---

# REGRA FINAL

> Agente sem estado é agente imprevisível
> Runtime-controller com estado é sistema controlado

O runtime-controller não cria conteúdo, mas impede que outras engines percam contexto. Ele é o guardião da continuidade operacional do sistema CVG.
