# 0034 — Backlog Operacional da Rodada Corretiva

## Objetivo

Transformar o backlog corretivo de `0033-backlog-corretivo-pos-auditoria.md` em plano operacional executavel, com:

- dono funcional
- estimativa inicial
- dependencias
- evidencias de encerramento

Este documento assume que a auditoria de referencia e `0032-relatorio-de-auditoria-do-programa-2026-04-17.md`.

---

## Andamento em 2026-04-17

### Itens fechados nesta rodada

- `OP-01`: autenticacao real e sessao confiavel no servidor
- `OP-02`: RBAC server-side com sessao persistida
- `OP-03`: persistencia administrativa e eventos administrativos duraveis
- `OP-09`: typecheck reproduzivel do frontend corrigido via ajuste de `tsconfig`

### Itens avancados nesta rodada

- `OP-04`: metricas e dashboard agora respeitam `workspace_id` do tenant ativo
- `OP-05`: runner de avaliacao deixou de forcar `threshold=0.0` e passou a medir `groundedness` mesmo sem judge
- `OP-06`: request correlation introduzido com `request_id` em logs centrais

### Evidencias desta rodada

- `pytest -q src/tests/test_sprint5.py -k 'metrics_route_scopes_results_to_active_workspace or metrics_filter_by_workspace or evaluation_uses_question_workspace_and_keeps_grounding_without_judge or test_metrics_returns_retrieval_answer_and_evaluation'`
- `python3 -m py_compile src/api/main.py src/models/schemas.py src/services/telemetry_service.py src/services/evaluation_service.py src/services/search_service.py src/services/request_context.py src/tests/test_sprint5.py`
- `pnpm -C frontend exec tsc --noEmit`
- `pnpm -C frontend lint`
- `pnpm -C frontend build`

---

## Convencoes

### Donos funcionais

- `Backend`: API, auth, RBAC, tenancy, persistencia
- `Frontend`: UI, fluxos de sessao, dashboard, experiencia enterprise
- `Platform`: observabilidade, pipeline, release, qualidade operacional
- `QA/Data`: testes de comportamento, dataset, avaliacao e calibracao

### Escala de estimativa

- `P`: pequeno, ate 2 dias uteis
- `M`: medio, de 3 a 5 dias uteis
- `G`: grande, de 1 a 2 semanas
- `GG`: muito grande, mais de 2 semanas ou com risco alto de descoberta

### Status inicial

Todos os itens abaixo comecam como:

- `status = aberto`
- `prioridade = conforme 0033`

---

## Trilho critico

O caminho critico desta rodada e:

1. autenticacao real
2. RBAC persistido
3. persistencia administrativa
4. isolamento multi-tenant provado
5. avaliacao honesta
6. observabilidade e release reproduzivel

Sem fechar os quatro primeiros itens, o gate da Fase 3 continua bloqueado.

---

## Backlog operacional

| ID | Item | Prioridade | Dono | Estimativa | Dependencias | Saida esperada |
|---|---|---|---|---|---|---|
| OP-01 | Autenticacao real e sessao confiavel | P0 | Backend | G | nenhuma | sessao autenticada resolvida no servidor |
| OP-02 | RBAC server-side com memberships persistidas | P0 | Backend | G | OP-01 | autorizacao centralizada e testada |
| OP-03 | Persistencia de tenants, usuarios e eventos administrativos | P0 | Backend | G | OP-01 | operacao administrativa duravel |
| OP-04 | Isolamento multi-tenant provado por teste | P0 | Backend + QA/Data | GG | OP-02, OP-03 | nao vazamento entre tenants |
| OP-05 | Avaliacao honesta e calibracao de confianca | P0 | QA/Data + Backend | G | OP-04 | metricas auditaveis sem vies otimista |
| OP-06 | Observabilidade F3 com request_id e metricas por tenant | P1 | Platform + Backend | G | OP-01, OP-02, OP-03 | trilha ponta a ponta observavel |
| OP-07 | Alertas e SLA operacional | P1 | Platform | G | OP-06 | sinais de saude e degradacao operaveis |
| OP-08 | Dashboard executivo enterprise | P1 | Frontend + Platform | M | OP-06, OP-07 | leitura executiva por tenant |
| OP-09 | Typecheck, smoke e pytest reproduziveis | P1 | Platform + QA/Data | M | nenhuma | trilha de validacao limpa |
| OP-10 | Branding e onboarding por tenant | P2 | Frontend + Backend | M | OP-03, OP-04 | onboarding enterprise mais completo |
| OP-11 | Workflow de aprovacao administrativa | P2 | Backend + Frontend | G | OP-03 | governanca operacional mais forte |
| OP-12 | Politicas de retencao e hardening de UX | P2 | Platform + Frontend | M | OP-06 | fechamento de acabamento operacional |

