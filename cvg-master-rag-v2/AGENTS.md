# AGENTS.md — CVG RAG Enterprise Premium

**Versão:** 1.0
**Data:** 2026-04-19
**Status:** Canônico
**Objetivo:** Constituição operacional do repositório para o Codex

---

## 1. TÍTULO E PROPÓSITO

Este repositório implementa o **RAG Enterprise Premium** utilizando o sistema de engenharia **CVG (Codex Visual Governance)** — uma metodologia enterprise de engenharia orientada por documentação, gates e execução controlada.

O Codex **NÃO** atua como gerador solto de código. O Codex atua como **operador de um sistema de engenharia controlado**, seguindo o pipeline CVG e utilizando as skills da pasta `.agents/skills`.

---

## 2. WORKING AGREEMENTS / REPOSITORY EXPECTATIONS

O Codex **DEVE**:
- Ler este `AGENTS.md` antes de qualquer ação
- Respeitar a estrutura do repositório (`/docs/00_discovery/`, `/docs/01_prd/`, `/docs/02_spec/`, `/docs/03_build/`, `/docs/04_audit/`)
- Seguir o pipeline CVG (`DISCOVERY → PRD → SPEC → BUILD → AUDIT`)
- Não improvisar soluções fora do processo
- Manter documentação viva e consistente
- Respeitar gates entre fases
- Sempre atualizar `/docs/99_runtime_state.md` e `/docs/20_master_execution_log.md`

O Codex **NÃO PODE**:
- Começar codificação sem processo definido
- Criar funcionalidades fora do escopo do PRD/SPEC
- Ignorar bloqueios ou dependências
- Encerrar sem atualizar estado e registrar próximo passo

---

## 3. PIPELINE OFICIAL DO REPOSITÓRIO

```
DISCOVERY → PRD → SPEC → BUILD → AUDIT
```

| Etapa | Função | Gate |
|---|---|---|
| **DISCOVERY** | Define o **problema** — investigação e análise | `0090_discovery_validation.md` |
| **PRD** | Define o **produto** — o quê será construído | `0090_prd_validation.md` |
| **SPEC** | Define a **engenharia** — como será construído | `0190_spec_validation.md` |
| **BUILD** | Executa a construção faseada | `0390_build_gate.md` |
| **AUDIT** | Valida a realidade — o que foi construído está correto? | `0490_audit_report.md` |

---

## 4. REGRAS DE TRANSIÇÃO ENTRE ETAPAS

| Transição | Condição |
|---|---|
| DISCOVERY → PRD | `0090_discovery_validation.md` aprovado |
| PRD → SPEC | `0090_prd_validation.md` aprovado |
| SPEC → BUILD | `0190_spec_validation.md` aprovado |
| BUILD → AUDIT | Sistema funcional em dev/staging/prod |

**PROIBIDO:**
- Iniciar PRD sem discovery aprovado
- Iniciar SPEC sem PRD aprovado
- Iniciar BUILD sem SPEC aprovada
- Iniciar AUDIT antes de sistema funcional

---

## 5. REGRAS DE USO DAS SKILLS

Este repositório utiliza skills especializadas em `.agents/skills/`. O Codex **DEVE** preferir essas skills quando a tarefa corresponder ao escopo delas.

| Skill | Quando Usar | Quando NÃO Usar |
|---|---|---|
| `discovery-engine` | Problema/oportunidade mal definida | Problema já descoberto/definido |
| `prd-engine` | Discovery aprovado, produto a definir | Discovery incompleto |
| `spec-engine` | PRD aprovado, engenharia a definir | PRD incompleto |
| `build-engine` | SPEC aprovada, construção a executar | SPEC incompleta |
| `audit-engine` | Sistema funcional, validação necessária | Sistema não existe ainda |
| `runtime-controller` | Após qualquer etapa, para continuidade | Não é skill principal |

---

## 6. REGRAS DE ESTADO E CONTINUIDADE

O Codex **SEMPRE** deve ler e atualizar:

| Arquivo | Função |
|---|---|
| `/docs/99_runtime_state.md` | Estado atual do sistema |
| `/docs/20_master_execution_log.md` | Log de todas as execuções |
| `/docs/30_backlog_master.md` | Backlog priorizado (quando aplicável) |

**PROIBIDO encerrar apenas com resumo narrativo.**

Antes de encerrar qualquer rodada, o Codex **DEVE**:
1. Atualizar estado em `/docs/99_runtime_state.md`
2. Registrar `last_completed_action`
3. Registrar `next_action`
4. Definir `status`
5. Adicionar entry no log

---

## 7. ESTADOS OFICIAIS

| Estado | Significado | Quando Usar |
|---|---|---|
| `IN_PROGRESS` | Execução ativa em curso | Durante execução de uma etapa |
| `READY_FOR_NEXT_STEP` | Etapa concluída, próximo passo disponível | Sprint/task concluído |
| `BLOCKED` | Execução impedida por bloqueio | Falta de informação, dependência, erro |
| `WAITING_HUMAN_APPROVAL` | Aguardando decisão humana | Decisão de negócio, escopo, risco |
| `COMPLETED` | Execução finalizada corretamente | Etapa/engine completo |

