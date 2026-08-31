# 0032 — Relatorio de Auditoria do Programa

## Objetivo

Registrar a auditoria formal do programa em `2026-04-17`, usando `docs/rag-enterprise` como fonte de verdade normativa e o código ativo como evidência de implementação.

Este documento existe para:

- consolidar a leitura executiva do estado atual
- registrar notas objetivas por item
- apontar gaps reais com evidência verificável
- decidir se o gate da Fase 3 pode ser aprovado

---

## Fonte de verdade utilizada

Leitura principal baseada em:

- `0007-fase-3-rag-enterprise.md`
- `0009-contratos-de-ingestao.md`
- `0010-contratos-de-retrieval.md`
- `0011-contratos-de-avaliacao.md`
- `0013-quality-gates.md`
- `0019-observabilidade-e-metricas.md`
- `0025-visao-final-enterprise-premium.md`
- `0026-mapa-de-aderencia-ao-guia.md`
- `0030-backlog-por-sprint-da-fase-3.md`
- `0031-checklist-do-gate-da-fase-3.md`

---

## Resumo executivo

Nota geral do programa: **58/100**.

Leitura executiva:

- a **Fase 2** esta materialmente implementada
- a **Fase 3** esta iniciada com entregas reais
- o **gate da Fase 3 nao esta aprovado**
- o principal bloqueio atual e **seguranca, autenticacao e RBAC**

Leitura honesta: o produto ja e demonstravel como plataforma premium funcional, mas ainda nao sustenta a classificacao de plataforma enterprise pronta para operacao real.

---

## Notas por item

| Item | Nota | Leitura curta |
|---|---:|---|
| Governanca documental e aderencia ao guia | 87 | A trilha normativa esta consistente e descreve corretamente que a Fase 3 segue aberta. |
| Ingestao e parsing | 78 | Upload, parsing e catalogo existem e cobrem o contrato base. |
| Chunking e indexacao | 82 | O pipeline segue o desenho da fase e o corpus esta organizado por workspace. |
| Retrieval hibrido | 79 | Dense, sparse e RRF existem e a busca esta funcional. |
| Query, citacoes e grounding | 63 | O pipeline existe, mas o sinal de confianca ainda esta mal calibrado. |
| Dataset e avaliacao auditavel | 45 | O dataset e estreito e a leitura de qualidade esta otimista demais. |
| Observabilidade e metricas | 57 | Ha logs, agregacao e dashboard, mas nao no nivel pedido pelo contrato de observabilidade. |
| Frontend premium canonico | 88 | O app em `frontend/` e real, integrado e com build verde. |
| Multitenancy | 38 | Existe contexto de tenant, mas o isolamento ainda e fraco e pouco provado. |
| Admin panel e operacao de tenants | 55 | Ha CRUD visual, porem sem persistencia e governanca fortes. |
| Seguranca e RBAC | 18 | Principal bloqueio do programa neste momento. |
| SLA, alertas e tracing | 24 | Nao ha evidencias suficientes de operacao enterprise sob SLA. |
| Qualidade de engenharia e reprodutibilidade | 58 | Lint e build passaram, mas o typecheck e o smoke ainda nao sao reproduziveis de forma limpa. |

---

## Gate da Fase 3

Leitura por bloco do `0031-checklist-do-gate-da-fase-3.md`:

| Gate F3 | Nota | Veredito |
|---|---:|---|
| A. Frontend Enterprise | 78 | Implementado em boa parte, mas ainda nao completo no padrao enterprise final. |
| B. Multitenancy | 42 | Existe contexto de tenant, porem com isolamento fragil. |
| C. RBAC e Seguranca | 20 | Bloqueador principal do gate. |
| D. Operacao Enterprise | 47 | Ha UI e metricas, mas sem maturidade operacional enterprise. |
| E. Auditoria e Governanca | 34 | Ha trilha de queries, mas nao ha trilha administrativa forte. |
| F. Qualidade de Servico | 15 | Quase sem evidencia formal de SLA. |
| G. Produto Comercial | 69 | O produto ja e demonstravel, mas nao esta pronto para uso comercial enterprise. |

Veredito do gate:

- **Fase 3 nao aprovada**
- **nova rodada corretiva obrigatoria**

---

## Achados criticos

### 1. Autenticacao e RBAC ainda sao de demonstracao

O backend constroi a sessao a partir de cabecalhos enviados pelo cliente, o que descaracteriza autenticacao forte e enfraquece toda a camada de autorizacao.

Evidencias:

- `src/api/main.py:85`
- `src/api/main.py:107`
- `src/api/main.py:188`
- `src/services/enterprise_service.py:52`

