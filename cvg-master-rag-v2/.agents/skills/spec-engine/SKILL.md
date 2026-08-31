---
name: spec-engine
description: Usar quando o PRD estiver aprovado e for necessário transformar produto em engenharia — definir arquitetura, contratos, modelos e especificações técnicas. NÃO usar se o PRD estiver incompleto ou não existir 0090_prd_validation.md aprovado.
---

# CONTEXTO

O spec-engine é responsável por transformar produto em engenharia. Ele define COMO o sistema será construído, não o que será construído. O SPEC responde:
- Qual é a arquitetura?
- Quais são os módulos e suas responsabilidades?
- Quais são os contratos de API?
- Como os dados são persistidos?
- Quais são as integrações?

---

# PRÉ-CONDIÇÕES

Antes de iniciar o SPEC, verificar:
1. **EXISTE** `0090_prd_validation.md` aprovado
2. **EXISTE** `/docs/01_prd/` completo (11+ documentos)
3. O produto está formalmente definido

---

# EXECUÇÃO

## Fase 1: Readiness Review
1. Ler `/docs/01_prd/` para consumir PRD aprovado
2. Criar `/docs/02_spec/0100_spec_readiness_review.md`

## Fase 2: Arquitetura
1. Criar `/docs/02_spec/0101_visao_arquitetural.md`
2. Criar `/docs/02_spec/0102_bounded_contexts.md`
3. Criar `/docs/02_spec/0103_mapa_de_modulos.md`

## Fase 3: Domínio
1. Criar `/docs/02_spec/0104_modelo_de_dominio.md`
2. Criar `/docs/02_spec/0105_maquina_de_estados_e_fluxos.md`

## Fase 4: Contratos
1. Criar `/docs/02_spec/0106_contratos_de_aplicacao.md`
2. Criar `/docs/02_spec/0107_contratos_de_api.md`
3. Criar `/docs/02_spec/0108_contratos_de_eventos_e_assincronismo.md`

## Fase 5: Dados
1. Criar `/docs/02_spec/0109_dados_e_persistencia.md`
2. Criar `/docs/02_spec/0110_consistencia_integridade_e_migracoes.md`

## Fase 6: Segurança e Observabilidade
1. Criar `/docs/02_spec/0111_permissoes_governanca_e_auditoria.md`
2. Criar `/docs/02_spec/0112_integracoes_externas.md`
3. Criar `/docs/02_spec/0113_observabilidade_runtime_e_operacao.md`

## Fase 7: Interface e Build
1. Criar `/docs/02_spec/0114_superficie_operacional_e_frontend.md`
2. Criar `/docs/02_spec/0115_plano_de_build_por_fases.md`
3. Criar `/docs/02_spec/0116_matriz_de_dependencias.md`
4. Criar `/docs/02_spec/0117_backlog_estruturado.md`

## Fase 8: Consolidação
1. Criar `/docs/02_spec/0120_spec_master.md`
2. Criar `/docs/02_spec/0190_spec_validation.md`
3. Atualizar `/docs/20_master_execution_log.md`

---

# ESTADO

## Estados Válidos
| Estado | Significado |
|---|---|
| IN_PROGRESS | Especificação em andamento |
| BLOCKED | Especificação bloqueada por dependência |
| WAITING_HUMAN_APPROVAL | Necessita decisão técnica ou de negócio |
| READY_FOR_NEXT_STEP | Etapa concluída, pronta para próxima |
| COMPLETED | SPEC completo e validado |

## Atualizações de Estado
Após cada ação:
- Atualizar `current_engine` para "SPEC"
- Atualizar `current_phase` para "02_SPEC"
- Atualizar `last_completed_action` com o que foi feito
- Atualizar `next_action` com o próximo passo
- Atualizar `status` conforme progresso

---

# LOOP

O spec-engine segue este loop operacional:

```
LER ESTADO → LER PRD → DEFINIR ENGENHARIA → DOCUMENTAR → VALIDAR → ATUALIZAR ESTADO → DECIDIR PRÓXIMO PASSO
```

### Regras do Loop
1. **LER** `/docs/99_runtime_state.md` no início de cada iteração
2. **CONSUMIR** `/docs/01_prd/` aprovado
3. **EXECUTAR** uma etapa por vez
4. **VALIDAR** o resultado antes de avançar
5. **ATUALIZAR** estado, log e backlog após cada etapa
6. **DECIDIR** o próximo passo ou bloqueio

### Término do Loop
O loop termina quando:
- `0190_spec_validation.md` existe e está aprovado
- `status: COMPLETED` em `/docs/99_runtime_state.md`

---

# SAÍDA

Ao final do SPEC, os seguintes artefatos devem existir:

| Artefato | Descrição |
|---|---|
| `0100_spec_readiness_review.md` | Review de consumo do PRD |
| `0101_visao_arquitetural.md` | Visão arquitetural modular monolith |
| `0102_bounded_contexts.md` | 6 domínios delimitados |
| `0103_mapa_de_modulos.md` | Mapa de módulos e dependências |
| `0104_modelo_de_dominio.md` | Entidades, VOs, aggregates |
| `0105_maquina_de_estados_e_fluxos.md` | State machines |
| `0106_contratos_de_aplicacao.md` | Commands e queries |
| `0107_contratos_de_api.md` | REST endpoints |
| `0108_contratos_de_eventos_e_assincronismo.md` | Eventos de domínio |
| `0109_dados_e_persistencia.md` | Storage strategy |
| `0110_consistencia_integridade_e_migracoes.md` | Regras de integridade |
| `0111_permissoes_governanca_e_auditoria.md` | RBAC e audit trail |
| `0112_integracoes_externas.md` | OpenAI, Qdrant, Filesystem |
| `0113_observabilidade_runtime_e_operacao.md` | Logs, métricas, SLI/SLO |
| `0114_superficie_operacional_e_frontend.md` | Telas e validações |
| `0115_plano_de_build_por_fases.md` | Phase 0-4 build plan |
| `0116_matriz_de_dependencias.md` | Dependências entre módulos |
| `0117_backlog_estruturado.md` | Backlog priorizado |
| `0120_spec_master.md` | Consolidação do SPEC |
| `0190_spec_validation.md` | Gate de validação |

---

# GATE DE TRANSIÇÃO

O spec-engine só libera `build-engine` se:
- `0090_prd_validation.md` aprovado (PRD completo)
- `0190_spec_validation.md` aprovado (SPEC completo com score >= 80)

---

# REGRA FINAL

O spec-engine NÃO pode:
- Começar sem PRD aprovado
- Definir produto ou solução
- Avançar para BUILD sem SPEC validada
- Encerrar sem atualizar estado

O spec-engine DEVE:
- Manter foco em engenharia (COMO)
- Rastrear requisitos PRD → SPEC
- Manter consistência arquitetural
- Atualizar estado e log
