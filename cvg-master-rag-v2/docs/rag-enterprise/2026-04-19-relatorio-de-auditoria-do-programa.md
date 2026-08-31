# Relatório de Auditoria do Programa

**Data:** 2026-04-19  
**Escopo:** auditoria do programa com `docs/rag-enterprise/` como fonte da verdade  
**Workspace:** `cvg-master-rag`  
**Resultado geral:** `62/100`

## Fonte de verdade utilizada

Documentos normativos priorizados:

- `docs/rag-enterprise/0001-visao-geral-e-objetivos.md`
- `docs/rag-enterprise/0007-fase-3-rag-enterprise.md`
- `docs/rag-enterprise/0008-arquitetura-alvo-e-arquitetura-atual.md`
- `docs/rag-enterprise/0009-contratos-de-ingestao.md`
- `docs/rag-enterprise/0010-contratos-de-retrieval.md`
- `docs/rag-enterprise/0011-contratos-de-avaliacao.md`
- `docs/rag-enterprise/0012-modelo-de-dados-e-metadados.md`
- `docs/rag-enterprise/0013-quality-gates.md`
- `docs/rag-enterprise/0019-observabilidade-e-metricas.md`
- `docs/rag-enterprise/0025-visao-final-enterprise-premium.md`
- `docs/rag-enterprise/0026-mapa-de-aderencia-ao-guia.md`
- `docs/rag-enterprise/0029-checklist-do-gate-visual-da-fase-2.md`
- `docs/rag-enterprise/0031-checklist-do-gate-da-fase-3.md`

## Resumo executivo

O programa já possui base material relevante em backend RAG, telemetria, avaliação, frontend premium e fundação enterprise. Porém o estado real não sustenta a leitura de produto plenamente estável porque há quebra no fluxo de login da UI, falhas na suíte backend, inconsistências no corpus ativo e lacunas claras nos requisitos de Fase 3.

O principal desvio entre documentação e implementação atual não é ausência total de features. É ausência de confiabilidade de ponta a ponta em itens que a documentação trata como já validados ou próximos de gate.

## Achados críticos

1. O login do frontend está quebrado por divergência de contrato.
   Evidência:
   - `frontend/types/index.ts` define `LoginRequest` sem `password`
   - `frontend/app/login/page.tsx` envia `{ email, role, tenant_id }`
   - `src/models/schemas.py` exige `email`, `password` e `tenant_id`
2. O smoke test do frontend falhou em `5/5` casos, todos presos em `/login`.
3. A suíte backend não está verde.
   Resultado: `163 passed, 17 skipped, 4 failed`
4. A ingestão depende rigidamente do Qdrant e falha quando o serviço não está acessível.
5. O corpus ativo em disco está inconsistente.
   Evidência: `3` arquivos `*_raw.json` órfãos em `src/data/documents/default`
6. O backend ainda retorna dataset placeholder se o dataset real não existir.
7. Os requisitos enterprise da Fase 3 seguem incompletos em branding, alertas, tracing mínimo, workflows de aprovação e operação comercial pronta.

## Evidências principais

### Backend

- Endpoints presentes:
  - `/documents/upload`
  - `/documents`
  - `/documents/{document_id}`
  - `/search`
  - `/query`
  - `/metrics`
  - `/evaluation/*`
  - `/session`
  - `/auth/*`
  - `/admin/tenants`
  - `/admin/users`
  - `/corpus/audit`
  - `/corpus/repair/{document_id}`
- Há estrutura real para:
  - retrieval híbrido
  - grounding
  - telemetry
  - avaliação
  - sessão enterprise
  - CRUD básico de tenants e usuários

### Frontend

- O app canônico existe em `frontend/`
- `tsc`, `lint` e `build` passam
- Rotas implementadas:
  - `/`
  - `/documents`
  - `/search`
  - `/chat`
  - `/dashboard`
  - `/audit`
  - `/admin`
  - `/login`
  - `/onboarding`
  - `/recover-access`
  - `/forbidden`
