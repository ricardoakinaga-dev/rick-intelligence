# 0020 — Master Execution Log

## Objetivo

Registrar a execução real do projeto, com base em evidência reproduzível, sem inflar resultados nem declarar gates sem validação executada.

---

## Status Atual

```text
PROJETO: RAG Database Builder
VERSÃO DO PLANO: 1.7 — convergência final encerrada
STATUS ATUAL: FUNDAÇÃO FECHADA — GATE F0 LIBERADO — PHASE B DESBLOQUEADA

LEITURA:
- o Sprint D1 restaurou a consistência entre corpus canônico, disco e índice
- o Sprint D2 fechou metadata e retrieval no mínimo operacional da fase
- o Sprint D3 fechou avaliação e observabilidade auditáveis
- o Sprint D4 reexecutou o pacote mínimo final de evidências
- a fundação está apta para seguir para a próxima fase

GATE F0:
- LIBERADO
- decisão baseada em evidência reproduzível executada em 2026-04-16

ÚLTIMA ATUALIZAÇÃO: 2026-04-16
```

---

## Evidência Final do Gate

### Pacote mínimo executado

| # | Validação | Resultado |
|---|---|---|
| 1 | `pytest -q` | `42 passed, 6 skipped` |
| 2 | `Dataset(**dataset.json)` | `30` perguntas, válido |
| 3 | `GET /documents/{document_id}` | `200`, metadata completa |
| 4 | Qdrant vs disco | `7` pontos, `7` IDs únicos, `1` documento, `7` chunks |
| 5 | `low_confidence` offline | query válida `false`; nonsense/OOD/symbol `true` |
| 6 | `/evaluation/run?workspace_id=default&run_judge=false` | `30` `question_results`, `hit_rate_top_1/3/5 = 1.0` |
| 7 | `/metrics` | blocos `retrieval`, `answer`, `evaluation` presentes |
| 8 | geração de respostas no dataset | `30/30` queries respondidas, `avg_latency_ms = 1458.2` |
| 9 | upload multi-formato | `PDF`, `DOCX`, `MD`, `TXT` retornando `201` |
| 10 | telemetry de falha de ingestão | erro de upload registrado com motivo |

### Evidência observada

| Área | Evidência |
|---|---|
| Suíte principal | verde: `42 passed, 6 skipped` |
| Dataset | `30` perguntas válidas no schema oficial |
| Corpus canônico | `src/data/documents/default/` com `1` documento e `7` chunks |
| Índice vetorial | consistente com o disco canônico: `7 = 7` |
| Metadata | `created_at`, `tags`, `embeddings_model` e `indexed_at` presentes |
| Retrieval | `document_filename`, `filters` suportados e `scores_breakdown` presentes |
| Avaliação | `question_results`, `avg_score`, `by_difficulty`, `by_category` presentes |
| Query pipeline | `30/30` respostas geradas no dataset com latência média abaixo de `5s` |
| Observabilidade | `/health` mostra estado do app, corpus, Qdrant e snapshot operacional de telemetria; `/metrics` entrega agregações mínimas de retrieval, answer e evaluation |
| Multi-formato | parsing validado por spot-check em `PDF`, `DOCX`, `MD` e `TXT` |

---

## Sprint D1 — Baseline e Integridade do Corpus

### Entrega real

1. O corpus canônico foi limpo para manter apenas o documento referenciado pelo dataset.
2. Duplicatas foram movidas para `src/data/documents-ARCHIVED/default/`.
3. A collection foi reindexada a partir do corpus canônico.
4. Os testes de consistência passaram a validar apenas o workspace e corpus oficiais.

### Evidência

- corpus canônico: `1` documento, `7` chunks
- Qdrant: `7` pontos, `7` IDs únicos, `1` documento
- `pytest -q`: verde

### Status

`CONCLUÍDO`

---

## Sprint D2 — Fechamento dos Contratos de API

### Entrega real

1. `GET /documents/{id}` passou a retornar metadata canônica completa da fase.
2. `/search` passou a devolver `document_filename`.
3. `include_raw_scores=true` passou a devolver `scores_breakdown`.
4. Filtros suportados foram implementados no retrieval.
5. As citações de `/query` passaram a carregar `document_filename`.

