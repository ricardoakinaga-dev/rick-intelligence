# 0037 — Roadmap Executivo e Matriz de Importacao (Atualizado 2026-04-17)

## Objetivo

Fechar a trilha documental da rodada corretiva com dois formatos de gestao:

- um roadmap executivo de 1 pagina
- uma matriz compacta pronta para importacao ou cadastro em Jira e GitHub Issues

Este documento deriva de:

- `0038-relatorio-de-auditoria-tecnica-2026-04-17.md`
- `0033-backlog-corretivo-pos-auditoria.md` (atualizado)
- `0015-roadmap-executivo.md` (atualizado)
- `0016-backlog-priorizado.md` (atualizado)

---

## Estado Atual (Auditoria 2026-04-17)

**Nota geral: 87/100**

| Fase | Nota | Status |
|---|---|---|
| F0 — Foundation | 95/100 | ✅ Funcional |
| F1 — Profissional | 72/100 | ⚠️ Parcial |
| F2 — Premium | 82/100 | ⚠️ Frontend OK, features pendentes |
| F3 — Enterprise | 60/100 | ❌ Bloqueado por dataset e auth |

**Blocker numero 1: dataset real nao existe.**

---

## Roadmap Executivo

### Meta da rodada

- nota geral: `>= 92/100`
- blocker de dataset removido
- auth real implementado
- isolamento multi-tenant provado
- reauditoria formal com chance real de aprovacao

### Sequencia executiva

#### Onda 0 — Dataset Real (PRIORIDADE ABSOLUTA)

- criar 20+ perguntas reais
- validar schema Pydantic
- executar baseline hit_rate >= 60%
- cobrir multiplos documentos

**Resultado esperado**

- gates se tornam verificaveis pela primeira vez

#### Onda 1 — Seguranca e identidade

- autenticacao real no servidor
- RBAC persistido
- fim da confianca em cabecalhos do cliente

**Resultado esperado**

- risco principal do programa removido

#### Onda 2 — Governanca e persistencia

- persistir tenants, usuarios e memberships
- registrar eventos administrativos auditaveis
- adaptar a UI administrativa para persistencia real

**Resultado esperado**

- operacao enterprise deixa de ser demonstracao

#### Onda 3 — Isolamento multi-tenant

- blindar documentos, busca, chat, auditoria e metricas
- provar nao-vazamento com 3 tenants ativos

**Resultado esperado**

- tenant vira limite real de dados e operacao

#### Onda 4 — Qualidade honesta

- avaliar com dataset real
- remover inflation do runner
- recalibrar `low_confidence`

**Resultado esperado**

- metricas passam a refletir qualidade observada de verdade

#### Onda 5 — Operacao enterprise

- `request_id` ponta a ponta
- metricas por tenant
- alertas, SLA e dashboard executivo

**Resultado esperado**

- plataforma operavel como produto enterprise

#### Onda 6 — Release e reauditoria

- typecheck reproduzivel
- smoke estavel
- `pytest` conclusivo
- reauditoria do gate

**Resultado esperado**

- evidencia suficiente para nova decisao formal de go/no-go

---

## Marco de Decisao

### Marco 0 (Onda 0)

Depois do dataset:
- gates sao verificaveis
- baseline documentado

**Pergunta executiva**
- temos evidencia real de qualidade pela primeira vez?

### Marco 1 (Onda 2)

Depois de auth e persistencia:
- auth e RBAC resolvidos
- persistencia administrativa ativa

**Pergunta executiva**
- o risco principal foi removido?

### Marco 2 (Onda 3)

Depois de isolamento:
- isolamento multi-tenant provado

**Pergunta executiva**
- o produto ja pode ser chamado de enterprise seguro por arquitetura?

### Marco 3 (Onda 5)

Depois de operacao:
- operacao observavel
- dashboard executivo
- sinais de SLA definidos

**Pergunta executiva**
- a plataforma ja e operavel com governanca suficiente?

### Marco 4 (Onda 6)

Depois de release e reauditoria:
- qualidade reproduzivel
- reauditoria fechada

