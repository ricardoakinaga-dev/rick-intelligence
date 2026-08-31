# Plano Mestre de Construção e Correção do Programa

**Data:** 2026-04-19  
**Status:** canônico para execução corretiva e reconvergência  
**Origem:** derivado de `BRIEFING/00.DiSCOVERY` → `BRIEFING/08.RUNTIME` e do relatório `BRIEFING/04.AUDIT/2026-04-19-relatorio-de-auditoria-do-programa.md`  
**Objetivo:** estruturar a reconstrução corretiva do `cvg-master-rag` em ordem executável, com gates, backlog, sprints, critérios de pronto e continuidade operacional

---

## 1. Propósito

Este plano transforma a auditoria de 2026-04-19 em um programa de execução controlada.

Ele existe para:

- corrigir os desvios críticos já identificados
- reconvergir implementação, frontend, backend e operação com a fonte de verdade do projeto
- impedir build improvisado
- organizar a execução em ordem CVG:
  - Discovery
  - PRD
  - SPEC
  - BUILD
  - AUDIT
  - AGENT LOOP / SESSION PERSISTENCE
  - SKILL
  - AGENTS
  - RUNTIME

---

## 2. Diagnóstico de Partida

Com base no relatório de auditoria, o sistema parte do seguinte estado:

### Forças reais

- backend RAG materialmente implementado
- frontend premium canônico existente em `frontend/`
- telemetria, avaliação e logs já operacionais
- fundação enterprise com sessão, tenant e admin básicos
- base documental forte em `docs/rag-enterprise/`

### Gaps críticos

- login frontend quebrado por divergência contratual
- smoke do frontend falhando `5/5`
- suíte backend não verde: `163 passed, 17 skipped, 4 failed`
- ingestão rígida com dependência forte de Qdrant
- corpus ativo inconsistente com `3` raws órfãos
- groundedness e confiança operacional abaixo do esperado
- requisitos Fase 3 ainda incompletos em alertas, tracing, branding, workflows e readiness comercial

### Leitura de risco

O projeto não está em fase de construção greenfield. Está em fase de:

- reconvergência funcional
- estabilização de contratos
- fechamento de dívida estrutural
- retomada de build enterprise com disciplina

---

## 3. Discovery

### Objetivo

Transformar a auditoria em problema estruturado, delimitado e priorizado antes de qualquer nova rodada de implementação.

### Trigger consolidado

- origem: auditoria técnica e funcional de 2026-04-19
- tipo de gatilho: falha operacional + divergência de contrato + risco de gate incorretamente assumido
- contexto inicial: produto com muita superfície construída, mas com quebras reais de ponta a ponta
- percepção consolidada: existe valor implementado, porém sem estabilidade suficiente para leitura de maturidade fechada

### Análise da dor

- quem sofre:
  - operador técnico
  - usuário do frontend
  - administrador do tenant
  - engenharia
- quando ocorre:
  - login
  - smoke da UI
  - execução de testes
  - ingestão sob indisponibilidade de infraestrutura
  - revisão de groundedness
- impacto:
  - impossibilidade de operar a UI ponta a ponta
  - risco de regressão mascarada por build verde
  - baixa confiabilidade para gate de fase
  - dificuldade de declarar enterprise readiness com evidência defensável

### Contexto operacional

- backend e frontend já estão em operação local real
- há logs, avaliações e corpus real
- a principal falha não está em ausência de módulo, mas em inconsistência entre camadas

### Problem framing

**Problema principal:** o programa possui implementação relevante, mas não possui ainda uma cadeia confiável e consistente entre contratos, runtime, corpus, experiência visual e critérios enterprise.

### Out of scope do ciclo corretivo atual

- redesign completo de produto
- reescrita arquitetural total
- nova stack
- features comerciais fora do escopo dos gaps auditados

### Hipótese de valor

Se o sistema recuperar consistência entre frontend, backend, corpus, testes, métricas e gates, ele sobe de base promissora para plataforma operacionalmente confiável, permitindo reabrir evolução enterprise real sem falsos positivos de maturidade.