### Evidência

- metadata observada com `created_at`, `tags`, `embeddings_model`, `indexed_at`
- `/search` com breakdown e filename
- testes específicos adicionados para retrieval, metadata e citações

### Status

`CONCLUÍDO`

---

## Sprint D3 — Avaliação e Observabilidade Auditáveis

### Entrega real

1. A resposta de avaliação passou a manter `question_results`.
2. O aggregate passou a expor `avg_score`, `by_difficulty` e `by_category`.
3. O `/metrics` passou a consolidar retrieval, answer e evaluation.
4. O telemetry de query foi alinhado ao shape mínimo da fase.
5. O telemetry de ingestão passou a registrar falhas com motivo.

### Evidência

- `/evaluation/run` com `question_results_len = 30`
- `/metrics` com blocos `retrieval`, `answer`, `evaluation`
- testes cobrindo shape de avaliação, métricas e logging de falha

### Status

`CONCLUÍDO`

---

## Sprint D4 — Gate Rehearsal Final

### Entrega real

1. O pacote mínimo final de validação foi reexecutado.
2. A consistência `Qdrant = disco` foi confirmada em runtime.
3. O comportamento de `low_confidence` foi revalidado com mock determinístico.
4. O pipeline de resposta foi exercitado em todo o dataset.
5. Upload e parsing multi-formato foram exercitados em workspace isolado.

### Evidência

- `pytest -q`: `42 passed, 6 skipped`
- Qdrant vs disco: `7` pontos = `7` chunks
- `low_confidence`: válida `false`; nonsense/OOD/symbol `true`
- `30/30` respostas geradas com `avg_latency_ms = 1458.2`
- uploads `PDF`, `DOCX`, `MD`, `TXT` com `201`
- spot-check de parsing confirmado nos arquivos de teste

### Decisão

`GATE F0 LIBERADO`

---

## Decisões Arquiteturais Vigentes

| ID | Data | Decisão | Motivo |
|---|---|---|---|
| D-001 | 2026-04-16 | `document_id` permanece o contrato canônico | dataset, schema e runtime convergiram |
| D-002 | 2026-04-16 | `src/data/documents/default/` permanece o diretório canônico | config e operação seguem essa convenção |
| D-003 | 2026-04-16 | duplicatas do corpus canônico ficam arquivadas fora do diretório ativo | evita drift entre disco e índice |
| D-004 | 2026-04-16 | metadata e retrieval fecham no mínimo operacional da fase | contrato final da F0 ficou reproduzível |
| D-005 | 2026-04-16 | avaliação e telemetry fecham no mínimo operacional da fase | pacote de qualidade passou a ser auditável |
| D-006 | 2026-04-16 | Gate F0 é liberado | evidência mínima da fase foi reexecutada com sucesso |

---

## Riscos Remanescentes

| Risco | Severidade | Situação |
|---|---|---|
| Semântica de threshold vs score RRF ainda pouco intuitiva | Baixa | Aberto, pós-gate |
| Observabilidade premium ainda não implementada | Média | Fora do escopo da F0 |

---

## Pós-Gate Imediato

### P1-01 — Migração para lifespan

Entrega confirmada no código ativo:

- `src/api/main.py` usa `lifespan=lifespan`
- não há uso ativo de `@app.on_event`
- `pytest -q` segue verde após a migração

### P1-02 — Documentação de rebuild/reindex

Entrega concluída em `2026-04-16` com runbook operacional dedicado:

- `0024-operacao-de-corpus-e-reindex.md`

O runbook fixa:

- diretório canônico do corpus
- diretório arquivado
- quando usar `--local-only`
- quando usar reindex completo
- como validar `Qdrant = disco`
- como tratar drift e duplicatas

### P1-03 — Reforço dos testes de retrieval

Entrega concluída em `2026-04-16` com ampliação da suíte para cobrir:

- encaminhamento de `document_id` e faixa de `page_hint` para o filtro do Qdrant
- filtro pós-fusão por `source_type`
- filtro pós-fusão por `tags`
- filtro pós-fusão por `page_hint_min/page_hint_max`