Leitura:

- a identidade ativa pode ser inferida do cliente
- a role ativa nao nasce de sessao autenticada real
- o enforcement server-side existe, mas depende de uma origem nao confiavel

Nota atribuida ao item de seguranca: **18/100**.

### 2. Tenants e usuarios administrativos nao sao persistidos

O modelo administrativo atual usa estruturas em memoria, o que inviabiliza operacao enterprise real, trilha de auditoria confiavel e governanca entre sessoes.

Evidencias:

- `src/services/admin_service.py:11`
- `src/services/admin_service.py:92`

Leitura:

- CRUD existe na UI
- o estado administrativo nao esta em storage duravel
- nao ha trilha forte de mudancas administrativas

Nota atribuida ao item de operacao de tenants: **55/100**.

### 3. A avaliacao superestima a qualidade atual

O dataset atual nao sustenta uma leitura auditavel forte porque esta concentrado em um unico documento e o runner usa configuracao permissiva demais para leitura de retrieval e confianca.

Evidencias:

- `src/data/default/dataset.json:1`
- `src/services/evaluation_service.py:178`
- `src/services/evaluation_service.py:204`

Leitura:

- ha 30 perguntas, mas apenas 1 documento fonte
- o `threshold=0.0` torna a leitura de `low_confidence` artificialmente favoravel no runner
- `groundedness_rate` so e contado quando `run_judge=true`

Nota atribuida ao item de avaliacao auditavel: **45/100**.

### 4. Observabilidade ainda nao atende o contrato da Fase 3

Existe logging JSONL e agregacao operacional, mas ainda nao ha evidencias suficientes de request tracing, alertas, SLA por tenant ou telemetria no padrao definido em `0019`.

Evidencias:

- `src/services/telemetry_service.py:39`
- `frontend/app/dashboard/page.tsx:32`

Leitura:

- a telemetria atual e util para operacao local
- falta `request_id`, segmentacao mais forte, niveis de severidade e trilha ponta a ponta
- o dashboard atual e mais operacional do que executivo

Nota atribuida ao item de observabilidade: **57/100**.

### 5. O classificador de confianca esta mal calibrado

Os logs mostram respostas uteis e citadas marcadas com `low_confidence=true`, o que sugere ruido no sinal usado para gating de confianca.

Evidencias:

- `src/logs/queries.jsonl:59`

Leitura:

- ha grounding util que nao se converte em confianca operacional
- isso fragiliza auditoria de qualidade e review humano

Nota atribuida ao item de grounding e confianca: **63/100**.

### 6. A disciplina de release ainda nao esta limpa

O frontend builda e o lint passa, mas o typecheck depende de artefatos gerados e o smoke test atual nao foi reproduzivel no ambiente desta auditoria.

Evidencias:

- `frontend/tsconfig.json:35`
- `frontend/playwright.config.ts:15`

Leitura:

- o `tsc --noEmit` depende de `.next/types`
- o smoke falhou porque a stack exige bind fixo em `8010`
- a evidencia de qualidade ainda esta correta para um produto em progresso, nao para gate enterprise

Nota atribuida ao item de reprodutibilidade: **58/100**.

---

## Validacao executada

Validacoes executadas durante a auditoria:

- `pnpm -C frontend lint` -> passou
- `pnpm -C frontend build` -> passou
- `pnpm -C frontend exec tsc --noEmit` -> falhou por dependencia de artefatos `.next/types`
- `pnpm -C frontend test:smoke` -> falhou nesta execucao por conflito de porta `8010`
- `pytest -q` -> nao fechou com evidencia conclusiva reproduzivel neste ambiente

Leitura:

- existe base real e funcional
- ainda falta um trilho de validacao totalmente limpo, repetivel e pronto para gate

---

## Decisao final

Classificacao executiva:

- **Fase 2**: materialmente concluida
- **Fase 3**: parcialmente implementada
- **Gate F3**: nao aprovado
- **Status recomendado**: produto premium funcional com fundacao enterprise parcial e rodada corretiva obrigatoria

Decisao de go/no-go:

- **go para correcao dirigida**
- **no-go para declarar plataforma enterprise concluida**

---

## Prioridade real de correcao

1. substituir auth baseada em cabecalho por autenticacao real e autorizacao server-side confiavel
2. persistir tenants, usuarios, memberships e eventos administrativos em storage duravel
3. corrigir a trilha de avaliacao para nao superestimar qualidade
4. fechar observabilidade F3 com alertas, tracing e metricas por tenant
5. estabilizar typecheck e smoke para evidencia reproduzivel