### Discovery ready

Este plano considera o discovery corretivo pronto para avançar porque:

- a dor está definida
- os impactos são concretos
- o recorte é claro
- os gaps críticos já estão priorizados

---

## 4. PRD

### Objetivo

Materializar o comportamento esperado do programa corrigido sem discutir implementação.

### Produto alvo desta rodada

Um RAG premium-enterprise capaz de:

- permitir login funcional e acesso por perfil
- operar documentos, busca, chat, dashboard e auditoria sem depender de Swagger
- manter corpus íntegro e reindexável
- sustentar contratos estáveis entre frontend e backend
- produzir resposta com groundedness defensável
- expor governança básica, multitenancy consistente e admin utilizável

### Casos de uso prioritários

1. Usuário entra no frontend com perfil e tenant válidos e navega para os módulos principais.
2. Operador faz upload visual de documento e o documento entra no corpus canônico sem inconsistência.
3. Usuário busca no corpus com evidência e filtros confiáveis.
4. Usuário pergunta no chat e recebe resposta com grounding e citações utilizáveis.
5. Operador acompanha métricas e logs sem precisar ler código.
6. Admin gerencia tenants e usuários com trilha auditável.

### Escopo desta rodada

#### In scope

- correção de contratos quebrados
- recuperação do smoke da UI
- recuperação da suíte backend
- correção da integridade do corpus
- robustez de ingestão e fallback operacional
- fechamento de lacunas de observabilidade operacional
- base de governança e runtime para continuar a fase enterprise

#### Out of scope

- autenticação corporativa externa completa
- billing
- white-label visual completo
- workflows enterprise avançados além da fundação necessária

### Regras de negócio mínimas

- login só é válido se frontend e backend compartilharem o mesmo contrato
- tenant ativo deve restringir workspace efetivo
- corpus ativo exige paridade `raw/chunks`
- nenhuma phase pode ser declarada concluída com smoke quebrado
- nenhum gate pode ser assumido apenas por existência de tela ou endpoint

### Requisitos não funcionais prioritários

- suíte principal verde
- smoke crítico verde
- rastreabilidade com logs estruturados
- reindex e recuperação reproduzíveis
- latência e groundedness visíveis
- continuidade operacional documentada

### Métricas de sucesso desta rodada

- `pytest -q` sem falhas
- `pnpm -C frontend test:smoke` sem falhas
- `0` raws órfãos no corpus ativo
- login web funcional
- groundedness_rate da avaliação principal acima do baseline auditado
- audit e repair logs começando a registrar uso real

---

## 5. SPEC

### Objetivo

Traduzir o PRD corretivo em arquitetura, contratos, domínio e backlog executável.

### Visão arquitetural desta rodada

Estilo: correção incremental sobre a arquitetura atual, sem reescrita.

Componentes sob intervenção:

- frontend session layer
- backend auth/session contract
- pipeline de ingestão
- registry/corpus integrity
- retrieval metadata contract
- evaluation and telemetry loop
- admin/governance foundation

### Bounded contexts relevantes

- `Auth & Session`
- `Tenant & Workspace Governance`
- `Corpus & Ingestion`
- `Retrieval & Ranking`
- `Answer & Grounding`
- `Evaluation & Telemetry`
- `Frontend Experience`

### Contratos prioritários a estabilizar

1. `LoginRequest`
2. `EnterpriseSession`
3. upload + persistência de documento
4. `SearchResponse` com metadata de reranking
5. contrato de dataset real versus placeholder
6. query logs e métricas agregadas

### Dados e persistência

- corpus ativo deve ser a única fonte operacional válida
- estado enterprise em disco deve permanecer consistente
- logs administrativos devem ser consumíveis como trilha de auditoria

### Permissões e auditoria

- roles `admin`, `operator`, `viewer` continuam como base
- ações sensíveis devem registrar evento administrativo
- trilha administrativa precisa sair de “persistida” para “operável”

### Dependências críticas