Evidência:

- `pytest -q`: `42 passed, 6 skipped`

### P1-04 — Melhoria do reporte de groundedness

Entrega concluída em `2026-04-16` com reforço do shape de groundedness em runtime e telemetry:

- `QueryResponse.grounding` tipado como `GroundingReport`
- query logs registrando `grounding_reason`, `uncited_claims_count` e `needs_review`
- `/metrics` no bloco `answer` agora expondo:
  - `grounded_answers`
  - `no_context_answers`
  - `ungrounded_answers`
  - `answers_needing_review`
  - `avg_uncited_claims`

Evidência:

- `pytest -q`: `42 passed, 6 skipped`

---

## Progresso da Fase 2 — Frontend Premium

### Estado real observado em 2026-04-16

O repositório já contém um frontend funcional em `frontend/`, com integração real ao backend.

Leitura honesta:

- `frontend/` é o frontend canônico atual
- a base paralela antiga de frontend foi removida do repositório
- o código já cobre materialmente `F1` a `F8`
- `F7` está consolidado no código
- `F8` foi executado como gate e aprovado

### Evidência reproduzida

| Área | Evidência |
|---|---|
| Frontend canônico | `frontend/README.md` declara `frontend/` como fonte de verdade da Fase 2 |
| Shell e navegação | rotas reais em `frontend/app/` para `documents`, `search`, `chat`, `dashboard` e `audit` |
| Admin enterprise | `/admin` com CRUD operacional para tenants e usuários |
| Busca | filtros por `document_id`, `tags`, `page_hint_min/page_hint_max`, painel de evidência e `scores_breakdown` |
| Chat | histórico local da sessão, cópia de resposta, badges de confiança e grounding |
| Navegação transversal | breadcrumbs e persistência de contexto em `documents`, `search`, `chat`, `dashboard` e `audit` |
| Build | `frontend/.next/BUILD_ID` gerado após compilação |
| Lint | `pnpm -C frontend lint` passou |
| Backend | `pytest -q` em `src`: `40 passed, 3 skipped` |
| UI smoke | `pnpm -C frontend test:smoke`: `5 passed` |
| Start local | `next start` em `frontend/` subiu com sucesso |
| Smoke HTTP | `/`, `/documents`, `/search`, `/chat`, `/dashboard`, `/audit` = `200` |

### Leitura por sprint

| Sprint | Status honesto | Observação |
|---|---|---|
| F1 | materialmente implementado | shell, tema, navegação e componentes base existem |
| F2 | materialmente implementado | painel de documentos com upload, filtros e metadata |
| F3 | materialmente implementado | busca com filtros e inspeção de evidência |
| F4 | materialmente implementado | chat com resposta, citações e sinais de confiança |
| F5 | materialmente implementado | dashboard com KPIs e leitura operacional |
| F6 | materialmente implementado | auditoria com filtros e detalhe de logs |
| F7 | materialmente implementado | persistência de contexto, breadcrumbs, drawer mobile e responsividade mínima validados |
| F8 | concluído | gate visual formal aprovado com smoke validado |

### Gaps remanescentes da Fase 2

- consolidar documentação final da Fase 2
- abrir a trilha de evolução da Fase 3

### Próximo passo correto da Fase 2

- usar `0029-checklist-do-gate-visual-da-fase-2.md` como registro formal da aprovação
- transicionar o foco para a Fase 3

### Resultado da execução do checklist

Evidência reproduzida nesta rodada:

- `pytest -q`: `40 passed, 3 skipped`
- `pnpm -C frontend lint`: passou
- `pnpm -C frontend build`: compilou com geração de `BUILD_ID`
- `pnpm -C frontend test:smoke`: `5 passed`
- smoke test do frontend canônico: `/`, `/documents`, `/search`, `/chat`, `/dashboard`, `/audit` = `200`
- upload web validado pela UI em workspace isolado
- `/health`: `healthy`
- `/documents`: `200`
- `/documents/{document_id}`: `200`
- `/metrics`: `200`
- `/queries/logs`: `200`

Achado importante desta rodada:

- o endpoint `/queries/logs` estava quebrado por assinatura incorreta em `TelemetryService`
- o bug foi corrigido
- foi adicionado teste para evitar regressão futura
- rows legadas de telemetria passaram a ser normalizadas antes da serialização
- o pipeline de `query` recebeu fallback offline determinístico para ambientes sem `OPENAI_API_KEY`
- foi adicionada suíte Playwright para validar busca, chat, navegação e responsividade mínima do frontend canônico

Decisão honesta após a execução do gate visual:

- `Fase 2 concluída`
- a base paralela antiga foi removida do repositório

### Evolução documental posterior

O frontend canônico foi consolidado em `frontend/` com os seguintes marcos adicionais:

- `pnpm -C frontend lint` passou
- `pnpm -C frontend exec tsc --noEmit` passou
- `pnpm -C frontend build` compilou com sucesso
- `pnpm -C frontend test:smoke` passou com `5` cenários
- a navegação mobile passou a usar drawer
- a experiência desktop/tablet foi fechada no código

Status honesto após essa consolidação:

- a implementação da Fase 2 está materialmente completa no frontend
- o gate visual formal foi aprovado com smoke validado
- o checklist `0029` permanece como fonte da decisão formal

Referência:

- `0029-checklist-do-gate-visual-da-fase-2.md`

---

## Leitura Final da Fundação

### O que está construído de fato

- ingestão multi-formato (`PDF`, `DOCX`, `MD`, `TXT`)
- parsing persistido em disco
- chunking recursivo com offsets e overlap
- embeddings e indexação híbrida no Qdrant
- retrieval com filtros suportados e breakdown opcional
- metadata de documentos no contrato mínimo da fase
- `low_confidence` validado offline
- pipeline de query com citações
- avaliação auditável com resultados por pergunta
- `/metrics` operacional para retrieval, answer e evaluation
- suíte principal verde
- groundedness tipado com motivo e claims sem citação

### O que fica para pós-gate

- hardening premium de observabilidade
- melhorias avançadas de retrieval e operabilidade enterprise

---

## Sanity Check Atual

### Validação executada após o alinhamento documental

- `pnpm -C frontend exec tsc --noEmit`: passou
- `pnpm -C frontend lint`: passou
- `pnpm -C frontend build`: passou
- `pnpm -C frontend test:smoke`: passou com `5 passed`
- `pytest -q`: passou com `48 passed, 3 skipped`

### Leitura

- o frontend premium está buildando e tipando corretamente
- o backend principal segue verde após a fundação enterprise
- o ajuste documental não introduziu regressão de compilação
- a decisão formal do gate da Fase 2 continua `aprovado`

## Fase 3 - Sprint G1

### Avanço implementado

- contrato de sessão enterprise exposto no backend
- login, recuperação e onboarding criados no frontend
- `GET /auth/me` exposto para introspecção explícita
- shell global com seletor de tenant, role badge e logout
- guardas de navegação por role com redirecionamento para `/login` e `/forbidden`
- bootstrap de sessão anônima por padrão e persistência local da sessão autenticada
- proteção contra race entre bootstrap anônimo e login interativo
- workspace ativo do contexto enterprise propagado para documentos, busca, chat e auditoria

### Evidência

- `pnpm -C frontend exec tsc --noEmit`: passou
- `pnpm -C frontend lint`: passou
- `pnpm -C frontend build`: passou
- `pnpm -C frontend test:smoke`: `5 passed`
- `pytest -q`: `48 passed, 3 skipped`

### Status

`CONCLUÍDO`

## Fase 3 - Sprint G2

### Avanço implementado

- painel `/admin` com CRUD operacional para tenants e usuários
- criação, edição e remoção de tenants via UI
- criação, edição e remoção de usuários via UI
- proteção visual do tenant bootstrap contra remoção
- enforcement backend de role e workspace para admin e rotas sensíveis

### Leitura

- a fundação enterprise da Fase 3 já existe materialmente no workspace e o G1 foi validado
- o G2 começou a sair do backlog com operação real de admin e enforcement central
- G3-G4 continuam em backlog

---

## Próximo Passo

Continuar `G2` e atacar persistência/isolamento real de multitenancy antes de avançar para observabilidade.
