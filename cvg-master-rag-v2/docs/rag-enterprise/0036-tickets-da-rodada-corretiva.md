# 0036 — Tickets da Rodada Corretiva

## Objetivo

Converter o plano de execucao em tickets prontos para uso em Jira, GitHub Issues ou qualquer gestor de trabalho equivalente.

Este documento deriva de:

- `0032-relatorio-de-auditoria-do-programa-2026-04-17.md`
- `0033-backlog-corretivo-pos-auditoria.md`
- `0034-backlog-operacional-da-rodada-corretiva.md`
- `0035-plano-de-execucao-por-sprint-e-issues.md`

---

## Convencao de uso

Cada ticket abaixo ja contem:

- titulo sugerido
- prioridade
- sprint recomendada
- dono funcional
- dependencias
- descricao curta
- checklist tecnico
- criterio de aceite

Padrao recomendado de status:

- `todo`
- `in_progress`
- `blocked`
- `review`
- `done`

---

## Tickets P0

### TKT-001 — Substituir autenticacao baseada em cabecalho por sessao resolvida no servidor

**Prioridade**

- P0

**Sprint**

- H1

**Dono funcional**

- Backend

**Dependencias**

- nenhuma

**Descricao**

O backend hoje infere identidade e contexto enterprise a partir de cabecalhos do cliente. Este ticket substitui esse modelo por autenticacao real, com sessao resolvida no servidor e usada como fonte de verdade para role e tenant.

**Checklist tecnico**

- introduzir ou consolidar camada de autenticacao real
- remover `X-Enterprise-*` como fonte primaria de identidade
- fazer `GET /session` refletir sessao autenticada do servidor
- tratar expiracao, logout e sessao invalida
- atualizar contrato de auth e sessao na documentacao

**Modulos provaveis**

- `src/api/main.py`
- `src/services/enterprise_service.py`
- `src/models/schemas.py`

**Criterio de aceite**

- nenhum endpoint central depende de cabecalho do cliente para identidade principal
- a sessao ativa e resolvida no servidor
- existe teste cobrindo role forjada e tenant forjado

### TKT-002 — Migrar frontend para consumir sessao autenticada real

**Prioridade**

- P0

**Sprint**

- H1

**Dono funcional**

- Frontend

**Dependencias**

- TKT-001

**Descricao**

O frontend deve deixar de operar como se o estado de sessao fosse local ou derivado de convencao de demonstracao e passar a depender do contrato real de sessao.

**Checklist tecnico**

- revisar bootstrap de sessao
- consumir sessao real no provider enterprise
- tratar loading, expiracao e falha de sessao
- revisar login, logout, forbidden e recovery

**Modulos provaveis**

- `frontend/components/layout/enterprise-session-provider.tsx`
- `frontend/components/layout/app-shell.tsx`
- `frontend/app/login/page.tsx`
- `frontend/app/forbidden/page.tsx`
- `frontend/app/recover-access/page.tsx`

**Criterio de aceite**

- login e logout funcionam com sessao autenticada de verdade
- shell nao entra em estado incoerente quando a sessao expira

### TKT-003 — Persistir usuarios, tenants e memberships

**Prioridade**

- P0

**Sprint**

- H2

**Dono funcional**

- Backend

**Dependencias**

- TKT-001

**Descricao**

Substituir o modelo administrativo em memoria por um modelo persistido e reaproveitavel entre sessoes e reinicios.

**Checklist tecnico**

- definir modelo persistido de usuario
- definir modelo persistido de tenant
- definir memberships com role
- adaptar servicos administrativos para leitura e escrita duraveis
- garantir compatibilidade minima com a UI existente

**Modulos provaveis**

- `src/services/admin_service.py`
- `src/services/enterprise_service.py`
- `src/models/schemas.py`

**Criterio de aceite**

- restart nao perde tenants, usuarios ou memberships
- nova sessao continua refletindo o estado administrativo anterior

### TKT-004 — Aplicar RBAC server-side nas rotas centrais

**Prioridade**

- P0

**Sprint**

- H2

**Dono funcional**

- Backend

**Dependencias**

- TKT-001
- TKT-003

**Descricao**

Padronizar autorizacao por role no backend e impedir que o frontend seja a principal barreira de acesso.

**Checklist tecnico**

- centralizar verificacao de role
- proteger endpoints de admin, auditoria, metricas e operacao sensivel
- diferenciar comportamento de `admin`, `operator` e `viewer`
- padronizar resposta de acesso negado

**Modulos provaveis**

- `src/api/main.py`
- `src/services/enterprise_service.py`

**Criterio de aceite**

- a role aplicada no backend muda de fato o comportamento dos endpoints
- ha testes cobrindo matriz minima de permissoes

### TKT-005 — Registrar eventos administrativos auditaveis