- Qdrant
- arquivos canônicos do corpus
- `frontend` consumindo o contrato correto da API
- logs consistentes para auditoria pós-fix

### Critério de SPEC ready desta rodada

- escopo corretivo fechado
- contratos prioritários identificados
- backlog ordenado
- gates objetivos definidos

---

## 6. BUILD

### Estratégia de execução

Executar em phases sequenciais, com sprint fechada e task auditável, sempre obedecendo:

`PHASE → SPRINT → TASK`

### Princípios de execução

- corrigir primeiro o que bloqueia ponta a ponta
- só depois melhorar maturidade de qualidade
- só depois avançar em enterprise aberto
- nenhuma sprint avança sem validação explícita

---

## 7. Roadmap

### Phase 0 — Reconvergência Crítica

**Objetivo:** eliminar bloqueios que impedem operação ponta a ponta e confiança mínima.

**Entregáveis:**

- contrato de login alinhado
- smoke do frontend verde
- suíte backend verde
- corpus sem órfãos

**Risco principal:** correções parciais mascararem regressões em outro ponto da cadeia.

**Critério de sucesso:** sistema premium volta a ser utilizável ponta a ponta em ambiente local controlado.

### Phase 1 — Estabilização Operacional

**Objetivo:** tornar ingestion, retrieval, grounding e métricas confiáveis para operação real.

**Entregáveis:**

- ingestão robusta sob indisponibilidade parcial
- contrato de reranking consistente
- dataset e avaliação sem fallback ambíguo
- qualidade operacional observável

**Critério de sucesso:** backend e operação de corpus deixam de depender de comportamento implícito ou frágil.

### Phase 2 — Hardening Premium

**Objetivo:** recuperar a leitura de Fase 2 como produto premium de fato estável.

**Entregáveis:**

- groundedness melhorada
- dashboard e auditoria alinhados à realidade
- fluxo visual consistente com evidência real

**Critério de sucesso:** gate visual da Fase 2 volta a ser defensável com evidência atual.

### Phase 3 — Fundação Enterprise Confiável

**Objetivo:** fechar os gaps reais de Fase 3 sem inflar escopo.

**Entregáveis:**

- governança mais operável
- observabilidade enterprise mínima
- trilha administrativa utilizável
- matriz clara do que ainda não é Fase 3 concluída

**Critério de sucesso:** plataforma fica pronta para nova rodada auditável de enterprise readiness.

---

## 8. Backlog Master

### P0 — Crítico

#### Item P0.1

- título: alinhar contrato de login entre frontend e backend
- módulo: auth/session
- dependência: nenhuma
- phase sugerida: Phase 0
- risco: crítico
- impacto: máximo

#### Item P0.2

- título: recuperar smoke do frontend
- módulo: frontend experience
- dependência: P0.1
- phase sugerida: Phase 0
- risco: crítico
- impacto: máximo

#### Item P0.3

- título: zerar falhas da suíte backend
- módulo: backend quality
- dependência: nenhuma
- phase sugerida: Phase 0
- risco: crítico
- impacto: máximo

#### Item P0.4

- título: reparar consistência do corpus ativo
- módulo: corpus/integrity
- dependência: nenhuma
- phase sugerida: Phase 0
- risco: crítico
- impacto: alto

### P1 — Alta Prioridade

#### Item P1.1

- título: reduzir acoplamento rígido da ingestão ao Qdrant
- módulo: ingestion
- dependência: P0.3
- phase sugerida: Phase 1
- risco: alto
- impacto: alto

#### Item P1.2

- título: corrigir contrato de reranking e metadata de search
- módulo: retrieval
- dependência: P0.3
- phase sugerida: Phase 1
- risco: alto
- impacto: alto

#### Item P1.3

- título: remover ambiguidade de placeholder dataset
- módulo: evaluation
- dependência: P0.3
- phase sugerida: Phase 1
- risco: alto
- impacto: médio

#### Item P1.4

- título: consolidar trilha de admin events como auditoria utilizável
- módulo: governance/admin
- dependência: P0.2
- phase sugerida: Phase 1
- risco: médio
- impacto: alto