---

## Detalhamento por item

### OP-01 — Autenticacao real e sessao confiavel

**Escopo**

- substituir identidade inferida por cabecalho
- resolver sessao autenticada no servidor
- tratar expiracao, logout e sessao invalida

**Arquivos ou modulos provaveis**

- `src/api/main.py`
- `src/services/enterprise_service.py`
- camada de auth a ser introduzida ou consolidada

**Riscos**

- acoplamento atual entre sessao do frontend e cabecalhos de demonstracao
- necessidade de migrar chamadas existentes sem quebrar smoke

**Evidencia para encerrar**

- teste automatizado cobrindo spoofing de role e tenant
- endpoints centrais sem dependencia de `X-Enterprise-*`
- documentacao do contrato de sessao atualizada

### OP-02 — RBAC server-side com memberships persistidas

**Escopo**

- modelar memberships entre usuario e tenant
- aplicar role no backend de forma central
- bloquear rotas administrativas, auditoria e operacao conforme role

**Arquivos ou modulos provaveis**

- `src/api/main.py`
- services administrativos
- storage ou repositorio de identidade

**Riscos**

- risco de regra espalhada por endpoint
- risco de role continuar sendo um detalhe de frontend

**Evidencia para encerrar**

- matriz `admin/operator/viewer` coberta por teste
- rotas centrais retornando bloqueio consistente
- trilha de permissoes documentada

### OP-03 — Persistencia administrativa e eventos auditaveis

**Escopo**

- sair de store em memoria
- persistir tenants, usuarios e memberships
- criar eventos administrativos com ator e timestamp

**Arquivos ou modulos provaveis**

- `src/services/admin_service.py`
- camada de storage persistente
- endpoints de admin e auditoria

**Riscos**

- migracao de estado seedado para estado real
- risco de UI assumir mutacao imediata sem persistencia

**Evidencia para encerrar**

- restart nao perde tenants e usuarios
- acoes administrativas aparecem na trilha de auditoria
- consulta administrativa sobrevive a nova sessao

### OP-04 — Isolamento multi-tenant provado por teste

**Escopo**

- revisar acesso a documentos, busca, chat, auditoria e metricas
- garantir filtros server-side por tenant
- provar nao vazamento entre tenants

**Arquivos ou modulos provaveis**

- endpoints de documentos, search, chat, metrics e audit
- testes backend e smoke

**Riscos**

- vazamento silencioso em logs e dashboards
- isolamento parcial apenas em alguns endpoints

**Evidencia para encerrar**

- suite cobrindo 3 tenants ativos
- testes negativos de leitura cruzada
- dashboard e auditoria segmentados no backend

### OP-05 — Avaliacao honesta e calibracao de confianca

**Escopo**

- ampliar dataset alem de um unico documento
- remover configuracao permissiva do runner
- recalibrar `low_confidence`
- separar leitura heuristica de leitura com judge

**Arquivos ou modulos provaveis**

- `src/data/default/dataset.json`
- `src/services/evaluation_service.py`
- logs e relatorios de avaliacao

**Riscos**

- comparabilidade historica de metricas
- descoberta de regressao real quando a inflacao for removida

**Evidencia para encerrar**

- relatorio com cobertura maior de corpus
- metricas explicitas para retrieval, groundedness e confianca
- documentacao de interpretacao atualizada

### OP-06 — Observabilidade F3 com request_id e metricas por tenant

**Escopo**

- adicionar `request_id` nos fluxos centrais
- padronizar campos estruturados de log
- emitir metricas por tenant
- permitir correlacao entre request, query e resposta

**Arquivos ou modulos provaveis**

- `src/services/telemetry_service.py`
- middleware ou camada transversal de request
- endpoints de metricas

**Riscos**

- alta dispersao de logging pelo codigo
- custo de retrofit nos fluxos centrais

**Evidencia para encerrar**

