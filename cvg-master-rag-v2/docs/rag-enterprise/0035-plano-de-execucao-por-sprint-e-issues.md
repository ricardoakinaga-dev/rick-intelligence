# 0035 — Plano de Execucao por Sprint e Issues

## Objetivo

Quebrar a rodada corretiva em sprints executaveis e issues tecnicas pequenas o suficiente para implementacao e acompanhamento.

Este documento complementa:

- `0032-relatorio-de-auditoria-do-programa-2026-04-17.md`
- `0033-backlog-corretivo-pos-auditoria.md`
- `0034-backlog-operacional-da-rodada-corretiva.md`

---

## Regra de uso

Cada issue abaixo deve terminar com:

- mudanca implementada
- teste ou evidencia equivalente
- atualizacao de documentacao se o contrato mudou

Nao marcar sprint como encerrada se houver:

- auth ainda confiando no cliente
- tenancy sem prova de isolamento
- metricas infladas sendo usadas para conclusao executiva

---

## Sprint H1 — Auth e Sessao Confiavel

### Objetivo da sprint

Remover o modelo de demonstracao baseado em cabecalho e fazer a sessao nascer do servidor.

### Issues

#### H1-01 — Introduzir camada de autenticacao real no backend

**Tipo**

- backend

**Modulos mais provaveis**

- `src/api/main.py`
- `src/services/enterprise_service.py`
- `src/models/schemas.py`

**Checklist tecnico**

- definir origem confiavel de identidade
- implementar resolucao de sessao no servidor
- retornar sessao autenticada em `GET /session`
- tratar expiracao e logout

**Criterio de aceite**

- o backend nao depende de `X-Enterprise-*` para identidade principal
- sessao muda apenas por fluxo autenticado

#### H1-02 — Migrar o frontend para sessao autenticada de verdade

**Tipo**

- frontend

**Modulos mais provaveis**

- `frontend/components/layout/enterprise-session-provider.tsx`
- `frontend/components/layout/app-shell.tsx`
- `frontend/app/login/page.tsx`
- `frontend/app/forbidden/page.tsx`

**Checklist tecnico**

- trocar bootstrap local por sessao vinda do backend
- tratar loading de sessao e sessao expirada
- revisar logout e fluxo de recovery

**Criterio de aceite**

- login, logout e refresh de sessao funcionam sem spoofing client-side
- shell reage a sessao invalida sem estado incoerente

#### H1-03 — Criar testes de spoofing de role e tenant

**Tipo**

- backend + QA

**Modulos mais provaveis**

- `src/tests/conftest.py`
- `src/tests/test_sprint5.py`

**Checklist tecnico**

- criar caso negativo para role forjada
- criar caso negativo para tenant forjado
- validar bloqueio consistente

**Criterio de aceite**

- tentativa de spoofing falha de forma reproduzivel

### Definicao de pronto da sprint

- auth resolvida no servidor
- frontend consumindo sessao real
- testes negativos de spoofing verdes

---

## Sprint H2 — RBAC e Persistencia Administrativa

### Objetivo da sprint

Persistir identidade e governanca administrativa.

### Issues

#### H2-01 — Modelar usuario, tenant e membership persistidos

**Tipo**

- backend

**Modulos mais provaveis**

- `src/services/admin_service.py`
- `src/services/enterprise_service.py`
- `src/models/schemas.py`

**Checklist tecnico**

- definir modelo persistente de usuario
- definir modelo persistente de tenant
- definir membership com role
- adaptar leitura e escrita hoje em memoria

**Criterio de aceite**

- restart nao perde entidades administrativas

#### H2-02 — Aplicar RBAC server-side nas rotas centrais

**Tipo**

- backend

**Modulos mais provaveis**

- `src/api/main.py`

**Checklist tecnico**

- centralizar verificacao de role
- proteger admin, audit, metrics e operacao sensivel
- padronizar resposta de acesso negado

**Criterio de aceite**

- `admin`, `operator` e `viewer` apresentam comportamento distinto no backend

#### H2-03 — Registrar eventos administrativos auditaveis

**Tipo**

- backend

**Modulos mais provaveis**

- `src/services/admin_service.py`
- `src/services/telemetry_service.py`

**Checklist tecnico**

- registrar ator, acao, alvo, tenant e timestamp
- incluir request id quando disponivel
- expor leitura para auditoria administrativa

**Criterio de aceite**

- criar tenant, editar usuario e remover membership geram evento auditavel

#### H2-04 — Adaptar a UI administrativa para persistencia real

**Tipo**

- frontend

**Modulos mais provaveis**

- `frontend/app/admin/page.tsx`

**Checklist tecnico**

- remover pressuposto de store em memoria
- tratar erro de persistencia
- refletir estados reais de loading e falha