### P2 — Média Prioridade

#### Item P2.1

- título: elevar groundedness e citation coverage do fluxo principal
- módulo: answer/grounding
- dependência: P1.2 e P1.3
- phase sugerida: Phase 2
- risco: médio
- impacto: alto

#### Item P2.2

- título: alinhar dashboard e auditoria com métricas realmente confiáveis
- módulo: frontend/dashboard/audit
- dependência: P1.3
- phase sugerida: Phase 2
- risco: médio
- impacto: médio

#### Item P2.3

- título: criar observabilidade enterprise mínima
- módulo: telemetry/runtime
- dependência: P1.4
- phase sugerida: Phase 3
- risco: médio
- impacto: alto

### P3 — Baixa Prioridade

#### Item P3.1

- título: branding por tenant
- módulo: enterprise ui
- dependência: Phase 3
- phase sugerida: Phase 3
- risco: baixo
- impacto: médio

#### Item P3.2

- título: workflows de aprovação
- módulo: governance
- dependência: observabilidade e governança estáveis
- phase sugerida: Phase 3
- risco: médio
- impacto: médio

---

## 9. Sprints e Tasks

### Sprint 0.1 — Contratos e Login

**Objetivo:** restabelecer autenticação ponta a ponta no frontend canônico.

#### Task 0.1.1

**O que:** corrigir o contrato de login compartilhado  
**Onde:** `frontend/types`, `frontend/lib/api`, `frontend/app/login`, `src/models/schemas.py`, `src/api/main.py`  
**Como:** tornar request/response consistentes sem contrato fantasma  
**Dependência:** nenhuma  
**Critério de pronto:** UI consegue autenticar e sair de `/login`

#### Task 0.1.2

**O que:** revalidar sessão, logout e switch tenant  
**Onde:** frontend session provider + backend enterprise session  
**Como:** executar fluxo completo com credenciais demo e tenant válido  
**Dependência:** 0.1.1  
**Critério de pronto:** sessão carrega, troca tenant e mantém navegação por role

### Sprint 0.2 — Suite Recovery

**Objetivo:** recuperar confiança mínima de engenharia.

#### Task 0.2.1

**O que:** corrigir falha de metadata de reranking  
**Onde:** `src/services/vector_service.py` e testes correspondentes  
**Como:** alinhar regra de aplicação versus metadata esperada  
**Dependência:** nenhuma  
**Critério de pronto:** teste de reranking passa

#### Task 0.2.2

**O que:** corrigir falhas de ingestão em testes offline  
**Onde:** `src/services/ingestion_service.py` e dependências  
**Como:** permitir comportamento previsível quando Qdrant não está acessível  
**Dependência:** nenhuma  
**Critério de pronto:** testes de semantic/reindex passam

#### Task 0.2.3

**O que:** corrigir integridade do corpus que quebra `test_active_corpus_has_matching_chunks`  
**Onde:** `src/data/documents/default`  
**Como:** reparar ou remover raws órfãos conforme fonte canônica  
**Dependência:** nenhuma  
**Critério de pronto:** paridade `raw/chunks` restabelecida

### Sprint 0.3 — Smoke Recovery

**Objetivo:** restaurar validação visual premium.

#### Task 0.3.1

**O que:** reexecutar smoke após correções do login  
**Onde:** `frontend/tests/phase2-gate.spec.ts` e módulos impactados  
**Como:** validar desktop, upload, busca, chat e tablet  
**Dependência:** Sprint 0.1  
**Critério de pronto:** `pnpm -C frontend test:smoke` verde

### Sprint 1.1 — Ingestão e Corpus

**Objetivo:** estabilizar ingestão e reindex.

#### Task 1.1.1

**O que:** desenhar fallback operacional seguro de ingestão  
**Onde:** `ingestion_service`, `vector_service`, scripts de corpus  
**Como:** separar persistência local, indexação e recuperação  
**Dependência:** Sprint 0.2  
**Critério de pronto:** pipeline não perde documento por indisponibilidade transitória