- query rastreavel do request ao resultado final
- dashboard com filtro por tenant
- logs estruturados com campos minimos definidos

### OP-07 — Alertas e SLA operacional

**Escopo**

- definir SLI e SLO
- medir `uptime`, `p99_latency` e `error_rate`
- criar alertas minimos

**Arquivos ou modulos provaveis**

- docs de observabilidade
- scripts ou jobs de agregacao
- painel de metricas

**Riscos**

- metricas incompletas antes de OP-06
- alerta demais ou alerta de menos

**Evidencia para encerrar**

- politica minima de monitoramento documentada
- alertas testados em condicao controlada
- janela de medicao publicada

### OP-08 — Dashboard executivo enterprise

**Escopo**

- transformar o dashboard em visao de negocio e operacao
- destacar saude, risco, uso e qualidade por tenant

**Arquivos ou modulos provaveis**

- `frontend/app/dashboard/page.tsx`
- contratos de metricas

**Riscos**

- frontend depender de metricas ainda imaturas
- excesso de detalhe tecnico para usuario nao tecnico

**Evidencia para encerrar**

- dashboard legivel por admin e operador
- KPIs principais disponiveis sem navegar por Swagger
- estados de erro e vazio tratados

### OP-09 — Trilho de validacao reproduzivel

**Escopo**

- estabilizar `tsc --noEmit`
- parametrizar ou flexibilizar portas do smoke
- garantir encerramento conclusivo de `pytest`

**Arquivos ou modulos provaveis**

- `frontend/tsconfig.json`
- `frontend/playwright.config.ts`
- configuracao de testes backend

**Riscos**

- dependencia de artefatos gerados
- flakiness por ambiente local

**Evidencia para encerrar**

- `lint`, `build`, `typecheck`, `smoke` e `pytest` verdes em sequencia
- passos de validacao documentados

### OP-10 — Branding e onboarding por tenant

**Escopo**

- suportar configuracoes visuais por tenant
- formalizar onboarding minimo

**Dependencia real**

- so faz sentido depois de persistencia e tenancy fortes

**Evidencia para encerrar**

- tenant novo nasce configuravel
- onboarding nao depende de seed manual

### OP-11 — Workflow de aprovacao administrativa

**Escopo**

- criar aprovacao para mudancas administrativas criticas
- registrar aprovador, acao e justificativa

**Dependencia real**

- exige trilha administrativa persistida

**Evidencia para encerrar**

- existe fluxo de aprovacao consultavel
- eventos administrativos passam a ter contexto de aprovacao

### OP-12 — Politicas de retencao e hardening de UX

**Escopo**

- formalizar retencao de logs
- revisar UX de erro, vazio e loading
- revisar usabilidade tablet e mobile

**Dependencia real**

- fecha a rodada, mas nao destrava o gate sozinho

**Evidencia para encerrar**

- docs de operacao atualizadas
- UX enterprise mais consistente nas rotas centrais

---

## Plano de alocacao recomendado

### Trilha Backend

- OP-01
- OP-02
- OP-03
- OP-04

### Trilha Platform

- OP-06
- OP-07
- OP-09

### Trilha Frontend

- OP-08
- OP-10
- parte de OP-11
- parte de OP-12

### Trilha QA/Data

- OP-04
- OP-05
- OP-09

---

## Sequencia recomendada de execucao

### Semana 1

- OP-01
- preparacao de base para OP-02 e OP-03

### Semana 2

- OP-02
- OP-03

### Semana 3

- OP-04
- inicio de OP-06

### Semana 4

- OP-05
- OP-06
- OP-09

### Semana 5

- OP-07
- OP-08

### Semana 6

- OP-10
- OP-11
- OP-12
- reauditoria do gate

---

## Definicao de pronto da rodada

A rodada corretiva so pode ser considerada pronta quando:

1. auth e RBAC estiverem resolvidos no servidor
2. tenants, usuarios e eventos administrativos estiverem persistidos
3. nao houver vazamento entre tenants nos fluxos centrais
4. a avaliacao nao estiver inflada por configuracao permissiva
5. observabilidade e alertas estiverem operaveis
6. a trilha de validacao estiver verde de forma reproduzivel

---

## Meta executiva

Meta desta rodada:

- remover o bloqueio do gate da Fase 3
- elevar a nota geral para `>= 80`
- permitir uma nova auditoria com chance real de aprovacao