**Criterio de aceite**

- CRUD administrativo sobrevive a refresh e nova sessao

### Definicao de pronto da sprint

- tenants, usuarios e memberships persistidos
- RBAC aplicado no backend
- trilha administrativa minima funcionando

---

## Sprint H3 — Isolamento Multi-Tenant

### Objetivo da sprint

Provar que o tenant e um limite real de dados e operacao.

### Issues

#### H3-01 — Revisar isolamento em documentos e ingestao

**Tipo**

- backend

**Modulos mais provaveis**

- `src/services/ingestion_service.py`
- `src/api/main.py`

**Checklist tecnico**

- validar filtro por tenant em upload e listagem
- revisar workspace ativo versus tenant ativo
- impedir associacao cruzada indevida

**Criterio de aceite**

- tenant nao enxerga nem altera documentos fora do proprio escopo

#### H3-02 — Revisar isolamento em busca, chat e grounding

**Tipo**

- backend

**Modulos mais provaveis**

- `src/services/search_service.py`
- `src/services/grounding_service.py`
- `src/services/vector_service.py`
- `src/api/main.py`

**Checklist tecnico**

- garantir filtro por tenant nos caminhos de retrieval
- revisar citacoes, corpus e lookup de chunks
- revisar qualquer cache ou indice que possa misturar tenants

**Criterio de aceite**

- query em tenant A nao recupera conteudo do tenant B

#### H3-03 — Revisar isolamento em auditoria e metricas

**Tipo**

- backend + platform

**Modulos mais provaveis**

- `src/services/telemetry_service.py`
- `src/api/main.py`

**Checklist tecnico**

- segmentar leitura de logs por tenant
- segmentar agregacoes e metricas
- impedir vazamento em dashboard e auditoria

**Criterio de aceite**

- auditoria e metricas respeitam tenant do servidor

#### H3-04 — Criar suite de nao-vazamento entre 3 tenants

**Tipo**

- QA + backend + frontend

**Modulos mais provaveis**

- `src/tests/test_sprint5.py`
- `frontend/tests/phase2-gate.spec.ts`

**Checklist tecnico**

- cobrir 3 tenants ativos
- criar testes negativos de leitura cruzada
- incluir ao menos um fluxo UI critico

**Criterio de aceite**

- suite prova isolamento em backend e trilha minima de UI

### Definicao de pronto da sprint

- nao vazamento entre tenants provado por teste
- dashboard e auditoria segmentados no backend

---

## Sprint H4 — Avaliacao Honesta e Calibracao

### Objetivo da sprint

Fazer a trilha de avaliacao virar evidencia confiavel de qualidade.

### Issues

#### H4-01 — Ampliar dataset para multiplos documentos e tenants

**Tipo**

- data

**Modulos mais provaveis**

- `src/data/default/dataset.json`

**Checklist tecnico**

- incluir mais de um documento
- incluir mais de um tenant ou workspace
- balancear perguntas por categoria e dificuldade

**Criterio de aceite**

- dataset deixa de depender de um unico documento

#### H4-02 — Corrigir runner para nao inflar retrieval e confianca

**Tipo**

- backend + data

**Modulos mais provaveis**

- `src/services/evaluation_service.py`

**Checklist tecnico**

- remover `threshold=0.0` se ele for artificialmente permissivo
- separar metricas com e sem judge
- revisar computo de groundedness

**Criterio de aceite**

- relatorio de avaliacao nao mascara falhas reais

#### H4-03 — Recalibrar `low_confidence`

**Tipo**

- backend

**Modulos mais provaveis**

- `src/services/search_service.py`
- `src/services/grounding_service.py`
- `src/services/evaluation_service.py`

**Checklist tecnico**

- revisar regra e threshold do classificador
- comparar com exemplos reais de `queries.jsonl`
- validar queda de falso positivo

**Criterio de aceite**

- respostas uteis e citadas deixam de ser marcadas como baixa confianca sem motivo

### Definicao de pronto da sprint

- dataset ampliado
- runner honesto
- confianca calibrada com menor ruido

---

## Sprint H5 — Observabilidade e Operacao Enterprise

### Objetivo da sprint

Fechar o contrato operacional enterprise pedido pela documentacao.

### Issues

#### H5-01 — Introduzir `request_id` ponta a ponta

**Tipo**

- platform + backend

**Modulos mais provaveis**

- `src/api/main.py`
- `src/services/telemetry_service.py`

**Checklist tecnico**

- gerar ou propagar `request_id`
- anexar a logs de query, ingestao e avaliacao
- devolver `request_id` em respostas relevantes quando fizer sentido

**Criterio de aceite**

- uma query pode ser correlacionada do request ao log final