#### Task 1.1.2

**O que:** ligar audit e repair a uso real  
**Onde:** endpoints de corpus + logs  
**Como:** executar auditoria real e reparar pelo menos um caso validado  
**Dependência:** 1.1.1  
**Critério de pronto:** `audit.jsonl` e `repair.jsonl` deixam de estar zerados

### Sprint 1.2 — Evaluation & Telemetry

**Objetivo:** tornar avaliação defensável.

#### Task 1.2.1

**O que:** eliminar ambiguidade de placeholder dataset  
**Onde:** `src/api/main.py`, `evaluation_service`, docs operacionais  
**Como:** diferenciar claramente dataset ausente de dataset válido  
**Dependência:** Sprint 0.2  
**Critério de pronto:** nenhuma rota crítica esconde ausência de dataset real com fallback enganoso

#### Task 1.2.2

**O que:** alinhar métricas agregadas com qualidade real de resposta  
**Onde:** telemetry, aggregate scripts, dashboard data  
**Como:** garantir leitura coerente entre retrieval, low confidence e groundedness  
**Dependência:** 1.2.1  
**Critério de pronto:** operador entende o sistema sem abrir código

### Sprint 2.1 — Grounding Recovery

**Objetivo:** reduzir respostas frágeis e elevar qualidade premium.

#### Task 2.1.1

**O que:** investigar por que hit@5 alto convive com groundedness baixa  
**Onde:** retrieval, answer generation, grounding verification  
**Como:** mapear padrões de falha e corrigir cadeia de resposta  
**Dependência:** Sprint 1.2  
**Critério de pronto:** groundedness principal supera baseline auditado

#### Task 2.1.2

**O que:** refletir melhora real na UI de chat e auditoria  
**Onde:** `frontend/app/chat`, `frontend/app/audit`, contratos de query  
**Como:** expor sinais consistentes de confiança e revisão  
**Dependência:** 2.1.1  
**Critério de pronto:** UX premium volta a ser defensável com evidência real

### Sprint 3.1 — Fundação Enterprise

**Objetivo:** preparar reauditoria da Fase 3.

#### Task 3.1.1

**O que:** consolidar governança básica operável  
**Onde:** admin backend/frontend, audit trail, permissões  
**Como:** transformar base atual em operação reproduzível  
**Dependência:** Sprint 0.3 e 1.2  
**Critério de pronto:** admin panel e eventos administrativos sustentam leitura de governança mínima

#### Task 3.1.2

**O que:** criar observabilidade enterprise mínima  
**Onde:** logs, métricas, tracing básico, alert conditions  
**Como:** implementar o mínimo previsto no BRIEFING e na documentação do produto  
**Dependência:** 3.1.1  
**Critério de pronto:** nova auditoria consegue medir estabilidade, falhas e resposta operacional

---

## 10. AUDIT

### Objetivo

Encerrar cada phase com evidência, não com narrativa.

### Auditorias obrigatórias por rodada

- aderência ao PRD corretivo
- aderência à SPEC corretiva
- análise de runtime
- auditoria de logs
- auditoria de métricas
- gap analysis
- remediation confirmation

### Gates obrigatórios

#### Gate A — Reconvergência crítica

- login funcional
- smoke verde
- `pytest -q` verde
- corpus íntegro

#### Gate B — Estabilização operacional

- ingestão robusta
- dataset sem ambiguidade
- telemetry coerente
- audit/repair com evidência real

#### Gate C — Hardening premium

- groundedness melhorada
- dashboard e auditoria coerentes
- operação premium novamente demonstrável

#### Gate D — Fundação enterprise pronta para reauditoria

- governança operável
- observabilidade mínima
- gaps enterprise remanescentes claramente delimitados

---

## 11. AGENT LOOP / SESSION PERSISTENCE

### Regra operacional

Toda execução deste plano deve obedecer ao loop:

`LER ESTADO → EXECUTAR → VALIDAR → ATUALIZAR ESTADO → DEFINIR PRÓXIMO PASSO`

### Arquivos que devem governar a execução real

