---
name: discovery-engine
description: Usar quando existir uma ideia, dor, gargalo ou oportunidade ainda mal definida que precisa ser investigada e documentada. NÃO usar se já existir discovery aprovado (0090_discovery_validation.md) ou se o problema já estiver claro e definido.
---

# CONTEXTO

O discovery-engine é responsável por investigar, analisar e documentar um problema, oportunidade ou situação antes de definir qualquer produto ou solução. Ele transforma incerteza em informação estruturada.

O discovery-engine opera no domínio de **problema**, não de solução. Seu trabalho é responder:
- O que está acontecendo?
- Onde e quando acontece?
- Quem é afetado?
- Quais são as causas raiz?
- O que aconteceria se não resolvêssemos?

---

# PRÉ-CONDIÇÕES

Antes de iniciar o discovery, verificar:
1. NÃO existe `0090_discovery_validation.md` aprovado
2. NÃO existe `/docs/00_discovery/` com conteúdo completo
3. O problema/oportunidade ainda não foi formalmente investigado

---

# EXECUÇÃO

## Fase 1: Investigação
1. Ler o estado atual em `/docs/99_runtime_state.md`
2. Identificar o domínio/área do problema
3. mapear stakeholderes e usuários afetados
4. documentar a dor/oportunidade

## Fase 2: Análise
1. Criar `/docs/00_discovery/0001_analise_da_dor.md`
2. Criar `/docs/00_discovery/0002_contexto_operacional.md`
3. Criar `/docs/00_discovery/0003_fluxo_atual.md`
4. Criar `/docs/00_discovery/0004_problem_framing.md`

## Fase 3: Hipóteses
1. Criar `/docs/00_discovery/0005_hipotese_de_valor.md`
2. Criar `/docs/00_discovery/0006_usuarios_e_stakeholders.md`
3. Criar `/docs/00_discovery/0007_riscos_e_hipoteses.md`

## Fase 4: Consolidação
1. Criar `/docs/00_discovery/0009_discovery_master.md`
2. Criar `/docs/00_discovery/0090_discovery_validation.md`
3. Atualizar `/docs/20_master_execution_log.md`

---

# ESTADO

## Estados Válidos
| Estado | Significado |
|---|---|
| IN_PROGRESS | Investigação em andamento |
| BLOCKED | Investigação bloqueada por falta de informação |
| WAITING_HUMAN_APPROVAL | Necessita decisão sobre escopo ou priorização |
| READY_FOR_NEXT_STEP | Etapa concluída, pronta para próxima |
| COMPLETED | Discovery completo e validado |

## Atualizações de Estado
Após cada ação:
- Atualizar `current_phase` para "discovery"
- Atualizar `last_completed_action` com o que foi feito
- Atualizar `next_action` com o próximo passo
- Atualizar `status` conforme progresso

---

# LOOP

O discovery-engine segue este loop operacional:

```
LER ESTADO → INVESTIGAR → ANALISAR → DOCUMENTAR → VALIDAR → ATUALIZAR ESTADO → DECIDIR PRÓXIMO PASSO
```

### Regras do Loop
1. **LER** `/docs/99_runtime_state.md` no início de cada iteração
2. **EXECUTAR** uma etapa por vez
3. **VALIDAR** o resultado antes de avançar
4. **ATUALIZAR** estado, log e backlog após cada etapa
5. **DECIDIR** o próximo passo ou bloqueio

### Término do Loop
O loop termina quando:
- `0090_discovery_validation.md` existe e está aprovado
- `status: COMPLETED` em `/docs/99_runtime_state.md`

---

# SAÍDA

Ao final do discovery, os seguintes artefatos devem existir:

| Artefato | Descrição |
|---|---|
| `0000_trigger.md` | Gatilho/origem do discovery |
| `0001_analise_da_dor.md` | Análise da dor/problema |
| `0002_contexto_operacional.md` | Contexto operacional |
| `0003_fluxo_atual.md` | Fluxo atual documentado |
| `0004_problem_framing.md` | Delimitação do problema |
| `0005_hipotese_de_valor.md` | Hipótese de valor |
| `0006_usuarios_e_stakeholders.md` | Usuários e stakeholders |
| `0007_riscos_e_hipoteses.md` | Riscos e hipóteses |
| `0009_discovery_master.md` | Consolidação do discovery |
| `0090_discovery_validation.md` | Gate de validação |

---

# REGRA FINAL

O discovery-engine NÃO pode:
- Definir solução ou produto
- Criar PRD ou SPEC
- Avançar para PRD sem gate aprovado
- Encerrar sem atualizar estado

O discovery-engine DEVE:
- Manter foco em problema
- Documentar com evidências
- Manter rastreabilidade
- Atualizar estado e log