**Prioridade**

- P0

**Sprint**

- H2

**Dono funcional**

- Backend

**Dependencias**

- TKT-003
- TKT-004

**Descricao**

Cada acao administrativa relevante deve gerar trilha confiavel de auditoria, com ator, acao, alvo, tenant e timestamp.

**Checklist tecnico**

- registrar eventos de criacao, edicao e remocao
- incluir request id quando disponivel
- expor leitura desses eventos para auditoria administrativa
- garantir coerencia entre evento e acao concluida

**Modulos provaveis**

- `src/services/admin_service.py`
- `src/services/telemetry_service.py`
- `src/api/main.py`

**Criterio de aceite**

- criar tenant, alterar usuario e remover membership geram evento consultavel

### TKT-006 — Adaptar o painel administrativo para persistencia real

**Prioridade**

- P0

**Sprint**

- H2

**Dono funcional**

- Frontend

**Dependencias**

- TKT-003
- TKT-005

**Descricao**

Atualizar a UI administrativa para refletir comportamento real de persistencia, erro e reload.

**Checklist tecnico**

- revisar fluxo de CRUD do admin
- tratar loading e falha reais
- remover pressupostos de mutacao instantanea em memoria
- validar consistencia apos refresh

**Modulos provaveis**

- `frontend/app/admin/page.tsx`

**Criterio de aceite**

- CRUD administrativo sobrevive a refresh e nova sessao

### TKT-007 — Garantir isolamento de tenant em documentos e ingestao

**Prioridade**

- P0

**Sprint**

- H3

**Dono funcional**

- Backend

**Dependencias**

- TKT-003
- TKT-004

**Descricao**

Revisar toda a trilha de upload, listagem e vinculacao de documentos para garantir isolamento estrito por tenant.

**Checklist tecnico**

- revisar upload e listagem de documentos
- validar associacao de workspace e tenant
- bloquear escrita ou leitura cruzada

**Modulos provaveis**

- `src/services/ingestion_service.py`
- `src/api/main.py`

**Criterio de aceite**

- tenant nao acessa nem altera documentos fora do proprio escopo

### TKT-008 — Garantir isolamento de tenant em busca, chat e grounding

**Prioridade**

- P0

**Sprint**

- H3

**Dono funcional**

- Backend

**Dependencias**

- TKT-003
- TKT-004

**Descricao**

Revisar retrieval, chat e grounding para garantir que consultas nunca recuperem dados de outro tenant.

**Checklist tecnico**

- revisar filtros por tenant na busca
- revisar lookup de chunks e citacoes
- revisar caches, indices e adaptadores de vetor

**Modulos provaveis**

- `src/services/search_service.py`
- `src/services/grounding_service.py`
- `src/services/vector_service.py`
- `src/api/main.py`

**Criterio de aceite**

- query de tenant A nao retorna conteudo de tenant B

### TKT-009 — Garantir isolamento de tenant em auditoria e metricas

**Prioridade**

- P0

**Sprint**

- H3

**Dono funcional**

- Backend + Platform

**Dependencias**

- TKT-003
- TKT-004

**Descricao**

Revisar logs, auditoria e agregacoes para garantir que as visoes operacionais respeitam o tenant no servidor.

**Checklist tecnico**

- segmentar logs por tenant
- segmentar leitura de auditoria
- segmentar agregacao e leitura de metricas

**Modulos provaveis**

- `src/services/telemetry_service.py`
- `src/api/main.py`

**Criterio de aceite**

- auditoria e metricas nao vazam entre tenants

### TKT-010 — Criar suite de nao-vazamento com 3 tenants ativos

**Prioridade**

- P0

**Sprint**

- H3

**Dono funcional**

- QA/Data

**Dependencias**

- TKT-007
- TKT-008
- TKT-009

**Descricao**

Criar cobertura automatizada para provar que tres tenants conseguem operar simultaneamente sem vazamento.

**Checklist tecnico**

- criar casos negativos de leitura cruzada
- cobrir documentos, busca e auditoria
- incluir pelo menos um fluxo UI critico

**Modulos provaveis**

- `src/tests/conftest.py`
- `src/tests/test_sprint5.py`
- `frontend/tests/phase2-gate.spec.ts`

**Criterio de aceite**

- suite prova isolamento em backend e UI minima

### TKT-011 — Ampliar dataset de avaliacao para multiplos documentos

**Prioridade**

- P0

**Sprint**

- H4

**Dono funcional**

- QA/Data

**Dependencias**

- TKT-010

**Descricao**

O dataset atual e estreito demais. Este ticket amplia a base de avaliacao para cobrir mais documentos, categorias e contextos.

**Checklist tecnico**

- incluir multiplos documentos
- balancear categorias e dificuldade
- revisar metadados do dataset

**Modulos provaveis**