- Há shell com navegação por role e seletor de tenant

### Logs e operação

- `src/logs/queries.jsonl`: `29636` eventos
- `src/logs/evaluations.jsonl`: `1354` eventos
- `src/logs/ingestion.jsonl`: `126` eventos
- `src/logs/admin_events.jsonl`: `2089` eventos
- `src/logs/audit.jsonl`: `0`
- `src/logs/repair.jsonl`: `0`

### Métricas observadas em logs

Agregado em `queries.jsonl`:

- `grounded_rate = 0.634`
- `low_confidence_rate = 0.0658`
- `needs_review_rate = 0.3636`
- `avg_citation_coverage = 0.6731`
- `avg_latency_ms = 54.1`

Última avaliação `default` com `30` perguntas:

- `timestamp = 2026-04-19T04:32:59.774540+00:00`
- `hit_at_1 = 1.0`
- `hit_at_3 = 1.0`
- `hit_at_5 = 1.0`
- `low_confidence_rate = 0.5667`
- `groundedness_rate = 0.2667`
- `avg_score = 0.6147`
- `avg_latency_ms = 39.1`

Isso indica retrieval muito forte no critério de documento correto, mas qualidade de groundedness e confiança operacional ainda fracas.

## Notas por item

- Ingestão e parsing: `72/100`
- Corpus canônico e metadata: `64/100`
- Retrieval híbrido: `78/100`
- Resposta, citações e grounding: `67/100`
- Avaliação e benchmarking: `70/100`
- Observabilidade e métricas: `68/100`
- Frontend premium Fase 2: `58/100`
- Autenticação e sessão: `45/100`
- Multitenancy e isolamento: `62/100`
- Admin e governança: `56/100`
- RBAC e segurança: `54/100`
- Operação enterprise e readiness comercial: `35/100`
- Documentação operacional aderente ao estado atual: `71/100`

## Justificativa das notas

### Ingestão e parsing — 72/100

Pontos fortes:

- contrato de upload implementado
- suporte a `pdf`, `docx`, `md`, `txt`
- persistência em disco
- chunking e embeddings integrados

Gaps:

- ingestão falha se Qdrant estiver indisponível
- isso reduz resiliência operacional e testabilidade offline

### Corpus canônico e metadata — 64/100

Pontos fortes:

- registry filesystem-backed existe
- listagem e metadata seguem bem o contrato

Gaps:

- corpus ativo não está íntegro
- existem raws sem chunks correspondentes

### Retrieval híbrido — 78/100

Pontos fortes:

- dense + sparse + RRF implementados
- filtros por metadata presentes
- query expansion e reranking existem

Gaps:

- contrato de `reranking_applied` está inconsistente
- há falha explícita de teste cobrando isso

### Resposta, citações e grounding — 67/100

Pontos fortes:

- pipeline `search + answer + grounding` existe
- citações estruturadas existem
- `low_confidence` e `needs_review` são expostos

Gaps:

- groundedness real observada ainda está abaixo do esperado para maturidade premium
- muitas respostas continuam indo para revisão

### Avaliação e benchmarking — 70/100

Pontos fortes:

- dataset default com `30` perguntas
- endpoints de avaliação e A/B disponíveis
- logs de avaliação abundantes

Gaps:

- backend ainda tolera placeholder dataset
- falta melhor coerência entre métricas de retrieval e qualidade final da resposta

### Observabilidade e métricas — 68/100

Pontos fortes:

- JSONL estruturado
- métricas agregadas
- `request_id` e scripts de agregação

Gaps:

- sem tracing enterprise real
- sem alertas configurados
- sem evidência de dashboards enterprise de observabilidade

### Frontend premium Fase 2 — 58/100

Pontos fortes:

- frontend existe e builda
- módulos principais estão implementados
- organização coerente com a visão premium

Gaps:

- smoke oficial falhou por completo
- isso invalida a estabilidade ponta a ponta da camada premium

