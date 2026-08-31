---
name: prd-engine
description: Usar quando o discovery estiver aprovado e for necessário transformar o problema investigado em produto/solução definida. NÃO usar se o discovery estiver incompleto, se não existir 0090_discovery_validation.md aprovado, ou se o problema ainda não foi formalmente descoberto.
---

# CONTEXTO

O prd-engine é responsável por transformar o problema descoberto em produto. Ele define O QUÊ será construído, não COMO será construído. O PRD responde:
- O que este produto resolve?
- Quem são os usuários?
- Quais são os casos de uso?
- Quais são as regras de negócio?
- Como medimos sucesso?

---

# PRÉ-CONDIÇÕES

Antes de iniciar o PRD, verificar:
1. **EXISTE** `0090_discovery_validation.md` aprovado
2. **EXISTE** `/docs/00_discovery/` completo (9+ documentos)
3. O problema está formalmente documentado

---

# EXECUÇÃO

## Fase 1: Visão do Produto
1. Ler `/docs/00_discovery/` para consumir discovery aprovado
2. Criar `/docs/01_prd/0001_visao_inicial.md`
3. Criar `/docs/01_prd/0002_problema_oportunidade.md`

## Fase 2: Stakeholders e Usuários
1. Criar `/docs/01_prd/0003_stakeholders_usuarios.md`
2. Criar `/docs/01_prd/0004_fluxo_atual.md`

## Fase 3: Análise de Risco e Hipóteses
1. Criar `/docs/01_prd/0005_riscos_hipoteses.md`

## Fase 4: Casos de Uso
1. Criar `/docs/01_prd/0010_casos_de_uso.md` (CU-01 a CU-11)

## Fase 5: Escopo e Regras
1. Criar `/docs/01_prd/0011_escopo_fase.md`
2. Criar `/docs/01_prd/0012_regras_de_negocio.md`

## Fase 6: Requisitos
1. Criar `/docs/01_prd/0013_requisitos_funcionais.md`
2. Criar `/docs/01_prd/0014_requisitos_nao_funcionais_produto.md`

## Fase 7: Métricas de Sucesso
1. Criar `/docs/01_prd/0015_metricas_de_sucesso.md`

## Fase 8: Consolidação
1. Criar `/docs/01_prd/0020_prd_master.md`
2. Criar `/docs/01_prd/0090_prd_validation.md`
3. Atualizar `/docs/20_master_execution_log.md`

---

# ESTADO

## Estados Válidos
| Estado | Significado |
|---|---|
| IN_PROGRESS | Construção de PRD em andamento |
| BLOCKED | PRD bloqueado por dependência não resolvida |
| WAITING_HUMAN_APPROVAL | Necessita decisão sobre escopo ou priorização |
| READY_FOR_NEXT_STEP | Etapa concluída, pronta para próxima |
| COMPLETED | PRD completo e validado |

## Atualizações de Estado
Após cada ação:
- Atualizar `current_engine` para "PRD"
- Atualizar `current_phase` para "01_PRD"
- Atualizar `last_completed_action` com o que foi feito
- Atualizar `next_action` com o próximo passo
- Atualizar `status` conforme progresso

---

# LOOP

O prd-engine segue este loop operacional:

```
LER ESTADO → LER DISCOVERY → DEFINIR PRODUTO → DOCUMENTAR → VALIDAR → ATUALIZAR ESTADO → DECIDIR PRÓXIMO PASSO
```

### Regras do Loop
1. **LER** `/docs/99_runtime_state.md` no início de cada iteração
2. **CONSUMIR** `/docs/00_discovery/` aprovado
3. **EXECUTAR** uma etapa por vez
4. **VALIDAR** o resultado antes de avançar
5. **ATUALIZAR** estado, log e backlog após cada etapa
6. **DECIDIR** o próximo passo ou bloqueio

### Término do Loop
O loop termina quando:
- `0090_prd_validation.md` existe e está aprovado
- `status: COMPLETED` em `/docs/99_runtime_state.md`

---

# SAÍDA

Ao final do PRD, os seguintes artefatos devem existir:

| Artefato | Descrição |
|---|---|
| `0001_visao_inicial.md` | Visão alto-nível do produto |
| `0002_problema_oportunidade.md` | Problema e oportunidade |
| `0003_stakeholders_usuarios.md` | Matriz de stakeholders |
| `0004_fluxo_atual.md` | Fluxo atual resumido |
| `0005_riscos_hipoteses.md` | Riscos e hipóteses |
| `0010_casos_de_uso.md` | 11 casos de uso (CU-01 a CU-11) |
| `0011_escopo_fase.md` | IN SCOPE, OUT OF SCOPE, FUTURE |
| `0012_regras_de_negocio.md` | RN-01 a RN-07, REST-01 a REST-03 |
| `0013_requisitos_funcionais.md` | RF-01 a RF-10 |
| `0014_requisitos_nao_funcionais_produto.md` | RNF-01 a RNF-16 |
| `0015_metricas_de_sucesso.md` | KPIs e métricas |
| `0020_prd_master.md` | Consolidação do PRD |
| `0090_prd_validation.md` | Gate de validação |

---

# GATE DE TRANSIÇÃO

O prd-engine só libera `spec-engine` se:
- `0090_discovery_validation.md` aprovado (discovery completo)
- `0090_prd_validation.md` aprovado (PRD completo)

---

# REGRA FINAL

O prd-engine NÃO pode:
- Começar sem discovery aprovado
- Definir arquitetura ou implementação
- Avançar para SPEC sem PRD validado
- Encerrar sem atualizar estado

O prd-engine DEVE:
- Manter foco em produto (O QUÊ)
- Baselinesar em evidências do discovery
- Manter rastreabilidade PRD → Discovery
- Atualizar estado e log