- `src/data/default/dataset.json`

**Criterio de aceite**

- o dataset deixa de depender de um unico documento

### TKT-012 — Corrigir runner de avaliacao para nao inflar metricas

**Prioridade**

- P0

**Sprint**

- H4

**Dono funcional**

- Backend + QA/Data

**Dependencias**

- TKT-011

**Descricao**

Remover vies permissivo na trilha de avaliacao e separar melhor as metricas observadas, heuristicias e metricas com judge.

**Checklist tecnico**

- revisar `threshold=0.0`
- separar metricas com e sem judge
- revisar computo de groundedness
- atualizar interpretacao das metricas

**Modulos provaveis**

- `src/services/evaluation_service.py`

**Criterio de aceite**

- relatorio de avaliacao nao mascara falhas reais

### TKT-013 — Recalibrar o sinal de `low_confidence`

**Prioridade**

- P0

**Sprint**

- H4

**Dono funcional**

- Backend

**Dependencias**

- TKT-012

**Descricao**

Reduzir falso positivo de baixa confianca em respostas que ja possuem grounding e citacoes satisfatorias.

**Checklist tecnico**

- revisar thresholds e regra de classificacao
- comparar com exemplos reais de log
- validar resultado em amostra representativa

**Modulos provaveis**

- `src/services/search_service.py`
- `src/services/grounding_service.py`
- `src/services/evaluation_service.py`
- `src/logs/queries.jsonl`

**Criterio de aceite**

- respostas boas deixam de cair em `low_confidence` sem justificativa clara

---

## Tickets P1

### TKT-014 — Introduzir `request_id` ponta a ponta

**Prioridade**

- P1

**Sprint**

- H5

**Dono funcional**

- Platform + Backend

**Dependencias**

- TKT-001
- TKT-004

**Descricao**

Adicionar correlacao ponta a ponta para requests, logs e eventos centrais.

**Checklist tecnico**

- gerar ou propagar `request_id`
- anexar a logs de query, ingestao e avaliacao
- devolver em respostas quando fizer sentido

**Modulos provaveis**

- `src/api/main.py`
- `src/services/telemetry_service.py`

**Criterio de aceite**

- uma query pode ser seguida do request ao log final

### TKT-015 — Estruturar logs e metricas por tenant

**Prioridade**

- P1

**Sprint**

- H5

**Dono funcional**

- Platform + Backend

**Dependencias**

- TKT-014
- TKT-009

**Descricao**

Padronizar telemetria para suportar operacao enterprise de verdade.

**Checklist tecnico**

- padronizar campos minimos de log
- incluir tenant, status, latencia e tipo de evento
- revisar agregacao de metricas
- expor recorte por tenant

**Modulos provaveis**

- `src/services/telemetry_service.py`
- `src/api/main.py`

**Criterio de aceite**

- dashboard e auditoria conseguem filtrar por tenant com consistencia

### TKT-016 — Definir SLI, SLO e alertas minimos

**Prioridade**

- P1

**Sprint**

- H5

**Dono funcional**

- Platform

**Dependencias**

- TKT-015

**Descricao**

Sair de monitoramento passivo para operacao com sinais e metas explicitas.

**Checklist tecnico**

- definir `uptime`, `p99_latency` e `error_rate`
- documentar janela de medicao
- configurar alertas minimos
- validar alertas em condicao controlada

**Modulos provaveis**

- docs de observabilidade
- scripts ou jobs de agregacao

**Criterio de aceite**

- plataforma possui criterio operacional explicito de saude

### TKT-017 — Evoluir dashboard para leitura executiva enterprise

**Prioridade**

- P1

**Sprint**

- H5

**Dono funcional**

- Frontend + Platform

**Dependencias**

- TKT-015
- TKT-016

**Descricao**

Transformar o dashboard atual em painel executivo capaz de apoiar leitura de saude, risco e uso por tenant.

**Checklist tecnico**

- incluir KPIs de uso, latencia, risco e qualidade
- separar visao de admin global e operador local
- tratar empty, error e stale state

**Modulos provaveis**

- `frontend/app/dashboard/page.tsx`

**Criterio de aceite**

- dashboard apoia decisao operacional e executiva sem depender de Swagger

### TKT-018 — Tornar typecheck do frontend reproduzivel

**Prioridade**

- P1

**Sprint**

- H6

**Dono funcional**

- Platform + Frontend

**Dependencias**

- nenhuma

**Descricao**

Eliminar ou explicitar a dependencia de artefatos gerados para o typecheck do frontend.

**Checklist tecnico**

- revisar inclusoes de `.next/types`
- remover dependencia implicita ou documentar geracao
- validar `tsc --noEmit` em trilha limpa

**Modulos provaveis**

- `frontend/tsconfig.json`

**Criterio de aceite**