### Autenticação e sessão — 45/100

Pontos fortes:

- sessão server-side existe
- logout, switch tenant e recuperação existem

Gaps:

- contrato de login frontend/backend está quebrado
- recuperação é apenas fila fake, sem fluxo real

### Multitenancy e isolamento — 62/100

Pontos fortes:

- `workspace_id` aparece transversalmente
- rotas sensíveis fazem checagem de workspace ativo
- tenant switch está implementado

Gaps:

- falta evidência reproduzível de isolamento enterprise ponta a ponta
- branding por tenant ainda ausente

### Admin e governança — 56/100

Pontos fortes:

- CRUD de tenants e usuários existe
- eventos administrativos são persistidos

Gaps:

- trilha de auditoria administrativa não está exposta como operação de produto
- governança ainda é fundação, não camada madura

### RBAC e segurança — 54/100

Pontos fortes:

- gating por role existe no frontend e backend

Gaps:

- auth forte não implementada
- políticas de retenção não aparecem
- fluxo comercial seguro ainda não está caracterizado

### Operação enterprise e readiness comercial — 35/100

Pontos fortes:

- fundação enterprise existe

Gaps:

- sem dashboard executivo enterprise validado
- sem alertas
- sem tracing mínimo
- sem workflows de aprovação
- sem evidência de SLA/uptime/error-rate como gate real

### Documentação operacional aderente ao estado atual — 71/100

Pontos fortes:

- `docs/rag-enterprise/` é forte, detalhada e normativa

Gaps:

- `src/README.md` ainda descreve o sistema como Fase 0
- parte da documentação executiva assume um estado mais estável do que a implementação atual comprova

## Comandos executados na auditoria

- `pytest -q`
- `pnpm -C frontend exec tsc --noEmit`
- `pnpm -C frontend lint`
- `pnpm -C frontend build`
- `pnpm -C frontend test:smoke`
- inspeção de `src/api/main.py`
- inspeção de `src/services/*`
- inspeção de `frontend/app/*`
- leitura de contratos e gates em `docs/rag-enterprise/`
- leitura e agregação de `src/logs/*.jsonl`

## Resultados de validação

### Backend

- `pytest -q`: `163 passed, 17 skipped, 4 failed`

Falhas observadas:

- metadata de reranking inconsistente
- ingestão sem tolerância à indisponibilidade do Qdrant em testes específicos
- corpus ativo com raws órfãos

### Frontend

- `pnpm -C frontend exec tsc --noEmit`: passou
- `pnpm -C frontend lint`: passou
- `pnpm -C frontend build`: passou
- `pnpm -C frontend test:smoke`: `5 failed`

Causa imediata do smoke:

- login não sai de `/login`
- provável causa raiz: incompatibilidade entre payload enviado pelo frontend e contrato esperado pelo backend

## Referências técnicas diretas

- Divergência de login:
  - `frontend/types/index.ts`
  - `frontend/app/login/page.tsx`
  - `src/models/schemas.py`
- Dependência rígida de Qdrant:
  - `src/services/ingestion_service.py`
- Contrato de reranking:
  - `src/services/vector_service.py`
- Placeholder dataset:
  - `src/api/main.py`

## Conclusão

O programa está acima de um protótipo e abaixo de uma plataforma enterprise confiável. A base é real e ampla, mas o estado atual ainda tem falhas bloqueantes para leitura de maturidade consolidada, principalmente em:

- autenticação/login ponta a ponta
- estabilidade da suíte
- integridade do corpus
- qualidade operacional de grounding
- fechamento efetivo dos critérios enterprise

## Recomendação imediata

Prioridade alta de correção:

1. alinhar contrato de login entre frontend e backend
2. zerar as `4` falhas do `pytest`
3. reparar os `3` raws órfãos no corpus ativo
4. restabelecer o smoke da Fase 2
5. só depois reabrir a discussão de fechamento de gate enterprise