**Pergunta executiva**
- o gate da Fase 3 pode ser aprovado?

---

## Matriz Compacta de Importacao

### Colunas recomendadas

- `Key`
- `Title`
- `Priority`
- `Sprint`
- `Owner`
- `Depends On`
- `Labels`
- `Outcome`

### Tabela

| Key | Title | Priority | Sprint | Owner | Depends On | Labels | Outcome |
|---|---|---|---|---|---|---|---|
| TKT-000 | Criar dataset real de 20+ perguntas com multiplos documentos | P0 | H0 | QA/Data | - | `data,dataset,evaluation,p0` | dataset real e verificavel |
| TKT-001 | Substituir autenticacao baseada em cabecalho por sessao resolvida no servidor | P0 | H1 | Backend | - | `security,auth,backend,p0` | sessao autenticada resolvida no servidor |
| TKT-002 | Migrar frontend para consumir sessao autenticada real | P0 | H1 | Frontend | TKT-001 | `frontend,auth,session,p0` | login e shell alinhados com sessao real |
| TKT-003 | Persistir usuarios, tenants e memberships | P0 | H2 | Backend | TKT-001 | `backend,persistence,tenancy,p0` | estado administrativo duravel |
| TKT-004 | Aplicar RBAC server-side nas rotas centrais | P0 | H2 | Backend | TKT-001,TKT-003 | `security,rbac,backend,p0` | autorizacao centralizada e testada |
| TKT-005 | Registrar eventos administrativos auditaveis | P0 | H2 | Backend | TKT-003,TKT-004 | `audit,backend,governance,p0` | trilha administrativa consultavel |
| TKT-006 | Adaptar o painel administrativo para persistencia real | P0 | H2 | Frontend | TKT-003,TKT-005 | `frontend,admin,persistence,p0` | CRUD administrativo consistente |
| TKT-007 | Garantir isolamento de tenant em documentos e ingestao | P0 | H3 | Backend | TKT-003,TKT-004 | `tenancy,ingestion,backend,p0` | documentos isolados por tenant |
| TKT-008 | Garantir isolamento de tenant em busca, chat e grounding | P0 | H3 | Backend | TKT-003,TKT-004 | `tenancy,retrieval,chat,backend,p0` | retrieval sem vazamento |
| TKT-009 | Garantir isolamento de tenant em auditoria e metricas | P0 | H3 | Backend+Platform | TKT-003,TKT-004 | `tenancy,metrics,audit,p0` | auditoria e metricas segmentadas |
| TKT-010 | Criar suite de nao-vazamento com 3 tenants ativos | P0 | H3 | QA/Data | TKT-007,TKT-008,TKT-009 | `qa,tenancy,tests,p0` | prova automatizada de isolamento |
| TKT-011 | Ampliar dataset de avaliacao para multiplos documentos | P0 | H4 | QA/Data | TKT-000,TKT-010 | `data,evaluation,dataset,p0` | dataset mais representativo |
| TKT-012 | Corrigir runner de avaliacao para nao inflar metricas | P0 | H4 | Backend+QA/Data | TKT-011 | `evaluation,backend,metrics,p0` | runner honesto |
| TKT-013 | Recalibrar o sinal de `low_confidence` | P0 | H4 | Backend | TKT-012 | `quality,confidence,backend,p0` | menos falso positivo de baixa confianca |
| TKT-014 | Introduzir `request_id` ponta a ponta | P1 | H5 | Platform+Backend | TKT-001,TKT-004 | `platform,observability,backend,p1` | correlacao ponta a ponta |
| TKT-015 | Estruturar logs e metricas por tenant | P1 | H5 | Platform+Backend | TKT-014,TKT-009 | `observability,metrics,tenancy,p1` | telemetria enterprise utilizavel |
| TKT-016 | Definir SLI, SLO e alertas minimos | P1 | H5 | Platform | TKT-015 | `sre,alerts,sla,p1` | sinais operacionais explicitos |
| TKT-017 | Evoluir dashboard para leitura executiva enterprise | P1 | H5 | Frontend+Platform | TKT-015,TKT-016 | `dashboard,frontend,executive,p1` | painel executivo por tenant |
| TKT-018 | Tornar typecheck do frontend reproduzivel | P1 | H6 | Platform+Frontend | - | `quality,frontend,tooling,p1` | `tsc --noEmit` previsivel |
| TKT-019 | Parametrizar smoke test e reduzir dependencia de portas fixas | P1 | H6 | QA/Data+Frontend | - | `qa,smoke,frontend,p1` | smoke mais estavel |
| TKT-020 | Fazer a suite `pytest` encerrar com evidencia conclusiva | P1 | H6 | QA/Data+Backend | - | `qa,backend,pytest,p1` | suite backend conclusiva |
| TKT-021 | Rodar reauditoria formal do gate da Fase 3 | P1 | H6 | Platform+QA/Data | TKT-018,TKT-019,TKT-020 | `audit,gate,phase3,p1` | nova decisao formal de gate |
| TKT-022 | Implementar branding e onboarding por tenant | P2 | Pos-H6 | Frontend+Backend | TKT-003,TKT-010 | `ux,branding,tenant,p2` | onboarding enterprise mais completo |
| TKT-023 | Criar workflow de aprovacao administrativa | P2 | Pos-H6 | Backend+Frontend | TKT-005 | `governance,approval,admin,p2` | governanca administrativa forte |
| TKT-024 | Formalizar retencao e hardening de UX enterprise | P2 | Pos-H6 | Platform+Frontend | TKT-015 | `operations,retention,ux,p2` | operacao e UX mais maduras |
| TKT-025 | Implementar Reranking (Cohere) ou documentar justificativa | P2 | Pos-H6 | Backend | TKT-000 | `retrieval,rerank,p2` | reranking implementado ou justificativa documentada |
| TKT-026 | Implementar HyDE ou remover do roadmap | P2 | Pos-H6 | Backend | TKT-000 | `retrieval,hyde,p2` | HyDE implementado ou removido do roadmap |
| TKT-027 | Implementar semantic chunking ou documentar justificativa | P2 | Pos-H6 | Backend | TKT-000 | `chunking,semantic,p2` | semantic chunking implementado ou justificativa documentada |