- typecheck roda limpo de forma previsivel

### TKT-019 — Parametrizar smoke test e reduzir dependencia de portas fixas

**Prioridade**

- P1

**Sprint**

- H6

**Dono funcional**

- QA/Data + Frontend

**Dependencias**

- nenhuma

**Descricao**

O smoke atual depende de bind fixo e fragiliza reproducao. Este ticket flexibiliza a execucao.

**Checklist tecnico**

- parametrizar portas
- revisar `reuseExistingServer` e suposicoes de ambiente
- preservar cobertura dos fluxos criticos

**Modulos provaveis**

- `frontend/playwright.config.ts`
- `frontend/tests/phase2-gate.spec.ts`

**Criterio de aceite**

- smoke nao quebra por configuracao rigida de porta

### TKT-020 — Fazer a suite `pytest` encerrar com evidencia conclusiva

**Prioridade**

- P1

**Sprint**

- H6

**Dono funcional**

- QA/Data + Backend

**Dependencias**

- nenhuma

**Descricao**

Resolver a execucao inconclusiva da suite atual e documentar a trilha oficial de validacao backend.

**Checklist tecnico**

- identificar causa de nao encerramento limpo
- revisar fixtures, teardown e testes lentos
- documentar comando de validacao

**Modulos provaveis**

- `src/tests/conftest.py`
- `src/tests/test_sprint5.py`
- `src/scripts/run_pipeline_tests.py`

**Criterio de aceite**

- `pytest -q` termina com resultado conclusivo

### TKT-021 — Rodar reauditoria formal do gate da Fase 3

**Prioridade**

- P1

**Sprint**

- H6

**Dono funcional**

- Platform + QA/Data

**Dependencias**

- TKT-018
- TKT-019
- TKT-020
- todos os tickets P0 concluidos

**Descricao**

Executar nova rodada formal de validacao, atualizar checklist do gate e revisar notas.

**Checklist tecnico**

- rerodar validacoes oficiais
- atualizar `0031`
- atualizar relatorio de auditoria
- preparar nova decisao de go/no-go

**Modulos provaveis**

- `docs/rag-enterprise/0031-checklist-do-gate-da-fase-3.md`
- novo relatorio ou revisao do `0032`

**Criterio de aceite**

- existe evidencia suficiente para nova decisao formal

---

## Tickets P2

### TKT-022 — Implementar branding e onboarding por tenant

**Prioridade**

- P2

**Sprint**

- apos H6 ou paralelizado sem risco ao trilho critico

**Dono funcional**

- Frontend + Backend

**Dependencias**

- TKT-003
- TKT-010

**Descricao**

Completar a experiencia enterprise com configuracao visual e onboarding minimo por tenant.

**Checklist tecnico**

- suportar configuracoes basicas por tenant
- revisar onboarding de novo tenant
- evitar dependencia de seed manual

**Criterio de aceite**

- novo tenant pode nascer com configuracao basica e fluxo minimamente guiado

### TKT-023 — Criar workflow de aprovacao administrativa

**Prioridade**

- P2

**Sprint**

- apos H6

**Dono funcional**

- Backend + Frontend

**Dependencias**

- TKT-005

**Descricao**

Adicionar governanca mais forte para mudancas administrativas criticas.

**Checklist tecnico**

- definir estados de aprovacao
- registrar aprovador e justificativa
- expor fluxo na UI

**Criterio de aceite**

- mudancas criticas podem exigir aprovacao consultavel

### TKT-024 — Formalizar retencao e hardening de UX enterprise

**Prioridade**

- P2

**Sprint**

- apos H6

**Dono funcional**

- Platform + Frontend

**Dependencias**

- TKT-015

**Descricao**

Fechar a rodada com politicas operacionais minimas e refinamento de UX nas rotas centrais.

**Checklist tecnico**

- formalizar retencao de logs
- revisar erros, vazios e loading
- revisar uso em tablet e mobile

**Criterio de aceite**

- operacao minima documentada e UX mais consistente

---

## Ordem recomendada de criacao

1. TKT-001
2. TKT-002
3. TKT-003
4. TKT-004
5. TKT-005
6. TKT-006
7. TKT-007
8. TKT-008
9. TKT-009
10. TKT-010
11. TKT-011
12. TKT-012
13. TKT-013
14. TKT-014
15. TKT-015
16. TKT-016
17. TKT-017
18. TKT-018
19. TKT-019
20. TKT-020
21. TKT-021
22. TKT-022
23. TKT-023
24. TKT-024

---

## Ordem recomendada de execucao

1. TKT-001 a TKT-006
2. TKT-007 a TKT-010
3. TKT-011 a TKT-013
4. TKT-014 a TKT-017
5. TKT-018 a TKT-021
6. TKT-022 a TKT-024