- `/docs/99_runtime_state.md`
- `/docs/20_master_execution_log.md`
- `/docs/30_backlog_master.md`

### Regras obrigatórias

- nunca encerrar uma rodada sem `next_action`
- nunca marcar phase concluída sem auditoria e backlog atualizados
- qualquer bloqueio técnico entra como `BLOCKED`
- qualquer decisão de negócio entra como `WAITING_HUMAN_APPROVAL`

### Estado inicial recomendado para iniciar este plano

- `current_engine: BUILD`
- `current_phase: Phase 0 — Reconvergência Crítica`
- `current_sprint: Sprint 0.1 — Contratos e Login`
- `current_task: Task 0.1.1`
- `status: READY_FOR_NEXT_STEP`
- `next_action: alinhar contrato de login entre frontend e backend`

---

## 12. SKILL

### Mapeamento de skill por etapa

- `discovery-engine`
  - usar para consolidar a dor auditada em discovery corretivo
- `prd-engine`
  - usar para fixar escopo, casos de uso e critérios de sucesso desta rodada
- `spec-engine`
  - usar para contratos, domínio, permissões, dados e plano técnico
- `build-engine`
  - usar para phases, sprints, tasks e ordem de execução
- `audit-engine`
  - usar ao final de cada phase e na revalidação do sistema
- `runtime-controller`
  - usar durante toda a execução para não perder estado

### Regra

Nenhuma skill substitui gate.

---

## 13. AGENTS

### Regras de agente para esta trilha

- o agente deve operar como executor disciplinado do pipeline CVG
- o agente não pode pular Discovery/PRD/SPEC só porque há código existente
- o agente não pode assumir fechamento de fase sem evidência atual
- o agente deve tratar documentação, backlog, log e runtime state como artefatos de execução, não como anexos

### Anti-patterns proibidos

- corrigir só o sintoma visual e ignorar contrato
- declarar fase estável com smoke quebrado
- esconder falha de corpus
- aceitar métricas altas de retrieval sem groundedness utilizável
- tratar “tem endpoint” como “tem produto”

---

## 14. RUNTIME

### Estrutura mínima esperada

O sistema deve operar com:

- `99_runtime_state.md` como estado oficial
- `20_master_execution_log.md` como trilha contínua
- `30_backlog_master.md` como backlog vivo

### Ordem operacional de runtime desta trilha

1. carregar estado atual
2. executar a task definida
3. validar com teste, smoke, log ou auditoria
4. atualizar estado
5. atualizar log
6. atualizar backlog
7. decidir próxima task

### Regra de ouro

O plano só está sendo executado corretamente se o próximo passo ficar explícito ao final de cada ciclo.

---

## 15. Ordem Executável Final

### Etapa 1

Reconvergir login, sessão e contrato web.

### Etapa 2

Zerar falhas do backend e restaurar consistência do corpus.

### Etapa 3

Restaurar o smoke completo do frontend premium.

### Etapa 4

Fortalecer ingestão, corpus audit e repair.

### Etapa 5

Corrigir avaliação, dataset e telemetria.

### Etapa 6

Elevar groundedness e confiabilidade premium.

### Etapa 7

Consolidar fundação enterprise para nova auditoria.

### Etapa 8

Executar auditoria completa de revalidação.

---

## 16. Próxima Ação Oficial

Iniciar pela **Sprint 0.1 — Contratos e Login**, atacando primeiro:

- divergência entre `frontend/types/index.ts`
- `frontend/app/login/page.tsx`
- `frontend/lib/api.ts`
- `src/models/schemas.py`
- `src/api/main.py`

Sem isso, qualquer outra correção premium ou enterprise continua bloqueada na experiência principal.

---

## 17. Resultado Esperado

Ao fim desta trilha, o programa deve sair do estado:

- muito construído
- parcialmente confiável
- documentalmente avançado
- operacionalmente inconsistente

para o estado:

- documentado
- validado
- rastreável
- premium realmente utilizável
- com fundação enterprise pronta para nova rodada auditável