#### H5-02 — Estruturar logs e metricas por tenant

**Tipo**

- platform + backend

**Modulos mais provaveis**

- `src/services/telemetry_service.py`
- endpoints de metricas em `src/api/main.py`

**Checklist tecnico**

- padronizar campos minimos
- incluir tenant, status, latencia e tipo de evento
- revisar agregacao para recorte por tenant

**Criterio de aceite**

- dashboard e auditoria conseguem filtrar por tenant com consistencia

#### H5-03 — Definir alertas e janela de SLA

**Tipo**

- platform

**Modulos mais provaveis**

- scripts operacionais
- docs de observabilidade

**Checklist tecnico**

- definir SLI e SLO
- medir `uptime`, `p99_latency` e `error_rate`
- documentar alertas minimos

**Criterio de aceite**

- plataforma tem criterio operacional explicito de saude

#### H5-04 — Transformar o dashboard em painel executivo

**Tipo**

- frontend + platform

**Modulos mais provaveis**

- `frontend/app/dashboard/page.tsx`

**Checklist tecnico**

- destacar KPIs de uso, risco, qualidade e latencia
- separar visao de admin global e operador local
- tratar empty, error e stale state

**Criterio de aceite**

- o dashboard serve decisao, nao apenas debugging

### Definicao de pronto da sprint

- request tracing minimo funcionando
- metricas por tenant operaveis
- dashboard executivo disponivel

---

## Sprint H6 — Qualidade de Release e Fechamento do Gate

### Objetivo da sprint

Fechar reproducao, smoke e evidencia final para reauditoria.

### Issues

#### H6-01 — Limpar o typecheck do frontend

**Tipo**

- platform + frontend

**Modulos mais provaveis**

- `frontend/tsconfig.json`

**Checklist tecnico**

- remover dependencia implicita de `.next/types` ou documentar geracao
- garantir `tsc --noEmit` reproduzivel

**Criterio de aceite**

- typecheck roda limpo em ambiente previsivel

#### H6-02 — Parametrizar o smoke test

**Tipo**

- QA + frontend

**Modulos mais provaveis**

- `frontend/playwright.config.ts`
- `frontend/tests/phase2-gate.spec.ts`

**Checklist tecnico**

- tornar portas configuraveis
- reduzir dependencia de bind fixo
- manter cobertura dos fluxos criticos

**Criterio de aceite**

- smoke nao falha por suposicao rigida de ambiente

#### H6-03 — Fazer `pytest` encerrar com evidencia conclusiva

**Tipo**

- QA + backend

**Modulos mais provaveis**

- `src/tests/test_sprint5.py`
- `src/scripts/run_pipeline_tests.py`

**Checklist tecnico**

- identificar por que a suite nao fecha limpo
- estabilizar fixtures e teardown
- documentar comando oficial de validacao

**Criterio de aceite**

- `pytest -q` termina com resultado conclusivo

#### H6-04 — Rodada final de reauditoria do gate

**Tipo**

- platform + QA + leadership tecnica

**Checklist tecnico**

- rerodar validacoes oficiais
- atualizar checklist do gate
- atualizar notas do relatorio

**Criterio de aceite**

- existe evidencia suficiente para nova decisao de go/no-go

### Definicao de pronto da sprint

- trilha de validacao reproduzivel
- gate preparado para reavaliacao formal

---

## Mapa rapido de modulos mais sensiveis

### Backend central

- `src/api/main.py`
- `src/services/enterprise_service.py`
- `src/services/admin_service.py`
- `src/services/telemetry_service.py`
- `src/services/evaluation_service.py`
- `src/services/search_service.py`
- `src/services/grounding_service.py`
- `src/services/ingestion_service.py`
- `src/services/vector_service.py`
- `src/models/schemas.py`

### Frontend central

- `frontend/components/layout/enterprise-session-provider.tsx`
- `frontend/components/layout/app-shell.tsx`
- `frontend/app/login/page.tsx`
- `frontend/app/admin/page.tsx`
- `frontend/app/dashboard/page.tsx`
- `frontend/app/audit/page.tsx`
- `frontend/app/documents/page.tsx`
- `frontend/app/search/page.tsx`
- `frontend/app/chat/page.tsx`
- `frontend/playwright.config.ts`
- `frontend/tests/phase2-gate.spec.ts`
- `frontend/tsconfig.json`

### Testes e suporte

- `src/tests/conftest.py`
- `src/tests/test_sprint5.py`
- `src/scripts/run_pipeline_tests.py`

---

## Meta final

Ao fim deste plano, o programa deve sair de:

- premium funcional com fundacao enterprise parcial

para:

- plataforma enterprise com seguranca, isolamento, operacao e evidencia de gate sustentaveis