---

## Sequencia de Execucao Otimizada

1. **TKT-000** — dataset real (PRIORIDADE ABSOLUTA, antes de qualquer gate)
2. TKT-001, TKT-002 — auth
3. TKT-003, TKT-004, TKT-005, TKT-006 — persistencia
4. TKT-007, TKT-008, TKT-009, TKT-010 — isolamento
5. TKT-011, TKT-012, TKT-013 — avaliacao honesta
6. TKT-014, TKT-015, TKT-016, TKT-017 — observabilidade
7. TKT-018, TKT-019, TKT-020 — qualidade
8. TKT-021 — reauditoria
9. TKT-022 a TKT-027 — acabamento

---

## Leitura Executiva Final

Se houver pouco tempo ou capacidade reduzida, a ordem minima que maximiza impacto e:

1. **TKT-000** — dataset (blocker de todos os gates)
2. TKT-001
3. TKT-003
4. TKT-004
5. TKT-007
6. TKT-008
7. TKT-010
8. TKT-012
9. TKT-014
10. TKT-021

Esta sequencia fecha: dataset real, auth real, isolamento provado e reauditoria.

---

## Diferenca da Versao Anterior

Esta versao foi atualizada com:

1. **TKT-000** adicionado como primeiro ticket (dataset real) — nunca existiu antes como item de backlog
2. Onda 0 dedicada exclusivamente ao dataset
3. Notas atualizadas conforme auditoria 0038 (87/100 geral)
4. TKT-025, TKT-026, TKT-027 adicionados para features pendentes (reranking, HyDE, semantic chunking)
5. Marco 0 adicionado antes do Marco 1 (dataset vem antes de auth)
6. Meta atualizada para 92/100 (era 80 na versao anterior)