---

## 8. REGRAS DE BLOQUEIO

O Codex **DEVE** marcar `BLOCKED` quando:
- Falta informação crítica
- Conflito entre documentos
- Dependência ausente
- Erro não recuperável
- Gate não aprovado

Ao bloquear, **DEVE** registrar:
- `blockers`: causa raiz do bloqueio
- `next_action`: como o bloqueio pode ser resolvido
- `status`: BLOCKED
- `human_decision_required`: yes/no conforme necessário

---

## 9. REGRAS DE APROVAÇÃO HUMANA

O Codex **DEVE** marcar `WAITING_HUMAN_APPROVAL` quando:
- Decisão de negócio necessária
- Alteração de escopo
- Conflito entre PRD e SPEC
- Risco crítico
- Ação irreversível

**PROIBIDO:**
- Tomar decisão silenciosa
- Assumir regra de negócio
- Alterar escopo sem aprovação

---

## 10. REGRAS DE BUILD

O BUILD **SEMPRE** deve começar por:
- `0300_build_engineer_master.md` — planejamento estratégico
- `0301_roadmap.md` — phases e timeline
- `0302_BACKLOG_MASTER.md` — backlog priorizado

O BUILD segue o padrão:
```
PHASE → SPRINT → TASK
```

Cada **task** deve conter:
- **O QUE** — descrição objetiva
- **ONDE** — arquivo/módulo/camada
- **COMO** — abordagem baseada na SPEC
- **DEPENDÊNCIA** — pré-requisitos
- **CRITÉRIO DE PRONTO** — o que precisa existir

Cada **phase** deve conter:
- Entregas realizadas
- GAPs de construção
- Riscos identificados
- Ajustes necessários
- Próxima phase planejada

---

## 11. REGRAS DE AUDIT

O AUDIT **SEMPRE** deve produzir:
- Análise de aderência ao PRD
- Análise de aderência à SPEC
- Runtime analysis
- Logs audit
- Metrics audit
- Integrations audit
- Data integrity audit
- Security governance audit
- Operational experience audit
- GAP analysis
- Remediation plan
- Audit report

---

## 12. REGRAS DE QUALIDADE

O Codex **DEVE**:
- Preferir mudanças pequenas e coerentes
- Preservar arquitetura definida na SPEC
- Evitar acoplamento indevido
- Manter rastreabilidade ( PRD → SPEC → BUILD)
- Não criar arquivos desnecessários
- Não quebrar convenções do repositório
- Documentar mudanças relevantes em `/docs`

---

## 13. DEFINIÇÃO DE PRONTO

Uma tarefa só é considerada **pronta** quando:
- Atende à etapa correta do pipeline
- Respeita os gates
- Atualiza estado e log
- Entrega os artefatos esperados
- Não deixa ambiguidade escondida
- Registra próximo passo

---

## 14. ANTI-PATTERNS (PROIBIDO)

O Codex está **PROIBIDO** de:
- ❌ Começar código sem Discovery/PRD/SPEC quando aplicável
- ❌ Inventar produto durante SPEC
- ❌ Build sem roadmap/backlog
- ❌ Encerrar sem atualizar estado
- ❌ Ignorar bloqueios
- ❌ Ignorar backlog
- ❌ Ignorar skills já existentes
- ❌ Resumir sem persistir
- ❌ Fazer decisões de negócio silenciosas
- ❌ Mascarar problema crítico
- ❌ Avançar com erro conhecido

---

## 15. CONCLUSÃO OPERACIONAL

> **Este repositório não usa o Codex como gerador solto de código.**
> **Este repositório usa o Codex como operador de um sistema de engenharia controlado.**

O Codex deve atuar como:
- **Operador disciplinado** — segue o processo CVG
- **Guardião do estado** — mantém continuidade operacional
- **Auditor de si mesmo** — valida antes de avançar
- **Documentador contínuo** — mantém artefatos atualizados

---

## 16. ESTRUTURA DE DIRETÓRIOS

```
/docs
├── 00_discovery/       # Discovery completo
├── 01_prd/           # PRD completo
├── 02_spec/          # SPEC completa
├── 03_build/         # BUILD documentation + sprints
├── 04_audit/         # AUDIT documentation
├── 99_runtime_state.md
├── 20_master_execution_log.md
└── 30_backlog_master.md

/.agents/skills/
├── discovery-engine/
├── prd-engine/
├── spec-engine/
├── build-engine/
├── audit-engine/
└── runtime-controller/
```

---

## 17. REGRA DE OURO

> **Agente sem estado é agente imprevisível.**
> **Agente com estado é sistema controlado.**

O Codex **SEMPRE** deve manter estado explícito e atualizado. O estado é a memória do sistema. Sem estado, não há continuidade. Sem continuidade, não há controle.

---

**FIM DO DOCUMENTO**
